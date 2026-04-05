"""
SwingTrader MCP server — Supabase (scan_runs, scan_rows, scan_jobs) + background screeners.

Run from repo root:
  python -m swingtrader_mcp.server

Cursor / Claude Desktop (example):
  "command": "python",
  "args": ["-m", "swingtrader_mcp.server"],
  "cwd": "/absolute/path/to/swingtrader"

Requires: pip install mcp supabase psycopg2-binary (see requirements.txt)
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv(dotenv_path=_REPO_ROOT / ".env")


def _load_db_module():
    """Load src/db.py without importing src/__init__ (keeps MCP deps minimal)."""
    path = _REPO_ROOT / "src" / "db.py"
    spec = importlib.util.spec_from_file_location("swingtrader_db", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_db = _load_db_module()
ensure_schema: Callable = _db.ensure_schema
create_scan_job: Callable = _db.create_scan_job
update_scan_job_pid: Callable = _db.update_scan_job_pid
update_scan_job_progress: Callable = _db.update_scan_job_progress
finish_scan_job: Callable = _db.finish_scan_job
get_supabase_client: Callable = _db.get_supabase_client
get_schema: Callable = _db.get_schema


mcp = FastMCP(
    "swingtrader",
    instructions="""
You are Hans, an AI trading assistant built on top of the SwingTrader screener.
SwingTrader applies the Minervini SEPA + O'Neil CAN SLIM methodology to identify
high-quality growth stocks in confirmed uptrends near actionable buy points.

## Your Daily Analytics Workflow

### Step 1 — Trigger the Screener
Call `run_json_screener` to start a full screening run in the background.
The screener runs a 5-step pipeline: market gate → liquidity filter → Minervini
trend template → O'Neil fundamentals → sector + institutional check.
Poll `get_scan_job(job_id)` until status = "completed" before proceeding.

### Step 2 — Market Gate (read first)
Check `result["market"]` from `get_latest_screener_result` or `get_run_detail`.
Key fields:
- `condition`: "uptrend" | "uptrend_under_pressure" | "qqq_lagging" | "correction" | "downtrend"
- `is_confirmed_uptrend`: True only when BOTH SPX and QQQ confirm uptrend
- `spx_condition` / `qqq_condition`: individual index assessments
- `distribution_days` / `qqq_distribution_days`: O'Neil danger signal at ≥5

If `is_confirmed_uptrend` is False → tell the user to be defensive. No new positions.
If `qqq_lagging` → SPX holding up but Nasdaq weakening; be selective, favour large-caps.

### Step 3 — Review the Shortlist
Call `get_screener_summary(run_id)` for counts and sector breakdown.
Call `get_near_pivot_stocks(run_id)` to focus on stocks nearest their buy point.
Call `get_passed_stocks(run_id)` for the full list.

Prioritise stocks where ALL of the following are true:
- `rs_rank` ≥ 80          (top 20% momentum vs full NYSE/NASDAQ universe)
- `within_buy_range` True  (price 0–5% above pivot — O'Neil: don't chase beyond 5%)
- `accumulation` True      (up/down volume ratio ≥ 1.25 — institutional buying)
- `roe_above_17pct` True   (Minervini quality filter)
- `rs_line_new_high` True  (RS line confirming breakout — strongest O'Neil signal)
- `inst_shares_increasing` True (net institutional share increase)

Secondary considerations:
- `adr_pct` 3–15%: ideal volatility range for position sizing
- `vol_ratio_today` > 1.4 on a breakout day: O'Neil volume confirmation
- `inst_pct_accumulating` > 50%: majority of holders adding to positions
- `eps_accelerating` True: growth rate speeding up (SEPA criterion)

### Step 4 — Earnings Awareness
Call `get_earnings_alerts(days_ahead=21)` to find watchlist stocks reporting
within 3 weeks. Stocks within 3 weeks of earnings are HIGH RISK for position
entries — Minervini and O'Neil both advise avoiding new buys before earnings
unless you intend to hold through the report.

### Step 5 — Communicate to the User
Send a Telegram message summarising:
1. Market regime (uptrend / defensive)
2. Number of stocks passing all criteria
3. Top 3–5 names by rs_rank, with: sector, price vs pivot (extension_pct),
   RS rank, ROE, whether RS line is at a new high
4. Any earnings alerts for the next 3 weeks

## Key Methodology Notes
- **Never chase**: `extension_pct` > 5% means the stock is extended — flag it, do not recommend buying
- **Volume matters**: A breakout on below-average volume is suspect; `vol_ratio_today` < 1.0 on a breakout = weak signal
- **Market first**: No individual stock analysis matters if `is_confirmed_uptrend` is False
- **VCP is manual**: Volatility Contraction Patterns require chart review — flag `vol_contracting_in_base` as a prompt for the user to check the chart
- **Earnings = risk**: Stocks within 21 days of earnings should be flagged, not recommended for new entries
- **Stage analysis**: The screener catches Stage 2 uptrends (Weinstein). Avoid Stage 3 (extended) and Stage 4 (downtrend) stocks

## Supabase Schema (swingtrader)
- `scan_runs`: one row per screening run (id, scan_date, source, market_json, result_json)
- `scan_rows`: normalised per-stock rows (run_id, dataset, symbol, row_data JSON)
  - datasets: "passed_stocks" (run_screener), "trend_template" / "rs_rating" (ibd_screener)
- `scan_jobs`: process state (status, pid, stdout_log, stderr_log, progress_message)

## Tool Quick Reference
| Goal | Tool |
|---|---|
| Start full IBD+Minervini screen | `run_json_screener` |
| Start market-wide Minervini screen | `run_ibd_market_screener` |
| Check job status | `get_scan_job(job_id)` |
| Latest completed result | `get_latest_screener_result` |
| Summary stats for a run | `get_screener_summary(run_id)` |
| Stocks near buy point | `get_near_pivot_stocks(run_id)` |
| All passed stocks | `get_passed_stocks(run_id)` |
| Upcoming earnings for watchlist | `get_earnings_alerts(days_ahead=21)` |
| Raw row data (paginated) | `get_scan_rows(run_id, dataset)` |
""",
)

_SCAN_SOURCE_BY_SCRIPT: dict[str, str] = {
    "scripts/run_screener.py": "run_screener",
    "ibd_screener.py": "ibd_screener",
}


def _scan_source_for_script(rel_script: str) -> str:
    key = Path(rel_script).as_posix()
    return _SCAN_SOURCE_BY_SCRIPT.get(key, key)


def _get_client():
    client = get_supabase_client()
    ensure_schema()
    return client


def _tbl(client, table: str):
    return client.schema(get_schema()).table(table)


def _resolve_passed_dataset(client, run_id: int) -> tuple[str, Optional[str]]:
    """Return (dataset_name, passed_flag_field) for a run."""
    res = _tbl(client, "scan_rows").select("dataset").eq("run_id", run_id).execute()
    datasets = {r["dataset"] for r in (res.data or [])}
    if "passed_stocks" in datasets:
        return "passed_stocks", None
    if "trend_template" in datasets:
        return "trend_template", "Passed"
    return "", None


def _extract_stock_fields(row_data: dict[str, Any]) -> dict[str, Any]:
    symbol = row_data.get("symbol") or row_data.get("ticker") or row_data.get("Symbol")
    return {
        "symbol": symbol,
        "sector": row_data.get("sector") or row_data.get("Sector"),
        "industry": row_data.get("subSector") or row_data.get("industry") or row_data.get("Industry"),
        "price": row_data.get("price") or row_data.get("Price"),
        "pivot": row_data.get("pivot"),
        "extension_pct": row_data.get("extension_pct"),
        "within_buy_range": row_data.get("within_buy_range"),
        "extended": row_data.get("extended"),
        "accumulation": row_data.get("accumulation"),
        "rs_line_new_high": row_data.get("rs_line_new_high"),
        "rs_over_70": row_data.get("RSOver70"),
        "adr_pct": row_data.get("adr_pct"),
        "vol_ratio_today": row_data.get("vol_ratio_today"),
        "up_down_vol_ratio": row_data.get("up_down_vol_ratio"),
        "eps_growth_yoy": row_data.get("eps_growth_yoy"),
        "rev_growth_yoy": row_data.get("rev_growth_yoy"),
        "rs_rank": row_data.get("rs_rank"),
        "roe": row_data.get("roe"),
        "roe_above_17pct": row_data.get("roe_above_17pct"),
        "inst_holders_increasing": row_data.get("inst_holders_increasing"),
        "inst_shares_increasing": row_data.get("inst_shares_increasing"),
        "inst_ownership_pct": row_data.get("inst_ownership_pct"),
        "inst_ownership_pct_increasing": row_data.get("inst_ownership_pct_increasing"),
        "inst_pct_accumulating": row_data.get("inst_pct_accumulating"),
    }


@mcp.tool()
def get_scan_jobs(limit: int = 25) -> str:
    """
    Screening process state from Supabase (scan_jobs): running / completed / failed,
    PID, logs, linked scan_run_id when finished.
    """
    limit = max(1, min(int(limit), 200))
    client = _get_client()
    res = (
        _tbl(client, "scan_jobs")
        .select(
            "id,created_at,started_at,finished_at,status,scan_source,script_rel,"
            "args_json,pid,exit_code,scan_run_id,stdout_log,stderr_log,error_message,progress_message"
        )
        .order("id", desc=True)
        .limit(limit)
        .execute()
    )
    return json.dumps(res.data or [], default=str)


@mcp.tool()
def get_scan_job(job_id: int) -> str:
    """Single scan_jobs row by id."""
    client = _get_client()
    res = (
        _tbl(client, "scan_jobs")
        .select(
            "id,created_at,started_at,finished_at,status,scan_source,script_rel,"
            "args_json,pid,exit_code,scan_run_id,stdout_log,stderr_log,error_message,progress_message"
        )
        .eq("id", job_id)
        .single()
        .execute()
    )
    if not res.data:
        return json.dumps({"error": "job_id not found", "job_id": job_id})
    return json.dumps(res.data, default=str)


@mcp.tool()
def list_scan_runs(limit: int = 20) -> str:
    """List recent screening runs (id, scan_date, source, created_at). JSON array."""
    limit = max(1, min(int(limit), 200))
    client = _get_client()
    res = (
        _tbl(client, "scan_runs")
        .select("id,created_at,scan_date,source,market_json,result_json")
        .order("id", desc=True)
        .limit(limit)
        .execute()
    )
    # Replace heavy JSON blobs with lengths for the listing
    rows = []
    for r in (res.data or []):
        rows.append({
            "id": r["id"],
            "created_at": r["created_at"],
            "scan_date": r["scan_date"],
            "source": r["source"],
            "market_json_len": len(r.get("market_json") or ""),
            "result_json_len": len(r.get("result_json") or ""),
        })
    return json.dumps(rows, default=str)


@mcp.tool()
def get_run_detail(run_id: int) -> str:
    """Return one scan_runs row including market_json and result_json."""
    client = _get_client()
    res = (
        _tbl(client, "scan_runs")
        .select("id,created_at,scan_date,source,market_json,result_json")
        .eq("id", run_id)
        .single()
        .execute()
    )
    if not res.data:
        return json.dumps({"error": "run_id not found", "run_id": run_id})
    return json.dumps(res.data, default=str)


@mcp.tool()
def get_scan_rows(
    run_id: int,
    dataset: Optional[str] = None,
    symbol: Optional[str] = None,
    limit: int = 500,
    offset: int = 0,
) -> str:
    """
    Rows from scan_rows for a run. dataset filters: trend_template, rs_rating, quote, passed_stocks.
    Use offset for pagination. row_data is parsed JSON per row.
    """
    limit = max(1, min(int(limit), 5000))
    offset = max(0, int(offset))
    client = _get_client()

    q = _tbl(client, "scan_rows").select("run_id,scan_date,dataset,symbol,row_data", count="exact").eq("run_id", run_id)
    if dataset:
        q = q.eq("dataset", dataset)
    if symbol:
        q = q.eq("symbol", symbol.upper())

    res = q.order("symbol").range(offset, offset + limit - 1).execute()

    out = []
    for rec in (res.data or []):
        raw = rec.get("row_data")
        if isinstance(raw, str):
            try:
                rec["row_data_parsed"] = json.loads(raw)
            except json.JSONDecodeError:
                rec["row_data_parsed"] = None
        out.append(rec)

    total = res.count if res.count is not None else len(out)
    return json.dumps({"total": total, "offset": offset, "limit": limit, "rows": out}, default=str)


@mcp.tool()
def get_screener_summary(run_id: int) -> str:
    """
    Aggregate stats for a run: total scanned, passed trend template, within buy range,
    near-pivot count, and sector breakdown.
    """
    client = _get_client()

    src_res = _tbl(client, "scan_runs").select("source,scan_date,result_json").eq("id", run_id).single().execute()
    if not src_res.data:
        return json.dumps({"error": "run_id not found", "run_id": run_id})

    source = src_res.data["source"]
    scan_date = src_res.data["scan_date"]
    result_json = src_res.data.get("result_json")

    # Fast path: run_screener stores top-level counts in result_json
    if source == "run_screener" and result_json:
        try:
            result = json.loads(result_json)
            passed = result.get("passed_stocks") or []
            within_buy = sum(1 for s in passed if s.get("within_buy_range"))
            near_pivot = sum(
                1 for s in passed
                if not s.get("extended")
                and s.get("extension_pct") is not None
                and s["extension_pct"] <= 5
            )
            sector_counts: dict[str, int] = {}
            for s in passed:
                sec = s.get("sector") or "Unknown"
                sector_counts[sec] = sector_counts.get(sec, 0) + 1
            return json.dumps({
                "run_id": run_id,
                "source": source,
                "scan_date": str(scan_date),
                "market_condition": (result.get("market") or {}).get("condition"),
                "distribution_days": (result.get("market") or {}).get("distribution_days"),
                "total_ibd_tickers": result.get("total_ibd_tickers"),
                "total_after_liquidity": result.get("total_after_liquidity"),
                "pre_screened_count": result.get("pre_screened_count"),
                "passed_trend_template": result.get("passed_count"),
                "within_buy_range": within_buy,
                "near_pivot_count": near_pivot,
                "error_count": result.get("error_count"),
                "sector_breakdown": dict(sorted(sector_counts.items(), key=lambda x: -x[1])),
            }, default=str)
        except (json.JSONDecodeError, TypeError):
            pass

    # Generic path: derive stats from scan_rows in Python
    dataset, passed_field = _resolve_passed_dataset(client, run_id)
    if not dataset:
        return json.dumps({"error": "no usable dataset in scan_rows", "run_id": run_id})

    rows_res = (
        _tbl(client, "scan_rows")
        .select("symbol,row_data")
        .eq("run_id", run_id)
        .eq("dataset", dataset)
        .execute()
    )
    all_rows = rows_res.data or []

    passed_count = 0
    within_buy = 0
    near_pivot = 0
    sector_counts = {}

    for rec in all_rows:
        try:
            rd = json.loads(rec.get("row_data") or "{}")
        except (json.JSONDecodeError, TypeError):
            rd = {}

        if passed_field and not rd.get(passed_field):
            continue
        passed_count += 1

        if rd.get("within_buy_range"):
            within_buy += 1

        ext = rd.get("extension_pct")
        try:
            if ext is not None and float(ext) <= 5 and not rd.get("extended"):
                near_pivot += 1
        except (TypeError, ValueError):
            pass

        sec = rd.get("sector") or "Unknown"
        sector_counts[sec] = sector_counts.get(sec, 0) + 1

    return json.dumps({
        "run_id": run_id,
        "source": source,
        "scan_date": str(scan_date),
        "dataset": dataset,
        "total_scanned": len(all_rows),
        "passed_trend_template": passed_count,
        "within_buy_range": within_buy,
        "near_pivot_count": near_pivot,
        "sector_breakdown": dict(sorted(sector_counts.items(), key=lambda x: -x[1])),
    }, default=str)


@mcp.tool()
def get_passed_stocks(
    run_id: int,
    sector: Optional[str] = None,
    limit: int = 200,
) -> str:
    """
    Stocks that passed the full screen for a run, with a minimal field set.
    Optionally filter by sector (case-insensitive substring match).
    """
    limit = max(1, min(int(limit), 2000))
    client = _get_client()
    dataset, passed_field = _resolve_passed_dataset(client, run_id)
    if not dataset:
        return json.dumps({"error": "no usable dataset in scan_rows", "run_id": run_id})

    res = (
        _tbl(client, "scan_rows")
        .select("symbol,row_data")
        .eq("run_id", run_id)
        .eq("dataset", dataset)
        .order("symbol")
        .limit(limit)
        .execute()
    )

    out = []
    for row in (res.data or []):
        try:
            rd = json.loads(row.get("row_data") or "{}")
        except (json.JSONDecodeError, TypeError):
            rd = {}
        if passed_field and not rd.get(passed_field):
            continue
        rec = _extract_stock_fields(rd)
        if sector and not (
            sector.lower() in (rec.get("sector") or "").lower()
            or sector.lower() in (rec.get("industry") or "").lower()
        ):
            continue
        out.append(rec)

    return json.dumps({"run_id": run_id, "count": len(out), "stocks": out}, default=str)


@mcp.tool()
def get_near_pivot_stocks(
    run_id: int,
    min_ext_pct: float = -5.0,
    max_ext_pct: float = 5.0,
    require_accumulation: bool = False,
) -> str:
    """
    Passed stocks within a buy range defined by extension_pct bounds (default -5% to +5%).
    Sorted by extension_pct ascending (closest-to-pivot first).
    """
    client = _get_client()
    dataset, passed_field = _resolve_passed_dataset(client, run_id)
    if not dataset:
        return json.dumps({"error": "no usable dataset in scan_rows", "run_id": run_id})

    res = (
        _tbl(client, "scan_rows")
        .select("symbol,row_data")
        .eq("run_id", run_id)
        .eq("dataset", dataset)
        .order("symbol")
        .execute()
    )

    out = []
    for row in (res.data or []):
        try:
            rd = json.loads(row.get("row_data") or "{}")
        except (json.JSONDecodeError, TypeError):
            rd = {}
        if passed_field and not rd.get(passed_field):
            continue
        ext = rd.get("extension_pct")
        if ext is None:
            continue
        try:
            ext = float(ext)
        except (TypeError, ValueError):
            continue
        if not (min_ext_pct <= ext <= max_ext_pct):
            continue
        if require_accumulation and not rd.get("accumulation"):
            continue
        rec = _extract_stock_fields(rd)
        rec["extension_pct"] = ext
        out.append(rec)

    out.sort(key=lambda r: r.get("extension_pct") or 0)
    return json.dumps({"run_id": run_id, "count": len(out), "stocks": out}, default=str)


@mcp.tool()
def get_latest_screener_result() -> str:
    """
    Actionable output of the most recent completed screening run.
    Returns summary stats + passed stocks (minimal fields).
    """
    client = _get_client()

    job_res = (
        _tbl(client, "scan_jobs")
        .select("scan_run_id,scan_source,finished_at")
        .eq("status", "completed")
        .not_.is_("scan_run_id", "null")
        .order("finished_at", desc=True)
        .limit(1)
        .execute()
    )

    if job_res.data:
        run_id = int(job_res.data[0]["scan_run_id"])
    else:
        run_res = _tbl(client, "scan_runs").select("id").order("id", desc=True).limit(1).execute()
        if not run_res.data:
            return json.dumps({"error": "no completed screening runs found"})
        run_id = int(run_res.data[0]["id"])

    summary = json.loads(get_screener_summary(run_id))
    passed = json.loads(get_passed_stocks(run_id))
    return json.dumps({
        "run_id": run_id,
        "summary": summary,
        "passed_stocks": passed.get("stocks", []),
    }, default=str)


def _start_repo_script(rel_script: str, args: list[str]) -> dict[str, Any]:
    """Launch job_runner → screening script in the background; record state in Supabase (scan_jobs)."""
    script_path = _REPO_ROOT / rel_script
    if not script_path.is_file():
        return {"ok": False, "started": False, "error": f"script not found: {script_path}"}

    log_dir = _REPO_ROOT / "output" / "mcp_screener_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stem = script_path.stem
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_log = log_dir / f"{stem}_{ts}.out.log"
    err_log = log_dir / f"{stem}_{ts}.err.log"
    out_log_rel = str(out_log.relative_to(_REPO_ROOT))
    err_log_rel = str(err_log.relative_to(_REPO_ROOT))

    scan_source = _scan_source_for_script(rel_script)
    job_id = create_scan_job(scan_source, rel_script, args, out_log_rel, err_log_rel)

    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")

    fo = open(out_log, "w", encoding="utf-8")
    fe = open(err_log, "w", encoding="utf-8")
    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "swingtrader_mcp.job_runner", str(job_id), rel_script] + args,
            cwd=str(_REPO_ROOT),
            stdout=fo,
            stderr=fe,
            env=env,
            start_new_session=True,
        )
    except OSError as e:
        try:
            finish_scan_job(job_id, 1, error_message=f"failed to spawn process: {e}")
        except Exception:
            pass
        return {"ok": False, "started": False, "job_id": job_id, "error": str(e)}
    finally:
        fo.close()
        fe.close()

    update_scan_job_pid(job_id, proc.pid)

    return {
        "ok": True,
        "started": True,
        "job_id": job_id,
        "scan_source": scan_source,
        "pid": proc.pid,
        "script": rel_script,
        "args": args,
        "stdout_log": out_log_rel,
        "stderr_log": err_log_rel,
        "message": (
            "Screening started in the background. Query get_scan_jobs or get_scan_job for status; "
            "when status is completed, scan_run_id links to scan_runs / list_scan_runs."
        ),
    }


@mcp.tool()
def get_earnings_alerts(days_ahead: int = 21, run_id: Optional[int] = None) -> str:
    """
    Returns upcoming earnings for watchlist stocks within the next days_ahead days.
    Loads the watchlist from passed_stocks in the most recent (or specified) scan run.
    """
    import importlib.util as _ilu
    from datetime import datetime as _dt, timedelta as _td

    _fmp_path = _REPO_ROOT / "src" / "fmp.py"
    _fmp_spec = _ilu.spec_from_file_location("swingtrader_fmp", _fmp_path)
    _fmp_mod = _ilu.module_from_spec(_fmp_spec)
    _fmp_spec.loader.exec_module(_fmp_mod)
    fmp_client = _fmp_mod.fmp()

    client = _get_client()

    if run_id is None:
        row = _tbl(client, "scan_runs").select("id").order("id", desc=True).limit(1).execute()
        if not row.data:
            return json.dumps({"error": "no scan runs found"})
        resolved_run_id = int(row.data[0]["id"])
    else:
        resolved_run_id = int(run_id)

    sym_res = (
        _tbl(client, "scan_rows")
        .select("symbol")
        .eq("run_id", resolved_run_id)
        .eq("dataset", "passed_stocks")
        .execute()
    )
    watchlist = {r["symbol"].upper() for r in (sym_res.data or []) if r.get("symbol")}

    if not watchlist:
        return json.dumps({
            "run_id": resolved_run_id,
            "checked_at": _dt.today().strftime("%Y-%m-%d"),
            "alerts": [],
            "message": "Watchlist is empty for this run",
        })

    today = _dt.today()
    from_date = today.strftime("%Y-%m-%d")
    to_date = (today + _td(days=int(days_ahead))).strftime("%Y-%m-%d")

    try:
        cal_df = fmp_client.earnings_calendar_range(from_date, to_date)
    except Exception as e:
        return json.dumps({"error": f"earnings_calendar_range failed: {e}"})

    alerts = []
    if not cal_df.empty and "symbol" in cal_df.columns:
        matches = cal_df[cal_df["symbol"].str.upper().isin(watchlist)]
        for _, row in matches.iterrows():
            earnings_date = str(row.get("date", ""))
            try:
                days_until = (_dt.strptime(earnings_date[:10], "%Y-%m-%d") - today).days
            except (ValueError, TypeError):
                days_until = None
            alerts.append({
                "symbol": row.get("symbol"),
                "earnings_date": earnings_date[:10],
                "time": row.get("time", ""),
                "days_until": days_until,
            })
        alerts.sort(key=lambda x: x["earnings_date"])

    return json.dumps({
        "run_id": resolved_run_id,
        "checked_at": from_date,
        "days_ahead": days_ahead,
        "watchlist_size": len(watchlist),
        "alerts": alerts,
    }, default=str)


@mcp.tool()
def run_json_screener(
    ibd_file: str = "./input/IBD Data Tables.xlsx",
    lookback_days: int = 365,
) -> str:
    """
    Start scripts/run_screener.py (IBD + Minervini pipeline) in the background.
    Returns immediately. Poll get_scan_job(job_id) for status.
    """
    args = ["--ibd-file", ibd_file, "--lookback-days", str(int(lookback_days))]
    return json.dumps(_start_repo_script("scripts/run_screener.py", args), default=str)


@mcp.tool()
def run_ibd_market_screener() -> str:
    """
    Start ibd_screener.py (NYSE/NASDAQ market-wide Minervini screen) in the background.
    Returns immediately. Poll get_scan_job(job_id) for status.
    """
    return json.dumps(_start_repo_script("ibd_screener.py", []), default=str)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
