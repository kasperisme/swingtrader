"""
SwingTrader MCP server — DuckDB (scan_runs, scan_rows, scan_jobs) + background screeners.

Run from repo root:
  python -m swingtrader_mcp.server

Cursor / Claude Desktop (example):
  "command": "python",
  "args": ["-m", "swingtrader_mcp.server"],
  "cwd": "/absolute/path/to/swingtrader"

Requires: pip install mcp (see requirements.txt)
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
connect: Callable = _db.connect
default_db_path: Callable[[], str] = _db.default_db_path
ensure_schema: Callable = _db.ensure_schema
create_scan_job: Callable = _db.create_scan_job
update_scan_job_pid: Callable = _db.update_scan_job_pid
update_scan_job_progress: Callable = _db.update_scan_job_progress
finish_scan_job: Callable = _db.finish_scan_job

mcp = FastMCP("swingtrader")

# Must match scan_runs.source written by each script (persist_* calls).
_SCAN_SOURCE_BY_SCRIPT: dict[str, str] = {
    "scripts/run_screener.py": "run_screener",
    "ibd_screener.py": "ibd_screener",
}


def _scan_source_for_script(rel_script: str) -> str:
    key = Path(rel_script).as_posix()
    return _SCAN_SOURCE_BY_SCRIPT.get(key, key)


def _db_connect():
    conn = connect()
    ensure_schema(conn)
    return conn


def _rows_to_dicts(rows: list[tuple], columns: list[str]) -> list[dict[str, Any]]:
    return [dict(zip(columns, row)) for row in rows]


@mcp.tool()
def swingtrader_db_path() -> str:
    """Return the resolved DuckDB file path (HANS_DUCKDB_PATH or default under data/)."""
    return default_db_path()


@mcp.tool()
def get_scan_jobs(limit: int = 25) -> str:
    """
    Screening process state from DuckDB (scan_jobs): running / completed / failed, PID, logs,
    linked scan_run_id when finished. Use this to answer whether a screen is still running or what happened last.
    """
    limit = max(1, min(int(limit), 200))
    conn = _db_connect()
    try:
        cur = conn.execute(
            f"""
            SELECT id, created_at, started_at, finished_at, status, scan_source, script_rel,
                   args_json, pid, exit_code, scan_run_id, stdout_log, stderr_log, error_message,
                   progress_message
            FROM scan_jobs
            ORDER BY CASE WHEN status = 'running' THEN 0 ELSE 1 END,
                     COALESCE(finished_at, started_at) DESC,
                     id DESC
            LIMIT {limit}
            """
        )
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        return json.dumps(_rows_to_dicts(rows, cols), default=str)
    finally:
        conn.close()


@mcp.tool()
def get_scan_job(job_id: int) -> str:
    """Single scan_jobs row by id (state of one screening process)."""
    conn = _db_connect()
    try:
        cur = conn.execute(
            """
            SELECT id, created_at, started_at, finished_at, status, scan_source, script_rel,
                   args_json, pid, exit_code, scan_run_id, stdout_log, stderr_log, error_message,
                   progress_message
            FROM scan_jobs WHERE id = ?
            """,
            [job_id],
        )
        cols = [d[0] for d in cur.description]
        row = cur.fetchone()
        if not row:
            return json.dumps({"error": "job_id not found", "job_id": job_id})
        return json.dumps(dict(zip(cols, row)), default=str)
    finally:
        conn.close()


@mcp.tool()
def list_scan_runs(limit: int = 20) -> str:
    """List recent screening runs (id, scan_date, source, created_at). JSON array."""
    limit = max(1, min(int(limit), 200))
    conn = _db_connect()
    try:
        cur = conn.execute(
            f"""
            SELECT id, created_at, scan_date, source,
                   LENGTH(COALESCE(market_json, '')) AS market_json_len,
                   LENGTH(COALESCE(result_json, '')) AS result_json_len
            FROM scan_runs
            ORDER BY id DESC
            LIMIT {limit}
            """
        )
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        return json.dumps(_rows_to_dicts(rows, cols), default=str)
    finally:
        conn.close()


@mcp.tool()
def get_run_detail(run_id: int) -> str:
    """Return one scan_runs row; result_json and market_json are included as strings (may be large)."""
    conn = _db_connect()
    try:
        cur = conn.execute(
            """
            SELECT id, created_at, scan_date, source, market_json, result_json
            FROM scan_runs WHERE id = ?
            """,
            [run_id],
        )
        cols = [d[0] for d in cur.description]
        row = cur.fetchone()
        if not row:
            return json.dumps({"error": "run_id not found", "run_id": run_id})
        return json.dumps(dict(zip(cols, row)), default=str)
    finally:
        conn.close()


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
    Use offset for pagination (e.g. offset=500 to get rows 500-999). row_data is parsed JSON per row.
    """
    limit = max(1, min(int(limit), 5000))
    offset = max(0, int(offset))
    conn = _db_connect()
    try:
        where = ["run_id = ?"]
        params: list[Any] = [run_id]
        if dataset:
            where.append("dataset = ?")
            params.append(dataset)
        if symbol:
            where.append("symbol = ?")
            params.append(symbol.upper())
        sql = f"""
            SELECT run_id, scan_date, dataset, symbol, row_data
            FROM scan_rows
            WHERE {' AND '.join(where)}
            ORDER BY symbol
            LIMIT {limit} OFFSET {offset}
        """
        cur = conn.execute(sql, params)
        cols = [d[0] for d in cur.description]
        out = []
        for row in cur.fetchall():
            rec = dict(zip(cols, row))
            raw = rec.get("row_data")
            if isinstance(raw, str):
                try:
                    rec["row_data_parsed"] = json.loads(raw)
                except json.JSONDecodeError:
                    rec["row_data_parsed"] = None
            out.append(rec)
        total = conn.execute(
            f"SELECT COUNT(*) FROM scan_rows WHERE {' AND '.join(where)}",
            params,
        ).fetchone()[0]
        return json.dumps({"total": total, "offset": offset, "limit": limit, "rows": out}, default=str)
    finally:
        conn.close()


def _resolve_passed_dataset(conn: Any, run_id: int) -> tuple[str, Optional[str]]:
    """
    Return (dataset_name, passed_flag_field) for a run.
    passed_flag_field is None when every row in the dataset is a passing stock.
    """
    datasets = {
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT dataset FROM scan_rows WHERE run_id = ?", [run_id]
        ).fetchall()
    }
    if "passed_stocks" in datasets:
        return "passed_stocks", None
    if "trend_template" in datasets:
        return "trend_template", "Passed"
    return "", None


def _extract_stock_fields(row_data: dict[str, Any]) -> dict[str, Any]:
    """Pull the minimal actionable fields from a parsed row_data dict."""
    symbol = (
        row_data.get("symbol")
        or row_data.get("ticker")
        or row_data.get("Symbol")
    )
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
    }


@mcp.tool()
def get_screener_summary(run_id: int) -> str:
    """
    Aggregate stats for a run: total scanned, passed trend template, within buy range,
    near-pivot count, and sector breakdown. Avoids downloading the full dataset.
    Works for both run_screener and ibd_screener runs.
    """
    conn = _db_connect()
    try:
        src_row = conn.execute(
            "SELECT source, scan_date, result_json FROM scan_runs WHERE id = ?", [run_id]
        ).fetchone()
        if not src_row:
            return json.dumps({"error": "run_id not found", "run_id": run_id})
        source, scan_date, result_json = src_row

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
                pass  # fall through to scan_rows path

        # Generic path: derive stats from scan_rows via DuckDB JSON extraction
        dataset, passed_field = _resolve_passed_dataset(conn, run_id)
        if not dataset:
            return json.dumps({"error": "no usable dataset in scan_rows", "run_id": run_id})

        total_rows = conn.execute(
            "SELECT COUNT(*) FROM scan_rows WHERE run_id = ? AND dataset = ?",
            [run_id, dataset],
        ).fetchone()[0]

        if passed_field:
            passed_count = conn.execute(
                f"""
                SELECT COUNT(*) FROM scan_rows
                WHERE run_id = ? AND dataset = ?
                  AND json_extract_string(row_data, '$.{passed_field}') IN ('true', 'True', '1')
                """,
                [run_id, dataset],
            ).fetchone()[0]
        else:
            passed_count = total_rows

        within_buy = conn.execute(
            """
            SELECT COUNT(*) FROM scan_rows
            WHERE run_id = ? AND dataset = ?
              AND json_extract_string(row_data, '$.within_buy_range') IN ('true', 'True', '1')
            """,
            [run_id, dataset],
        ).fetchone()[0]

        near_pivot = conn.execute(
            """
            SELECT COUNT(*) FROM scan_rows
            WHERE run_id = ? AND dataset = ?
              AND TRY_CAST(json_extract_string(row_data, '$.extension_pct') AS DOUBLE) <= 5
              AND TRY_CAST(json_extract_string(row_data, '$.extension_pct') AS DOUBLE) IS NOT NULL
              AND COALESCE(json_extract_string(row_data, '$.extended'), 'false')
                  NOT IN ('true', 'True', '1')
            """,
            [run_id, dataset],
        ).fetchone()[0]

        sector_rows = conn.execute(
            """
            SELECT COALESCE(json_extract_string(row_data, '$.sector'), 'Unknown') AS sector,
                   COUNT(*) AS cnt
            FROM scan_rows
            WHERE run_id = ? AND dataset = ?
            GROUP BY sector ORDER BY cnt DESC
            """,
            [run_id, dataset],
        ).fetchall()

        return json.dumps({
            "run_id": run_id,
            "source": source,
            "scan_date": str(scan_date),
            "dataset": dataset,
            "total_scanned": total_rows,
            "passed_trend_template": passed_count,
            "within_buy_range": within_buy,
            "near_pivot_count": near_pivot,
            "sector_breakdown": {r[0]: r[1] for r in sector_rows},
        }, default=str)
    finally:
        conn.close()


@mcp.tool()
def get_passed_stocks(
    run_id: int,
    sector: Optional[str] = None,
    limit: int = 200,
) -> str:
    """
    Stocks that passed the full screen for a run, with a minimal field set:
    symbol, sector, industry, price, pivot, extension_pct, within_buy_range,
    extended, accumulation, rs_line_new_high, adr_pct, vol_ratio_today,
    up_down_vol_ratio, eps_growth_yoy, rev_growth_yoy.
    Optionally filter by sector (case-insensitive substring match).
    Much lighter than get_scan_rows — use this instead of downloading all 40 fields.
    """
    limit = max(1, min(int(limit), 2000))
    conn = _db_connect()
    try:
        dataset, passed_field = _resolve_passed_dataset(conn, run_id)
        if not dataset:
            return json.dumps({"error": "no usable dataset in scan_rows", "run_id": run_id})

        where = ["run_id = ?", "dataset = ?"]
        params: list[Any] = [run_id, dataset]
        if passed_field:
            where.append(
                f"json_extract_string(row_data, '$.{passed_field}') IN ('true', 'True', '1')"
            )

        sql = f"""
            SELECT symbol, row_data FROM scan_rows
            WHERE {' AND '.join(where)}
            ORDER BY symbol
            LIMIT {limit}
        """
        rows = conn.execute(sql, params).fetchall()

        out = []
        for sym, raw in rows:
            try:
                rd = json.loads(raw) if isinstance(raw, str) else {}
            except (json.JSONDecodeError, TypeError):
                rd = {}
            rec = _extract_stock_fields(rd)
            if sector and not (
                sector.lower() in (rec.get("sector") or "").lower()
                or sector.lower() in (rec.get("industry") or "").lower()
            ):
                continue
            out.append(rec)

        return json.dumps({"run_id": run_id, "count": len(out), "stocks": out}, default=str)
    finally:
        conn.close()


@mcp.tool()
def get_near_pivot_stocks(
    run_id: int,
    min_ext_pct: float = -5.0,
    max_ext_pct: float = 5.0,
    require_accumulation: bool = False,
) -> str:
    """
    Passed stocks within a buy range defined by extension_pct bounds (default -5% to +5%).
    Set require_accumulation=True to further filter to only accumulating names.
    Sorted by extension_pct ascending (closest-to-pivot first).
    Returns the same minimal field set as get_passed_stocks.
    """
    conn = _db_connect()
    try:
        dataset, passed_field = _resolve_passed_dataset(conn, run_id)
        if not dataset:
            return json.dumps({"error": "no usable dataset in scan_rows", "run_id": run_id})

        where = ["run_id = ?", "dataset = ?"]
        params: list[Any] = [run_id, dataset]
        if passed_field:
            where.append(
                f"json_extract_string(row_data, '$.{passed_field}') IN ('true', 'True', '1')"
            )

        sql = f"SELECT symbol, row_data FROM scan_rows WHERE {' AND '.join(where)} ORDER BY symbol"
        rows = conn.execute(sql, params).fetchall()

        out = []
        for sym, raw in rows:
            try:
                rd = json.loads(raw) if isinstance(raw, str) else {}
            except (json.JSONDecodeError, TypeError):
                rd = {}
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
    finally:
        conn.close()


@mcp.tool()
def get_latest_screener_result() -> str:
    """
    Actionable output of the most recent completed screening run.
    Returns summary stats + passed stocks (minimal fields). Works for both
    run_screener and ibd_screener. Shortcut for the get_scan_job → get_run_detail
    → get_scan_rows chain.
    """
    conn = _db_connect()
    try:
        # Find the most recent completed job that has a linked scan_run_id
        job_row = conn.execute(
            """
            SELECT scan_run_id, scan_source, finished_at FROM scan_jobs
            WHERE status = 'completed' AND scan_run_id IS NOT NULL
            ORDER BY finished_at DESC LIMIT 1
            """
        ).fetchone()
        if not job_row:
            # Fall back to most recent scan_run regardless of job linkage
            run_row = conn.execute(
                "SELECT id FROM scan_runs ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if not run_row:
                return json.dumps({"error": "no completed screening runs found"})
            run_id = int(run_row[0])
        else:
            run_id = int(job_row[0])

        conn.close()

        # Re-use existing tools for consistency
        summary = json.loads(get_screener_summary(run_id))
        passed = json.loads(get_passed_stocks(run_id))
        return json.dumps({
            "run_id": run_id,
            "summary": summary,
            "passed_stocks": passed.get("stocks", []),
        }, default=str)
    except Exception:
        # conn may already be closed
        try:
            conn.close()
        except Exception:
            pass
        raise


def _start_repo_script(rel_script: str, args: list[str]) -> dict[str, Any]:
    """
    Launch job_runner → screening script in the background; record state in DuckDB (scan_jobs).
    Does not block MCP stdio. Stdout/stderr go to output/mcp_screener_logs/.
    """
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
    job_id = create_scan_job(
        scan_source,
        rel_script,
        args,
        out_log_rel,
        err_log_rel,
    )

    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")

    fo = open(out_log, "w", encoding="utf-8")
    fe = open(err_log, "w", encoding="utf-8")
    try:
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "swingtrader_mcp.job_runner",
                str(job_id),
                rel_script,
            ]
            + args,
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
def run_json_screener(
    ibd_file: str = "./input/IBD Data Tables.xlsx",
    lookback_days: int = 365,
) -> str:
    """
    Start scripts/run_screener.py (IBD + Minervini pipeline) in the background — returns immediately.
    Job state is in DuckDB (get_scan_jobs). Does not block the MCP. Logs under output/mcp_screener_logs/.
    """
    args = ["--ibd-file", ibd_file, "--lookback-days", str(int(lookback_days))]
    return json.dumps(_start_repo_script("scripts/run_screener.py", args), default=str)


@mcp.tool()
def run_ibd_market_screener() -> str:
    """
    Start ibd_screener.py (NYSE/NASDAQ market-wide Minervini screen) in the background — returns immediately.
    Job state is in DuckDB (get_scan_jobs). Does not block the MCP. Logs under output/mcp_screener_logs/.
    """
    return json.dumps(_start_repo_script("ibd_screener.py", []), default=str)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
