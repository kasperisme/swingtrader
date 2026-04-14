"""
SwingTrader MCP server — Supabase (scan_runs, scan_rows, scan_jobs) + background screeners.

Run from repo root:
  python -m swingtrader_mcp.server

Cursor / Claude Desktop (example):
  "command": "python",
  "args": ["-m", "swingtrader_mcp.server"],
  "cwd": "/absolute/path/to/swingtrader/code/analytics"

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
from fastmcp import FastMCP

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


def _as_json(val, default=None):
    """Coerce a value that may be a str (legacy TEXT) or already a dict/list (JSONB)."""
    if val is None:
        return default
    if isinstance(val, (dict, list)):
        return val
    try:
        return json.loads(val)
    except (json.JSONDecodeError, TypeError):
        return default
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
- `news_articles`: scored articles (id, title, url, source, body, article_hash)
- `news_impact_vectors`: per-article impact vector (article_id, impact_json, top_dimensions)
- `news_article_tickers`: ticker mentions per article (article_id, ticker, source)
- `company_vectors`: company dimension embeddings (ticker, vector_date, dimensions_json)

## News Impact Workflow
The news scorer (Ollama LLM) maps each article into an 8-cluster impact vector, then
dot-products it against company dimension vectors to produce tailwind/headwind scores.

### Typical usage:
1. **Keep vectors fresh** (daily/weekly): `run_build_company_vectors(tickers=[...])` or by exchange
2. **Ingest FMP news** (daily): `run_fmp_news_scoring(limit=30)` — runs in background
3. **Score a specific article**: `score_news_url(url)` or `score_news_text(text)`
4. **Query for a watchlist**: `get_ticker_news_impact_summary(tickers=[...])`
5. **Browse recent articles**: `get_recent_news_impact(ticker="NVDA")`

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
| Score article from URL | `score_news_url(url)` |
| Score article from text | `score_news_text(text, tickers=[...])` |
| Batch score FMP news (background) | `run_fmp_news_scoring(limit=30)` |
| Build/refresh company vectors (background) | `run_build_company_vectors(tickers=[...])` |
| Recent news for a ticker | `get_recent_news_impact(ticker="AAPL")` |
| News summary for watchlist | `get_ticker_news_impact_summary(tickers=[...])` |
""",
)

_SCAN_SOURCE_BY_SCRIPT: dict[str, str] = {
    "scripts/run_screener.py": "run_screener",
    "ibd_screener.py": "ibd_screener",
    "news_impact/score_news_cli.py": "news_score",
    "news_impact/build_vectors_cli.py": "news_build_vectors",
}


def _scan_source_for_script(rel_script: str) -> str:
    key = Path(rel_script).as_posix()
    return _SCAN_SOURCE_BY_SCRIPT.get(key, key)


def _get_client():
    return get_supabase_client()


def _tbl(client, table: str):
    return client.schema(get_schema()).table(table)


def _resolve_passed_dataset(client, run_id: int) -> tuple[str, Optional[str]]:
    """Return (dataset_name, passed_flag_field) for a run."""
    res = _tbl(client, "user_scan_rows").select("dataset").eq("run_id", run_id).execute()
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
        _tbl(client, "user_scan_jobs")
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
        _tbl(client, "user_scan_jobs")
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
        _tbl(client, "user_scan_runs")
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
            "has_market_json": r.get("market_json") is not None,
            "has_result_json": r.get("result_json") is not None,
        })
    return json.dumps(rows, default=str)


@mcp.tool()
def get_run_detail(run_id: int) -> str:
    """Return one scan_runs row including market_json and result_json."""
    client = _get_client()
    res = (
        _tbl(client, "user_scan_runs")
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

    q = _tbl(client, "user_scan_rows").select("run_id,scan_date,dataset,symbol,row_data", count="exact").eq("run_id", run_id)
    if dataset:
        q = q.eq("dataset", dataset)
    if symbol:
        q = q.eq("symbol", symbol.upper())

    res = q.order("symbol").range(offset, offset + limit - 1).execute()

    out = []
    for rec in (res.data or []):
        rec["row_data"] = _as_json(rec.get("row_data"))
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

    src_res = _tbl(client, "user_scan_runs").select("source,scan_date,result_json").eq("id", run_id).single().execute()
    if not src_res.data:
        return json.dumps({"error": "run_id not found", "run_id": run_id})

    source = src_res.data["source"]
    scan_date = src_res.data["scan_date"]
    result_json = src_res.data.get("result_json")

    # Fast path: run_screener stores top-level counts in result_json
    if source == "run_screener" and result_json:
        try:
            result = _as_json(result_json) or {}
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
        _tbl(client, "user_scan_rows")
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
        rd = _as_json(rec.get("row_data")) or {}

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
        _tbl(client, "user_scan_rows")
        .select("symbol,row_data")
        .eq("run_id", run_id)
        .eq("dataset", dataset)
        .order("symbol")
        .limit(limit)
        .execute()
    )

    out = []
    for row in (res.data or []):
        rd = _as_json(row.get("row_data")) or {}
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
        _tbl(client, "user_scan_rows")
        .select("symbol,row_data")
        .eq("run_id", run_id)
        .eq("dataset", dataset)
        .order("symbol")
        .execute()
    )

    out = []
    for row in (res.data or []):
        rd = _as_json(row.get("row_data")) or {}
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
        _tbl(client, "user_scan_jobs")
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
        run_res = _tbl(client, "user_scan_runs").select("id").order("id", desc=True).limit(1).execute()
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
        row = _tbl(client, "user_scan_runs").select("id").order("id", desc=True).limit(1).execute()
        if not row.data:
            return json.dumps({"error": "no scan runs found"})
        resolved_run_id = int(row.data[0]["id"])
    else:
        resolved_run_id = int(run_id)

    sym_res = (
        _tbl(client, "user_scan_rows")
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
    ibd_file: str = str(_REPO_ROOT / "input" / "IBD Data Tables.xlsx"),
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


# ── News impact tools ─────────────────────────────────────────────────────────

def _run_news_async(coro):
    """Run an async news_impact coroutine from a sync MCP tool."""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


@mcp.tool()
def score_news_url(url: str, tickers: Optional[list[str]] = None) -> str:
    """
    Fetch a news article from a URL, score it through the impact framework,
    and optionally rank given tickers as tailwinds or headwinds.

    The article is persisted to the DB (deduped by hash). Subsequent calls
    with the same URL content return the cached result instantly.

    Returns: article_id, impact vector top signals, and per-ticker scores.
    """
    from news_impact.impact_scorer import score_article, aggregate_heads, top_dimensions, extract_tickers
    from news_impact.company_scorer import score_companies
    from news_impact.company_vector import build_vectors
    from news_impact.news_ingester import ingest_article
    import asyncio

    async def _run():
        import httpx, re
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
            r = await client.get(url, headers={"User-Agent": "Mozilla/5.0 news-impact-bot/1.0"})
            r.raise_for_status()
        content_type = r.headers.get("content-type", "")
        if "html" in content_type:
            paragraphs = re.findall(r"<p[^>]*>(.*?)</p>", r.text, re.IGNORECASE | re.DOTALL)
            tag_re = re.compile(r"<[^>]+>")
            space_re = re.compile(r"\s{2,}")
            body = space_re.sub(" ", tag_re.sub(" ", " ".join(paragraphs) if paragraphs else r.text)).strip()
        else:
            body = r.text

        heads, extracted = await asyncio.gather(score_article(body), extract_tickers(body))
        impact = aggregate_heads(heads)
        article_id, impact = await ingest_article(
            body=body,
            url=url,
            article_stream="manual_url",
        )

        all_tickers = list(dict.fromkeys((tickers or []) + extracted))
        company_scores = []
        if all_tickers and impact:
            vecs = await build_vectors(all_tickers, use_cache=True)
            if vecs:
                company_scores = score_companies(impact, vecs, top_n=10)

        return {
            "article_id": article_id,
            "url": url,
            "top_signals": top_dimensions(impact, n=8),
            "companies_mentioned": extracted,
            "tailwinds": [{"ticker": s.ticker, "score": round(s.score, 3)} for s in company_scores if s.score > 0],
            "headwinds": [{"ticker": s.ticker, "score": round(s.score, 3)} for s in reversed(company_scores) if s.score < 0],
        }

    try:
        return json.dumps(_run_news_async(_run()), default=str)
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


@mcp.tool()
def score_news_text(
    text: str,
    tickers: Optional[list[str]] = None,
    title: Optional[str] = None,
) -> str:
    """
    Score a news article from raw text through the impact framework.
    Optionally supply --tickers to rank specific companies as tailwinds/headwinds.
    Persists the result to DB.

    Returns: article_id, top impact signals, and per-ticker scores.
    """
    from news_impact.impact_scorer import score_article, aggregate_heads, top_dimensions, extract_tickers
    from news_impact.company_scorer import score_companies
    from news_impact.company_vector import build_vectors
    from news_impact.news_ingester import ingest_article
    import asyncio

    async def _run():
        heads, extracted = await asyncio.gather(score_article(text), extract_tickers(text))
        impact = aggregate_heads(heads)
        article_id, impact = await ingest_article(
            body=text,
            title=title,
            article_stream="manual_text",
        )

        all_tickers = list(dict.fromkeys((tickers or []) + extracted))
        company_scores = []
        if all_tickers and impact:
            vecs = await build_vectors(all_tickers, use_cache=True)
            if vecs:
                company_scores = score_companies(impact, vecs, top_n=10)

        return {
            "article_id": article_id,
            "top_signals": top_dimensions(impact, n=8),
            "companies_mentioned": extracted,
            "tailwinds": [{"ticker": s.ticker, "score": round(s.score, 3)} for s in company_scores if s.score > 0],
            "headwinds": [{"ticker": s.ticker, "score": round(s.score, 3)} for s in reversed(company_scores) if s.score < 0],
        }

    try:
        return json.dumps(_run_news_async(_run()), default=str)
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


@mcp.tool()
def run_fmp_news_scoring(
    tickers: Optional[list[str]] = None,
    limit: int = 20,
    page: int = 0,
    feed: str = "stock",
) -> str:
    """
    Fetch news from FMP stable APIs and score each article in the background.
    feed: "stock" (stock-latest or news/stock with tickers), "general" (general-latest),
    or "both" (parallel fetch, URL-deduped).
    Returns immediately with a job_id. Poll get_scan_job(job_id) for status.
    """
    f = (feed or "stock").strip().lower()
    if f not in ("stock", "general", "both"):
        return json.dumps({"ok": False, "error": "feed must be stock, general, or both"})
    args = [
        "--fmp-news",
        "--fmp-news-feed",
        f,
        "--limit",
        str(int(limit)),
        "--page",
        str(int(page)),
    ]
    if tickers:
        args += ["--tickers"] + [t.upper() for t in tickers]
    return json.dumps(_start_repo_script("news_impact/score_news_cli.py", args), default=str)


@mcp.tool()
def run_build_company_vectors(
    tickers: Optional[list[str]] = None,
    exchange: Optional[list[str]] = None,
    from_db: bool = False,
    min_mktcap: Optional[float] = None,
    min_price: Optional[float] = None,
) -> str:
    """
    Build or refresh company embedding vectors (stored in Supabase + local cache).
    - tickers: specific symbols to build/refresh
    - from_db: refresh every ticker already stored in Supabase (daily update pattern)
    - exchange: bulk rebuild from a full exchange (e.g. ["NASDAQ","NYSE"])
    Returns immediately with a job_id. Poll get_scan_job(job_id) for status.
    """
    if tickers:
        args = ["--tickers"] + [t.upper() for t in tickers]
    elif from_db:
        args = ["--from-db"]
    elif exchange:
        args = ["--exchange"] + [e.upper() for e in exchange]
        if min_mktcap is not None:
            args += ["--min-mktcap", str(min_mktcap)]
        if min_price is not None:
            args += ["--min-price", str(min_price)]
    else:
        return json.dumps({"ok": False, "error": "supply tickers, from_db=True, or exchange"})
    return json.dumps(_start_repo_script("news_impact/build_vectors_cli.py", args), default=str)


@mcp.tool()
def get_recent_news_impact(ticker: Optional[str] = None, limit: int = 10) -> str:
    """
    Query recent scored news articles from the DB.
    If ticker is supplied, returns only articles that mention that ticker.
    Each result includes the article title, URL, top impact signals, and article_id.
    """
    client = _get_client()
    schema = get_schema()

    if ticker:
        ticker_upper = ticker.upper()
        # join through news_article_tickers
        at_res = (
            client.schema(schema).table("news_article_tickers")
            .select("article_id")
            .eq("ticker", ticker_upper)
            .order("article_id", desc=True)
            .limit(int(limit))
            .execute()
        )
        article_ids = [r["article_id"] for r in (at_res.data or [])]
        if not article_ids:
            return json.dumps({"ticker": ticker_upper, "articles": []})
        art_res = (
            client.schema(schema).table("news_trends_article_base_v")
            .select("article_id,title,url,source,published_at,article_created_at")
            .in_("article_id", article_ids)
            .execute()
        )
    else:
        art_res = (
            client.schema(schema).table("news_trends_article_base_v")
            .select("article_id,title,url,source,published_at,article_created_at")
            .order("published_at", desc=True)
            .limit(int(limit))
            .execute()
        )

    articles = art_res.data or []
    if not articles:
        return json.dumps({"articles": []})

    ids = [a["article_id"] for a in articles]
    vec_res = (
        client.schema(schema).table("news_impact_vectors")
        .select("article_id,top_dimensions")
        .in_("article_id", ids)
        .execute()
    )
    top_dims_by_id = {r["article_id"]: r["top_dimensions"] for r in (vec_res.data or [])}

    results = []
    for a in articles:
        results.append({
            "article_id": a["article_id"],
            "title": a.get("title"),
            "url": a.get("url"),
            "source": a.get("source"),
            "published_at": a.get("published_at"),
            "created_at": a.get("article_created_at"),
            "top_signals": top_dims_by_id.get(a["article_id"]),
        })

    return json.dumps({"articles": results}, default=str)


@mcp.tool()
def get_ticker_news_impact_summary(tickers: list[str], limit_per_ticker: int = 5) -> str:
    """
    For each ticker, return recent news articles that mention it along with their
    top impact signals. Useful for quickly assessing news sentiment for a watchlist.
    """
    client = _get_client()
    schema = get_schema()
    tickers_upper = [t.upper() for t in tickers]

    at_res = (
        client.schema(schema).table("news_article_tickers")
        .select("article_id,ticker")
        .in_("ticker", tickers_upper)
        .execute()
    )
    by_ticker: dict[str, list[int]] = {}
    for row in (at_res.data or []):
        by_ticker.setdefault(row["ticker"], []).append(row["article_id"])

    all_ids = list({aid for ids in by_ticker.values() for aid in ids})
    if not all_ids:
        return json.dumps({t: [] for t in tickers_upper})

    art_res = (
        client.schema(schema).table("news_trends_article_base_v")
        .select("article_id,title,url,published_at,article_created_at")
        .in_("article_id", all_ids)
        .execute()
    )
    art_by_id = {a["article_id"]: a for a in (art_res.data or [])}

    vec_res = (
        client.schema(schema).table("news_impact_vectors")
        .select("article_id,top_dimensions")
        .in_("article_id", all_ids)
        .execute()
    )
    top_dims_by_id = {r["article_id"]: r["top_dimensions"] for r in (vec_res.data or [])}

    out: dict[str, list] = {}
    for ticker in tickers_upper:
        ids = sorted(by_ticker.get(ticker, []), reverse=True)[:limit_per_ticker]
        out[ticker] = [
            {
                "article_id": aid,
                "title": art_by_id[aid]["title"] if aid in art_by_id else None,
                "url": art_by_id[aid].get("url") if aid in art_by_id else None,
                "published_at": art_by_id[aid].get("published_at") if aid in art_by_id else None,
                "created_at": art_by_id[aid].get("article_created_at") if aid in art_by_id else None,
                "top_signals": top_dims_by_id.get(aid),
            }
            for aid in ids
            if aid in art_by_id
        ]
    return json.dumps(out, default=str)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
