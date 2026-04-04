"""
DuckDB persistence for screening runs — queryable by local agents (e.g. Hans).

Set HANS_DUCKDB_PATH to override the default file location (default: <repo>/data/swingtrader.duckdb).

Tables:
  scan_runs — one row per run (source, scan_date, market_json, full result_json for run_screener).
  scan_rows — normalized rows per dataset (trend_template, rs_rating, quote, passed_stocks);
              row_data is JSON text for flexible evolving columns.
  scan_jobs — screening process state (MCP / background): running → completed/failed, links to scan_run_id when done.

Example (DuckDB CLI or Python):
  SELECT id, scan_date, source FROM scan_runs ORDER BY id DESC LIMIT 5;
  SELECT id, status, scan_source, pid, scan_run_id FROM scan_jobs ORDER BY id DESC LIMIT 10;
  SELECT symbol, json_extract_string(row_data, '$.Passed') AS passed
  FROM scan_rows WHERE dataset = 'trend_template' AND run_id = (SELECT MAX(id) FROM scan_runs);
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import time

import duckdb
import numpy as np
import pandas as pd
from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=_REPO_ROOT / ".env")


def default_db_path() -> str:
    return os.environ.get(
        "HANS_DUCKDB_PATH",
        str(_REPO_ROOT / "data" / "swingtrader.duckdb"),
    )


def connect(path: Optional[str] = None, retries: int = 8, retry_delay: float = 1.5) -> duckdb.DuckDBPyConnection:
    p = path or default_db_path()
    parent = Path(p).parent
    if parent != Path("."):
        parent.mkdir(parents=True, exist_ok=True)
    last_err: Exception = RuntimeError("unreachable")
    for attempt in range(retries):
        try:
            return duckdb.connect(p)
        except duckdb.IOException as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(retry_delay)
    raise last_err


def ensure_schema(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS scan_runs (
            id BIGINT PRIMARY KEY,
            created_at TIMESTAMP NOT NULL,
            scan_date DATE NOT NULL,
            source VARCHAR NOT NULL,
            market_json VARCHAR,
            result_json VARCHAR
        );
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS scan_rows (
            run_id BIGINT NOT NULL,
            scan_date DATE NOT NULL,
            dataset VARCHAR NOT NULL,
            symbol VARCHAR,
            row_data VARCHAR NOT NULL
        );
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_scan_rows_run ON scan_rows(run_id);"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_scan_rows_symbol ON scan_rows(symbol);"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_scan_rows_dataset ON scan_rows(dataset);"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS scan_jobs (
            id BIGINT PRIMARY KEY,
            created_at TIMESTAMP NOT NULL,
            started_at TIMESTAMP NOT NULL,
            finished_at TIMESTAMP,
            status VARCHAR NOT NULL,
            scan_source VARCHAR NOT NULL,
            script_rel VARCHAR NOT NULL,
            args_json VARCHAR,
            pid INTEGER,
            exit_code INTEGER,
            scan_run_id BIGINT,
            stdout_log VARCHAR,
            stderr_log VARCHAR,
            error_message VARCHAR
        );
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_scan_jobs_status ON scan_jobs(status);"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_scan_jobs_started ON scan_jobs(started_at);"
    )
    conn.execute(
        "ALTER TABLE scan_jobs ADD COLUMN IF NOT EXISTS progress_message VARCHAR;"
    )


def _next_job_id(conn: duckdb.DuckDBPyConnection) -> int:
    row = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM scan_jobs").fetchone()
    return int(row[0])


def _next_run_id(conn: duckdb.DuckDBPyConnection) -> int:
    row = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM scan_runs").fetchone()
    return int(row[0])


def _symbol_from_row(rec: dict[str, Any]) -> Optional[str]:
    for k in ("symbol", "ticker", "Symbol"):
        if k in rec and rec[k] is not None and str(rec[k]).strip():
            return str(rec[k]).strip()
    return None


def _json_row(rec: dict[str, Any]) -> str:
    def default(o: Any) -> Any:
        if isinstance(o, (datetime, date, pd.Timestamp)):
            return o.isoformat()
        if isinstance(o, (np.bool_, np.integer, np.floating)):
            if isinstance(o, np.bool_):
                return bool(o)
            if isinstance(o, np.integer):
                return int(o)
            x = float(o)
            if np.isnan(x) or np.isinf(x):
                return None
            return x
        if isinstance(o, float) and (np.isnan(o) or np.isinf(o)):
            return None
        return str(o)

    return json.dumps(rec, default=default, allow_nan=False)


def _dataframe_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    clean = df.replace({np.nan: None})
    return clean.to_dict(orient="records")


def append_scan_rows(
    conn: duckdb.DuckDBPyConnection,
    run_id: int,
    scan_date: date,
    dataset: str,
    df: pd.DataFrame,
) -> int:
    """Insert each row of df as JSON in scan_rows. Returns number of rows inserted."""
    if df is None or df.empty:
        return 0
    n = 0
    for rec in _dataframe_records(df):
        sym = _symbol_from_row(rec)
        conn.execute(
            """
            INSERT INTO scan_rows (run_id, scan_date, dataset, symbol, row_data)
            VALUES (?, ?, ?, ?, ?);
            """,
            [run_id, scan_date, dataset, sym, _json_row(rec)],
        )
        n += 1
    return n


def insert_scan_run(
    conn: duckdb.DuckDBPyConnection,
    scan_date: date,
    source: str,
    market_json: Optional[str] = None,
    result_json: Optional[str] = None,
) -> int:
    run_id = _next_run_id(conn)
    conn.execute(
        """
        INSERT INTO scan_runs (id, created_at, scan_date, source, market_json, result_json)
        VALUES (?, ?, ?, ?, ?, ?);
        """,
        [
            run_id,
            datetime.now(),
            scan_date,
            source,
            market_json,
            result_json,
        ],
    )
    return run_id


def create_scan_job(
    scan_source: str,
    script_rel: str,
    args: list[str],
    stdout_log: str,
    stderr_log: str,
    path: Optional[str] = None,
) -> int:
    """
    Insert a row with status='running' (used when MCP starts a background screener).
    Returns job id. Call finish_scan_job when the process exits.
    """
    conn = connect(path)
    try:
        ensure_schema(conn)
        jid = _next_job_id(conn)
        now = datetime.now()
        conn.execute(
            """
            INSERT INTO scan_jobs (
                id, created_at, started_at, finished_at, status,
                scan_source, script_rel, args_json, pid, exit_code, scan_run_id,
                stdout_log, stderr_log, error_message
            )
            VALUES (?, ?, ?, NULL, 'running', ?, ?, ?, NULL, NULL, NULL, ?, ?, NULL);
            """,
            [
                jid,
                now,
                now,
                scan_source,
                script_rel,
                json.dumps(args),
                stdout_log,
                stderr_log,
            ],
        )
        return jid
    finally:
        conn.close()


def update_scan_job_pid(job_id: int, pid: int, path: Optional[str] = None) -> None:
    conn = connect(path)
    try:
        ensure_schema(conn)
        conn.execute("UPDATE scan_jobs SET pid = ? WHERE id = ?", [pid, job_id])
    finally:
        conn.close()


def update_scan_job_progress(job_id: int, message: str, path: Optional[str] = None) -> None:
    conn = connect(path)
    try:
        ensure_schema(conn)
        conn.execute(
            "UPDATE scan_jobs SET progress_message = ? WHERE id = ?",
            [message, job_id],
        )
    finally:
        conn.close()


def finish_scan_job(
    job_id: int,
    exit_code: int,
    path: Optional[str] = None,
    error_message: Optional[str] = None,
) -> None:
    """
    Mark job completed (exit_code==0) or failed. Tries to attach scan_run_id from the
    latest scan_runs row matching this job's scan_source.
    """
    conn = connect(path)
    try:
        ensure_schema(conn)
        row = conn.execute(
            "SELECT scan_source, started_at FROM scan_jobs WHERE id = ?", [job_id]
        ).fetchone()
        if not row:
            return
        scan_source, started_at = row[0], row[1]
        status = "completed" if exit_code == 0 else "failed"
        scan_run_id = None
        if status == "completed":
            r2 = conn.execute(
                """
                SELECT id FROM scan_runs
                WHERE source = ? AND created_at >= ?
                ORDER BY id DESC
                LIMIT 1
                """,
                [scan_source, started_at],
            ).fetchone()
            if r2:
                scan_run_id = int(r2[0])
        conn.execute(
            """
            UPDATE scan_jobs
            SET finished_at = ?, status = ?, exit_code = ?, scan_run_id = ?, error_message = ?
            WHERE id = ?
            """,
            [
                datetime.now(),
                status,
                exit_code,
                scan_run_id,
                error_message,
                job_id,
            ],
        )
    finally:
        conn.close()


def persist_market_wide_scan(
    scan_date: date,
    source: str,
    trend_template: pd.DataFrame,
    rs_rating: pd.DataFrame,
    quote: pd.DataFrame,
    market_json: Optional[str] = None,
    path: Optional[str] = None,
) -> int:
    """
    Store outputs from ibd_screener / market-wide Excel-equivalent dataframes.
    Returns run_id.
    """
    conn = connect(path)
    try:
        ensure_schema(conn)
        run_id = insert_scan_run(
            conn, scan_date, source, market_json=market_json, result_json=None
        )
        append_scan_rows(conn, run_id, scan_date, "trend_template", trend_template)
        append_scan_rows(conn, run_id, scan_date, "rs_rating", rs_rating)
        append_scan_rows(conn, run_id, scan_date, "quote", quote)
        return run_id
    finally:
        conn.close()


def persist_screener_json_result(
    result: dict[str, Any],
    source: str = "run_screener",
    path: Optional[str] = None,
) -> Optional[int]:
    """
    Store the JSON-serializable dict from scripts/run_screener.screen() (passed_stocks, market, etc.).
    Returns run_id or None if persistence is skipped / fails.
    """
    run_date = result.get("run_date")
    if not run_date:
        return None
    scan_date = datetime.strptime(run_date, "%Y-%m-%d").date()
    result_json = json.dumps(result, default=str)
    market = result.get("market") or {}
    market_json = json.dumps(market, default=str)

    conn = connect(path)
    try:
        ensure_schema(conn)
        run_id = insert_scan_run(
            conn,
            scan_date,
            source,
            market_json=market_json,
            result_json=result_json,
        )
        passed = result.get("passed_stocks") or []
        if passed:
            df = pd.DataFrame(passed)
            append_scan_rows(conn, run_id, scan_date, "passed_stocks", df)
        return run_id
    finally:
        conn.close()
