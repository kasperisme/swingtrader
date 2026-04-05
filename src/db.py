"""
Supabase/PostgreSQL persistence for screening runs — queryable by local agents (e.g. Hans).

All tables live in the 'swingtrader' schema (SUPABASE_SCHEMA env var, default: swingtrader).

Environment variables required:
  SUPABASE_URL           - Supabase project URL (https://<ref>.supabase.co)
  SUPABASE_KEY           - Anon/service-role key
  SUPABASE_DB_PWD        - Database password (for psycopg2 DDL / complex queries)
  SUPABASE_SCHEMA        - Schema name (default: swingtrader)
  SUPABASE_DB_DIRECT_URL - Optional: full postgres:// URL; overrides URL+PWD construction

NOTE: The swingtrader schema must be exposed in Supabase → Settings → API → Extra search path.

Tables (all in swingtrader schema):
  scan_runs      — one row per run (source, scan_date, market_json, result_json)
  scan_rows      — normalised per-stock rows; row_data is JSON text
  scan_jobs      — background screener process state
  news_articles  — article content and metadata
  news_impact_heads   — AI scoring results
  news_impact_vectors — impact dimension vectors
  company_vectors     — company embedding vectors per ticker per date
  news_article_tickers — ticker mentions in articles
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

from supabase import create_client, Client
from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=_REPO_ROOT / ".env")


# ---------------------------------------------------------------------------
# Client helpers
# ---------------------------------------------------------------------------

def get_supabase_client() -> Client:
    """Create and return a Supabase client."""
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set in .env")
    return create_client(url, key)


def get_schema() -> str:
    return os.environ.get("SUPABASE_SCHEMA", "swingtrader")


def _tbl(client: Client, table: str):
    """Return a schema-aware PostgREST table query builder."""
    return client.schema(get_schema()).table(table)


def get_pg_connection():
    """
    Direct psycopg2 connection for DDL and complex SQL.
    Uses SUPABASE_DB_DIRECT_URL if set; otherwise constructs from project URL + password.
    Format: postgresql://postgres.<ref>:<pwd>@aws-0-<region>.pooler.supabase.com:6543/postgres
    or the direct host: postgresql://postgres:<pwd>@db.<ref>.supabase.co:5432/postgres
    """
    import psycopg2

    direct = os.environ.get("SUPABASE_DB_DIRECT_URL")
    if direct:
        return psycopg2.connect(direct)

    project_url = os.environ.get("SUPABASE_URL", "")
    pwd = os.environ.get("SUPABASE_DB_PWD", "")
    # Extract ref from https://<ref>.supabase.co
    ref = project_url.replace("https://", "").split(".")[0]
    if not ref or not pwd:
        raise RuntimeError(
            "Set SUPABASE_DB_DIRECT_URL or both SUPABASE_DB_URL and SUPABASE_DB_PWD in .env"
        )
    url = f"postgresql://postgres:{pwd}@db.{ref}.supabase.co:5432/postgres"
    return psycopg2.connect(url)


# ---------------------------------------------------------------------------
# Schema / DDL
# ---------------------------------------------------------------------------

def ensure_schema(client: Optional[Client] = None) -> None:
    """
    Create the swingtrader schema and all required tables if they don't exist.
    Uses a direct psycopg2 connection (DDL is not supported through PostgREST).
    The `client` argument is accepted but ignored (kept for call-site compatibility).
    """
    schema = get_schema()
    conn = get_pg_connection()
    try:
        cur = conn.cursor()

        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")

        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS {schema}.scan_runs (
                id          BIGSERIAL PRIMARY KEY,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                scan_date   DATE NOT NULL,
                source      VARCHAR NOT NULL,
                market_json TEXT,
                result_json TEXT
            )
        """)

        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS {schema}.scan_rows (
                id        BIGSERIAL PRIMARY KEY,
                run_id    BIGINT NOT NULL,
                scan_date DATE NOT NULL,
                dataset   VARCHAR NOT NULL,
                symbol    VARCHAR,
                row_data  TEXT NOT NULL
            )
        """)
        cur.execute(f"CREATE INDEX IF NOT EXISTS idx_scan_rows_run ON {schema}.scan_rows(run_id)")
        cur.execute(f"CREATE INDEX IF NOT EXISTS idx_scan_rows_symbol ON {schema}.scan_rows(symbol)")
        cur.execute(f"CREATE INDEX IF NOT EXISTS idx_scan_rows_dataset ON {schema}.scan_rows(dataset)")

        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS {schema}.scan_jobs (
                id               BIGSERIAL PRIMARY KEY,
                created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                started_at       TIMESTAMPTZ NOT NULL,
                finished_at      TIMESTAMPTZ,
                status           VARCHAR NOT NULL,
                scan_source      VARCHAR NOT NULL,
                script_rel       VARCHAR NOT NULL,
                args_json        TEXT,
                pid              INTEGER,
                exit_code        INTEGER,
                scan_run_id      BIGINT,
                stdout_log       TEXT,
                stderr_log       TEXT,
                error_message    TEXT,
                progress_message VARCHAR
            )
        """)
        cur.execute(f"CREATE INDEX IF NOT EXISTS idx_scan_jobs_status ON {schema}.scan_jobs(status)")
        cur.execute(f"CREATE INDEX IF NOT EXISTS idx_scan_jobs_started ON {schema}.scan_jobs(started_at)")

        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS {schema}.news_articles (
                id           BIGSERIAL PRIMARY KEY,
                created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                url          VARCHAR,
                title        VARCHAR,
                body         TEXT NOT NULL,
                source       VARCHAR,
                article_hash VARCHAR NOT NULL UNIQUE
            )
        """)

        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS {schema}.news_impact_heads (
                id            BIGSERIAL PRIMARY KEY,
                article_id    BIGINT NOT NULL,
                cluster       VARCHAR NOT NULL,
                scores_json   TEXT NOT NULL,
                reasoning_json TEXT,
                confidence    DOUBLE PRECISION NOT NULL,
                model         VARCHAR NOT NULL,
                latency_ms    INTEGER,
                created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        cur.execute(f"CREATE INDEX IF NOT EXISTS idx_news_heads_article ON {schema}.news_impact_heads(article_id)")

        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS {schema}.news_impact_vectors (
                id             BIGSERIAL PRIMARY KEY,
                article_id     BIGINT NOT NULL UNIQUE,
                impact_json    TEXT NOT NULL,
                top_dimensions TEXT,
                created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)

        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS {schema}.company_vectors (
                id              BIGSERIAL PRIMARY KEY,
                ticker          VARCHAR NOT NULL,
                vector_date     DATE NOT NULL,
                dimensions_json TEXT NOT NULL,
                raw_json        TEXT,
                metadata_json   TEXT,
                fetched_at      TIMESTAMPTZ NOT NULL,
                UNIQUE (ticker, vector_date)
            )
        """)
        cur.execute(f"CREATE INDEX IF NOT EXISTS idx_company_vectors_ticker ON {schema}.company_vectors(ticker)")

        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS {schema}.news_article_tickers (
                article_id BIGINT NOT NULL,
                ticker     VARCHAR NOT NULL,
                source     VARCHAR NOT NULL,
                PRIMARY KEY (article_id, ticker)
            )
        """)
        cur.execute(f"CREATE INDEX IF NOT EXISTS idx_article_tickers_ticker ON {schema}.news_article_tickers(ticker)")

        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Scan jobs
# ---------------------------------------------------------------------------

def create_scan_job(
    scan_source: str,
    script_rel: str,
    args: list[str],
    stdout_log: str,
    stderr_log: str,
) -> int:
    """Insert a scan_jobs row with status='running'. Returns the generated job id."""
    client = get_supabase_client()
    now = datetime.now().isoformat()
    result = _tbl(client, "scan_jobs").insert({
        "created_at": now,
        "started_at": now,
        "status": "running",
        "scan_source": scan_source,
        "script_rel": script_rel,
        "args_json": json.dumps(args),
        "stdout_log": stdout_log,
        "stderr_log": stderr_log,
    }).execute()
    return result.data[0]["id"]


def update_scan_job_pid(job_id: int, pid: int) -> None:
    client = get_supabase_client()
    _tbl(client, "scan_jobs").update({"pid": pid}).eq("id", job_id).execute()


def update_scan_job_progress(job_id: int, message: str) -> None:
    client = get_supabase_client()
    _tbl(client, "scan_jobs").update({"progress_message": message}).eq("id", job_id).execute()


def finish_scan_job(
    job_id: int,
    exit_code: int,
    error_message: Optional[str] = None,
) -> None:
    """Mark job completed (exit_code==0) or failed; links scan_run_id when done."""
    client = get_supabase_client()

    job_res = _tbl(client, "scan_jobs").select("scan_source,started_at").eq("id", job_id).single().execute()
    if not job_res.data:
        return

    scan_source = job_res.data["scan_source"]
    started_at = job_res.data["started_at"]
    status = "completed" if exit_code == 0 else "failed"

    scan_run_id = None
    if status == "completed":
        r2 = (
            _tbl(client, "scan_runs")
            .select("id")
            .eq("source", scan_source)
            .gte("created_at", started_at)
            .order("id", desc=True)
            .limit(1)
            .execute()
        )
        if r2.data:
            scan_run_id = r2.data[0]["id"]

    _tbl(client, "scan_jobs").update({
        "finished_at": datetime.now().isoformat(),
        "status": status,
        "exit_code": exit_code,
        "scan_run_id": scan_run_id,
        "error_message": error_message,
    }).eq("id", job_id).execute()


# ---------------------------------------------------------------------------
# Scan runs / rows
# ---------------------------------------------------------------------------

def insert_scan_run(
    client: Client,
    scan_date: date,
    source: str,
    market_json: Optional[str] = None,
    result_json: Optional[str] = None,
) -> int:
    """Insert a new scan_runs row; returns the auto-generated run_id."""
    result = _tbl(client, "scan_runs").insert({
        "scan_date": scan_date.isoformat(),
        "source": source,
        "market_json": market_json,
        "result_json": result_json,
    }).execute()
    return result.data[0]["id"]


def _json_row(rec: dict[str, Any]) -> str:
    def default(o: Any) -> Any:
        if isinstance(o, (datetime, date)):
            return o.isoformat()
        return str(o)
    return json.dumps(rec, default=default)


def append_scan_rows(
    client: Client,
    run_id: int,
    scan_date: date,
    dataset: str,
    df: Any,  # pandas.DataFrame
) -> int:
    """Batch-insert each row of df as JSON in scan_rows. Returns number of rows inserted."""
    import pandas as pd

    if df is None or df.empty:
        return 0

    rows = []
    for rec in df.to_dict(orient="records"):
        for k, v in list(rec.items()):
            if isinstance(v, float) and (v != v or abs(v) == float("inf")):
                rec[k] = None
            elif v is not None and isinstance(v, float) and pd.isna(v):
                rec[k] = None

        sym = None
        for k in ("symbol", "ticker", "Symbol"):
            if k in rec and rec[k] is not None and str(rec[k]).strip():
                sym = str(rec[k]).strip()
                break

        rows.append({
            "run_id": run_id,
            "scan_date": scan_date.isoformat(),
            "dataset": dataset,
            "symbol": sym,
            "row_data": _json_row(rec),
        })

    if rows:
        _tbl(client, "scan_rows").insert(rows).execute()
    return len(rows)


def persist_market_wide_scan(
    scan_date: date,
    source: str,
    trend_template: Any,
    rs_rating: Any,
    quote: Any,
    market_json: Optional[str] = None,
) -> int:
    """Store outputs from ibd_screener / market-wide scans. Returns run_id."""
    client = get_supabase_client()
    run_id = insert_scan_run(client, scan_date, source, market_json=market_json)
    append_scan_rows(client, run_id, scan_date, "trend_template", trend_template)
    append_scan_rows(client, run_id, scan_date, "rs_rating", rs_rating)
    append_scan_rows(client, run_id, scan_date, "quote", quote)
    return run_id


def persist_screener_json_result(
    result: dict[str, Any],
    source: str = "run_screener",
) -> Optional[int]:
    """Store a run_screener result dict. Returns run_id or None."""
    run_date = result.get("run_date")
    if not run_date:
        return None

    scan_date = datetime.strptime(run_date, "%Y-%m-%d").date()
    result_json = json.dumps(result, default=str)
    market_json = json.dumps(result.get("market") or {}, default=str)

    client = get_supabase_client()
    run_id = insert_scan_run(client, scan_date, source, market_json=market_json, result_json=result_json)

    passed = result.get("passed_stocks") or []
    if passed:
        import pandas as pd
        append_scan_rows(client, run_id, scan_date, "passed_stocks", pd.DataFrame(passed))

    return run_id


# ---------------------------------------------------------------------------
# News / articles
# ---------------------------------------------------------------------------

def save_article_tickers(
    client: Client,
    article_id: int,
    tickers: list[str],
    source: str = "extracted",
) -> None:
    """Persist ticker mentions for an article (delete + insert per source)."""
    _tbl(client, "news_article_tickers").delete().eq("article_id", article_id).eq("source", source).execute()
    if tickers:
        _tbl(client, "news_article_tickers").insert([
            {"article_id": article_id, "ticker": t, "source": source} for t in tickers
        ]).execute()


# ---------------------------------------------------------------------------
# Company vectors
# ---------------------------------------------------------------------------

def upsert_company_vector(
    client: Client,
    ticker: str,
    vector_date: date,
    dimensions: dict,
    raw: dict,
    metadata: dict,
    fetched_at: datetime,
) -> None:
    """Insert or replace a company vector row (one per ticker per day)."""
    _tbl(client, "company_vectors").upsert({
        "ticker": ticker,
        "vector_date": vector_date.isoformat(),
        "dimensions_json": json.dumps(dimensions),
        "raw_json": json.dumps(raw, default=str),
        "metadata_json": json.dumps(metadata, default=str),
        "fetched_at": fetched_at.isoformat(),
    }, on_conflict="ticker,vector_date").execute()


def load_company_vectors(
    client: Client,
    tickers: Optional[list[str]] = None,
    vector_date: Optional[date] = None,
) -> list[dict]:
    """
    Load company vectors, returning the most-recent row per ticker when no date is given.
    Uses a direct SQL query (DISTINCT ON) for the latest-per-ticker case.
    """
    schema = get_schema()

    if vector_date and tickers:
        # Simple filter — use table API
        res = (
            _tbl(client, "company_vectors")
            .select("ticker,vector_date,dimensions_json,raw_json,metadata_json,fetched_at")
            .eq("vector_date", vector_date.isoformat())
            .in_("ticker", tickers)
            .execute()
        )
        rows_data = res.data or []

    elif vector_date:
        res = (
            _tbl(client, "company_vectors")
            .select("ticker,vector_date,dimensions_json,raw_json,metadata_json,fetched_at")
            .eq("vector_date", vector_date.isoformat())
            .execute()
        )
        rows_data = res.data or []

    else:
        # Need DISTINCT ON (ticker) ORDER BY ticker, vector_date DESC — use psycopg2
        conn = get_pg_connection()
        try:
            cur = conn.cursor()
            if tickers:
                placeholders = ",".join(["%s"] * len(tickers))
                cur.execute(
                    f"""
                    SELECT DISTINCT ON (ticker)
                        ticker, vector_date, dimensions_json, raw_json, metadata_json, fetched_at
                    FROM {schema}.company_vectors
                    WHERE ticker IN ({placeholders})
                    ORDER BY ticker, vector_date DESC
                    """,
                    tickers,
                )
            else:
                cur.execute(
                    f"""
                    SELECT DISTINCT ON (ticker)
                        ticker, vector_date, dimensions_json, raw_json, metadata_json, fetched_at
                    FROM {schema}.company_vectors
                    ORDER BY ticker, vector_date DESC
                    """
                )
            cols = ["ticker", "vector_date", "dimensions_json", "raw_json", "metadata_json", "fetched_at"]
            rows_data = [dict(zip(cols, row)) for row in cur.fetchall()]
        finally:
            conn.close()

    results = []
    for row in rows_data:
        try:
            vdate = row["vector_date"]
            results.append({
                "ticker": row["ticker"],
                "vector_date": datetime.strptime(str(vdate), "%Y-%m-%d").date() if isinstance(vdate, str) else vdate,
                "dimensions": json.loads(row["dimensions_json"] or "{}"),
                "raw": json.loads(row["raw_json"] or "{}"),
                "metadata": json.loads(row["metadata_json"] or "{}"),
                "fetched_at": (
                    datetime.fromisoformat(row["fetched_at"])
                    if isinstance(row["fetched_at"], str)
                    else row["fetched_at"]
                ),
            })
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
    return results
