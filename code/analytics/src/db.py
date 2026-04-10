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
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
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


def count_news_articles_per_calendar_day_utc(n_days: int) -> dict[date, int]:
    """
    Count stored news rows per UTC calendar day for the last ``n_days`` (inclusive of today).

    Each row is bucketed by ``date_trunc('day', COALESCE(published_at, created_at))`` in UTC.
    Days with no rows are included with count ``0``.
    """
    if n_days < 1:
        raise ValueError("n_days must be >= 1")
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=n_days - 1)
    out: dict[date, int] = {start + timedelta(days=i): 0 for i in range(n_days)}
    schema = get_schema()
    sql = f"""
        SELECT
            ((COALESCE(published_at, created_at) AT TIME ZONE 'UTC')::date) AS d,
            COUNT(*)::bigint AS c
        FROM {schema}.news_articles
        WHERE ((COALESCE(published_at, created_at) AT TIME ZONE 'UTC')::date)
              BETWEEN %s AND %s
        GROUP BY 1
    """
    conn = get_pg_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql, (start, today))
        for row in cur.fetchall() or []:
            d, c = row[0], int(row[1])
            if d in out:
                out[d] = c
    finally:
        conn.close()
    return out


_EASTERN = ZoneInfo("America/New_York")


def count_news_articles_per_calendar_day_eastern(n_days: int) -> dict[date, int]:
    """
    Count stored news rows per US Eastern calendar day for the last ``n_days`` (inclusive of today ET).

    Each row is bucketed by the US Eastern date of ``COALESCE(published_at, created_at)``.
    Days with no rows are included with count ``0``.

    Use this instead of the UTC variant when the consumer uses Eastern-time date parameters
    (e.g. the FMP stock-news API).
    """
    if n_days < 1:
        raise ValueError("n_days must be >= 1")
    today = datetime.now(_EASTERN).date()
    start = today - timedelta(days=n_days - 1)
    out: dict[date, int] = {start + timedelta(days=i): 0 for i in range(n_days)}
    schema = get_schema()
    sql = f"""
        SELECT
            ((COALESCE(published_at, created_at) AT TIME ZONE 'America/New_York')::date) AS d,
            COUNT(*)::bigint AS c
        FROM {schema}.news_articles
        WHERE ((COALESCE(published_at, created_at) AT TIME ZONE 'America/New_York')::date)
              BETWEEN %s AND %s
        GROUP BY 1
    """
    conn = get_pg_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql, (start, today))
        for row in cur.fetchall() or []:
            d, c = row[0], int(row[1])
            if d in out:
                out[d] = c
    finally:
        conn.close()
    return out


def _tbl(client: Client, table: str):
    """Return a schema-aware PostgREST table query builder."""
    return client.schema(get_schema()).table(table)


def get_pg_connection():
    """
    Direct psycopg2 connection for DDL and complex SQL.
    Uses SUPABASE_DB_DIRECT_URL if set; otherwise constructs from project URL + password.
    Format: postgresql://postgres.<ref>:<pwd>@aws-0-<region>.pooler.supabase.com:6543/postgres
    or the direct host: postgresql://postgres:<pwd>@db.<ref>.supabase.co:5432/postgres
    JSONB columns are automatically decoded to Python dicts/lists.
    """
    import psycopg2
    import psycopg2.extras

    direct = os.environ.get("SUPABASE_DB_DIRECT_URL")
    if direct:
        conn = psycopg2.connect(direct)
    else:
        project_url = os.environ.get("SUPABASE_URL", "")
        pwd = os.environ.get("SUPABASE_DB_PWD", "")
        ref = project_url.replace("https://", "").split(".")[0]
        if not ref or not pwd:
            raise RuntimeError(
                "Set SUPABASE_DB_DIRECT_URL or both SUPABASE_DB_URL and SUPABASE_DB_PWD in .env"
            )
        url = f"postgresql://postgres:{pwd}@db.{ref}.supabase.co:5432/postgres"
        conn = psycopg2.connect(url)

    psycopg2.extras.register_default_jsonb(conn, globally=False, loads=json.loads)
    psycopg2.extras.register_default_json(conn, globally=False, loads=json.loads)
    return conn


def _as_json(val, default=None):
    """Safely coerce a value that may be a str (legacy TEXT) or already parsed (JSONB)."""
    if val is None:
        return default
    if isinstance(val, (dict, list)):
        return val
    try:
        return json.loads(val)
    except (json.JSONDecodeError, TypeError):
        return default


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
    try:
        conn = get_pg_connection()
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(
            "[db] ensure_schema: psycopg2 connection failed (%s) — assuming schema already exists", exc
        )
        return
    try:
        cur = conn.cursor()

        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")

        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS {schema}.scan_runs (
                id          BIGSERIAL PRIMARY KEY,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                scan_date   DATE NOT NULL,
                source      VARCHAR NOT NULL,
                market_json JSONB,
                result_json JSONB
            )
        """)

        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS {schema}.scan_rows (
                id        BIGSERIAL PRIMARY KEY,
                run_id    BIGINT NOT NULL,
                scan_date DATE NOT NULL,
                dataset   VARCHAR NOT NULL,
                symbol    VARCHAR,
                row_data  JSONB NOT NULL
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
                args_json        JSONB,
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
            CREATE UNIQUE INDEX IF NOT EXISTS idx_news_articles_url_unique
            ON {schema}.news_articles (url)
            WHERE url IS NOT NULL AND trim(url) <> ''
        """)
        cur.execute(
            f"ALTER TABLE {schema}.news_articles ADD COLUMN IF NOT EXISTS image_url TEXT"
        )
        cur.execute(
            f"ALTER TABLE {schema}.news_articles ADD COLUMN IF NOT EXISTS slug TEXT"
        )
        cur.execute(f"""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_news_articles_slug_unique
            ON {schema}.news_articles (slug)
            WHERE slug IS NOT NULL AND trim(slug) <> ''
        """)
        cur.execute(f"""
            CREATE OR REPLACE FUNCTION {schema}.set_news_article_slug()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $fn$
            DECLARE
                base_slug text;
                candidate text;
                suffix int := 2;
            BEGIN
                IF NEW.slug IS NOT NULL AND btrim(NEW.slug) <> '' THEN
                    RETURN NEW;
                END IF;

                base_slug := regexp_replace(lower(COALESCE(NEW.title, '')), '[^a-z0-9]+', '-', 'g');
                base_slug := btrim(base_slug, '-');
                IF base_slug = '' THEN
                    base_slug := 'article-' || left(COALESCE(NEW.article_hash, md5(random()::text)), 10);
                END IF;

                candidate := base_slug;
                WHILE EXISTS (
                    SELECT 1
                    FROM {schema}.news_articles na
                    WHERE na.slug = candidate
                      AND (NEW.id IS NULL OR na.id <> NEW.id)
                ) LOOP
                    candidate := base_slug || '-' || suffix::text;
                    suffix := suffix + 1;
                END LOOP;

                NEW.slug := candidate;
                RETURN NEW;
            END;
            $fn$;
        """)
        cur.execute(f"DROP TRIGGER IF EXISTS trg_set_news_article_slug ON {schema}.news_articles")
        cur.execute(f"""
            CREATE TRIGGER trg_set_news_article_slug
            BEFORE INSERT OR UPDATE OF title, article_hash, slug
            ON {schema}.news_articles
            FOR EACH ROW
            EXECUTE FUNCTION {schema}.set_news_article_slug()
        """)

        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS {schema}.news_impact_heads (
                id            BIGSERIAL PRIMARY KEY,
                article_id    BIGINT NOT NULL,
                cluster       VARCHAR NOT NULL,
                scores_json   JSONB NOT NULL,
                reasoning_json JSONB,
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
                impact_json    JSONB NOT NULL,
                top_dimensions JSONB,
                created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)

        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS {schema}.company_vectors (
                id              BIGSERIAL PRIMARY KEY,
                ticker          VARCHAR NOT NULL,
                vector_date     DATE NOT NULL,
                dimensions_json JSONB NOT NULL,
                raw_json        JSONB,
                metadata_json   JSONB,
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
    user_id: Optional[str] = None,
) -> int:
    """Insert a scan_jobs row with status='running'. Returns the generated job id."""
    client = get_supabase_client()
    now = datetime.now().isoformat()
    row: dict[str, Any] = {
        "created_at": now,
        "started_at": now,
        "status": "running",
        "scan_source": scan_source,
        "script_rel": script_rel,
        "args_json": args,
        "stdout_log": stdout_log,
        "stderr_log": stderr_log,
    }
    if user_id is not None:
        row["user_id"] = user_id
    result = _tbl(client, "user_scan_jobs").insert(row).execute()
    return result.data[0]["id"]


def update_scan_job_pid(job_id: int, pid: int) -> None:
    client = get_supabase_client()
    _tbl(client, "user_scan_jobs").update({"pid": pid}).eq("id", job_id).execute()


def update_scan_job_progress(job_id: int, message: str) -> None:
    client = get_supabase_client()
    _tbl(client, "user_scan_jobs").update({"progress_message": message}).eq("id", job_id).execute()


def finish_scan_job(
    job_id: int,
    exit_code: int,
    error_message: Optional[str] = None,
) -> None:
    """Mark job completed (exit_code==0) or failed; links scan_run_id when done."""
    client = get_supabase_client()

    job_res = _tbl(client, "user_scan_jobs").select("scan_source,started_at").eq("id", job_id).single().execute()
    if not job_res.data:
        return

    scan_source = job_res.data["scan_source"]
    started_at = job_res.data["started_at"]
    status = "completed" if exit_code == 0 else "failed"

    scan_run_id = None
    if status == "completed":
        r2 = (
            _tbl(client, "user_scan_runs")
            .select("id")
            .eq("source", scan_source)
            .gte("created_at", started_at)
            .order("id", desc=True)
            .limit(1)
            .execute()
        )
        if r2.data:
            scan_run_id = r2.data[0]["id"]

    _tbl(client, "user_scan_jobs").update({
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
    market_json: Optional[dict] = None,
    result_json: Optional[dict] = None,
    user_id: Optional[str] = None,
) -> int:
    """Insert a new scan_runs row; returns the auto-generated run_id."""
    row: dict[str, Any] = {
        "scan_date": scan_date.isoformat(),
        "source": source,
        "market_json": market_json,
        "result_json": result_json,
    }
    if user_id is not None:
        row["user_id"] = user_id
    result = _tbl(client, "user_scan_runs").insert(row).execute()
    return result.data[0]["id"]


def _clean_row(rec: dict[str, Any]) -> dict[str, Any]:
    """Sanitise a record dict for JSONB insertion: replace NaN/inf and non-serialisable types."""
    import math
    out = {}
    for k, v in rec.items():
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            out[k] = None
        elif isinstance(v, (datetime, date)):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


def append_scan_rows(
    client: Client,
    run_id: int,
    scan_date: date,
    dataset: str,
    df: Any,  # pandas.DataFrame
    user_id: Optional[str] = None,
) -> int:
    """Batch-insert each row of df as JSONB in scan_rows. Returns number of rows inserted."""
    if df is None or df.empty:
        return 0

    rows = []
    for rec in df.to_dict(orient="records"):
        cleaned = _clean_row(rec)

        sym = None
        for k in ("symbol", "ticker", "Symbol"):
            if k in cleaned and cleaned[k] is not None and str(cleaned[k]).strip():
                sym = str(cleaned[k]).strip()
                break

        row: dict[str, Any] = {
            "run_id": run_id,
            "scan_date": scan_date.isoformat(),
            "dataset": dataset,
            "symbol": sym,
            "row_data": cleaned,
        }
        if user_id is not None:
            row["user_id"] = user_id
        rows.append(row)

    if rows:
        _tbl(client, "user_scan_rows").insert(rows).execute()
    return len(rows)


def persist_market_wide_scan(
    scan_date: date,
    source: str,
    trend_template: Any,
    rs_rating: Any,
    quote: Any,
    market_json: Optional[str] = None,
    user_id: Optional[str] = None,
) -> int:
    """Store outputs from ibd_screener / market-wide scans. Returns run_id."""
    client = get_supabase_client()
    run_id = insert_scan_run(client, scan_date, source, market_json=market_json, user_id=user_id)
    append_scan_rows(client, run_id, scan_date, "trend_template", trend_template, user_id=user_id)
    append_scan_rows(client, run_id, scan_date, "rs_rating", rs_rating, user_id=user_id)
    append_scan_rows(client, run_id, scan_date, "quote", quote, user_id=user_id)
    return run_id


def persist_screener_json_result(
    result: dict[str, Any],
    source: str = "run_screener",
    user_id: Optional[str] = None,
) -> Optional[int]:
    """Store a run_screener result dict. Returns run_id or None."""
    run_date = result.get("run_date")
    if not run_date:
        return None

    scan_date = datetime.strptime(run_date, "%Y-%m-%d").date()

    client = get_supabase_client()
    run_id = insert_scan_run(
        client, scan_date, source,
        market_json=result.get("market") or {},
        result_json=result,
        user_id=user_id,
    )

    passed = result.get("passed_stocks") or []
    if passed:
        import pandas as pd
        append_scan_rows(client, run_id, scan_date, "passed_stocks", pd.DataFrame(passed), user_id=user_id)

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


def load_article_tickers(
    client: Client,
    article_id: int,
    source: Optional[str] = "extracted",
) -> list[str]:
    """
    Load ticker mentions for an article.
    If source is provided, returns only that source (default: extracted).
    """
    q = _tbl(client, "news_article_tickers").select("ticker").eq("article_id", article_id)
    if source is not None:
        q = q.eq("source", source)
    res = q.execute()
    tickers = sorted({
        str(row.get("ticker", "")).upper().strip()
        for row in (res.data or [])
        if row.get("ticker")
    })
    return tickers


def patch_news_article_image_if_missing(
    client: Client,
    article_id: int,
    image_url: Optional[str],
) -> None:
    """
    Set ``image_url`` on ``news_articles`` only when the row has no image yet
    (NULL or blank). Used when an article is skipped as a duplicate but the
    API now provides a thumbnail URL.
    """
    url = (image_url or "").strip()
    if not url or article_id < 0:
        return
    res = (
        _tbl(client, "news_articles")
        .select("image_url")
        .eq("id", article_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        return
    cur = res.data[0].get("image_url")
    if cur is not None and str(cur).strip():
        return
    _tbl(client, "news_articles").update({"image_url": url}).eq("id", article_id).execute()


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
        "dimensions_json": dimensions,
        "raw_json": raw,
        "metadata_json": metadata,
        "fetched_at": fetched_at.isoformat(),
    }, on_conflict="ticker,vector_date").execute()


def load_company_vectors(
    client: Client,
    tickers: Optional[list[str]] = None,
    vector_date: Optional[date] = None,
) -> list[dict]:
    """
    Load company vectors, returning the most-recent row per ticker when no date is given.

    Latest-per-ticker uses the PostgREST API only (same HTTPS path as writes). Direct
    Postgres (port 5432) is not used here, so environments where REST works but
    db.<project>.supabase.co is unreachable (e.g. IPv6 routing) still load cache.
    """
    _cols = "ticker,vector_date,dimensions_json,raw_json,metadata_json,fetched_at"

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
        # Latest row per ticker via PostgREST (no direct Postgres connection).
        if tickers is not None and len(tickers) == 0:
            rows_data = []
        elif tickers:
            rows_data = []
            for t in tickers:
                res = (
                    _tbl(client, "company_vectors")
                    .select(_cols)
                    .eq("ticker", t)
                    .order("vector_date", desc=True)
                    .limit(1)
                    .execute()
                )
                if res.data:
                    rows_data.append(res.data[0])
        else:
            # All tickers: paginate full table, keep max vector_date per ticker in memory.
            rows_data = []
            page_size = 1000
            offset = 0
            best: dict[str, dict] = {}
            while True:
                res = (
                    _tbl(client, "company_vectors")
                    .select(_cols)
                    .range(offset, offset + page_size - 1)
                    .execute()
                )
                batch = res.data or []
                if not batch:
                    break
                for row in batch:
                    t = row.get("ticker")
                    if not t:
                        continue
                    vd = str(row.get("vector_date") or "")
                    prev = best.get(t)
                    if prev is None or vd > str(prev.get("vector_date") or ""):
                        best[t] = row
                if len(batch) < page_size:
                    break
                offset += page_size
            rows_data = list(best.values())

    results = []
    for row in rows_data:
        try:
            vdate = row["vector_date"]
            results.append({
                "ticker": row["ticker"],
                "vector_date": datetime.strptime(str(vdate), "%Y-%m-%d").date() if isinstance(vdate, str) else vdate,
                "dimensions": _as_json(row["dimensions_json"], default={}),
                "raw": _as_json(row["raw_json"], default={}),
                "metadata": _as_json(row["metadata_json"], default={}),
                "fetched_at": (
                    datetime.fromisoformat(row["fetched_at"])
                    if isinstance(row["fetched_at"], str)
                    else row["fetched_at"]
                ),
            })
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
    return results
