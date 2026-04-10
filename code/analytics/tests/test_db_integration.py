"""
Integration tests for src/db.py against a live Supabase instance.

Requires .env with SUPABASE_URL, SUPABASE_KEY, SUPABASE_DB_PWD set.
All test data is written with source/scan_source prefixed "pytest_"
and cleaned up in teardown.

Run:
    .venv/bin/python -m pytest tests/test_db_integration.py -v
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pytest
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from postgrest.exceptions import APIError

from src.db import (
    get_supabase_client,
    get_schema,
    ensure_schema,
    insert_scan_run,
    append_scan_rows,
    persist_market_wide_scan,
    persist_screener_json_result,
    create_scan_job,
    update_scan_job_pid,
    update_scan_job_progress,
    finish_scan_job,
    save_article_tickers,
    upsert_company_vector,
    load_company_vectors,
    _tbl,
)

_TEST_SOURCE = "pytest_integration"
_TEST_DATE = date(2000, 1, 1)  # fixed date so cleanup is deterministic


# ---------------------------------------------------------------------------
# Module-level connectivity check
# ---------------------------------------------------------------------------

def _check_schema_accessible() -> str | None:
    """Return an error message if the swingtrader schema is not accessible, else None."""
    try:
        c = get_supabase_client()
        _tbl(c, "user_scan_runs").select("id").limit(1).execute()
        return None
    except APIError as e:
        return str(e)
    except Exception as e:
        return str(e)


_SCHEMA_ERROR = _check_schema_accessible()
_skip_if_no_schema = pytest.mark.skipif(
    _SCHEMA_ERROR is not None,
    reason=(
        f"swingtrader schema not accessible ({_SCHEMA_ERROR}). "
        "Run the migration first: supabase/migrations/20260406000000_create_swingtrader_schema.sql"
    ),
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    """Shared Supabase client; ensures schema exists before any test runs."""
    c = get_supabase_client()
    ensure_schema()
    return c


@pytest.fixture(autouse=True)
def cleanup(client):
    """Delete all rows written by this test module after each test."""
    yield
    schema = get_schema()
    # Jobs
    _tbl(client, "user_scan_jobs").delete().eq("scan_source", _TEST_SOURCE).execute()
    # Rows + runs
    runs = _tbl(client, "user_scan_runs").select("id").eq("source", _TEST_SOURCE).execute()
    run_ids = [r["id"] for r in (runs.data or [])]
    for rid in run_ids:
        _tbl(client, "user_scan_rows").delete().eq("run_id", rid).execute()
    _tbl(client, "user_scan_runs").delete().eq("source", _TEST_SOURCE).execute()
    # Company vectors (test ticker)
    _tbl(client, "company_vectors").delete().eq("ticker", "PYTEST").execute()
    # Article tickers / articles (test hash prefix is not feasible so use title)
    articles = _tbl(client, "news_articles").select("id").eq("source", _TEST_SOURCE).execute()
    article_ids = [r["id"] for r in (articles.data or [])]
    for aid in article_ids:
        _tbl(client, "news_article_tickers").delete().eq("article_id", aid).execute()
        _tbl(client, "news_impact_heads").delete().eq("article_id", aid).execute()
        _tbl(client, "news_impact_vectors").delete().eq("article_id", aid).execute()
    _tbl(client, "news_articles").delete().eq("source", _TEST_SOURCE).execute()


# ---------------------------------------------------------------------------
# ensure_schema
# ---------------------------------------------------------------------------

@_skip_if_no_schema
class TestEnsureSchema:
    def test_is_idempotent(self):
        """Calling ensure_schema() twice should not raise."""
        ensure_schema()
        ensure_schema()

    def test_tables_exist(self, client):
        """All expected tables are queryable via the table API."""
        tables = [
            "user_scan_runs", "user_scan_rows", "user_scan_jobs",
            "news_articles", "news_impact_heads", "news_impact_vectors",
            "company_vectors", "news_article_tickers",
        ]
        for table in tables:
            res = _tbl(client, table).select("*").limit(1).execute()
            assert res.data is not None, f"table {table} not queryable"


# ---------------------------------------------------------------------------
# scan_runs
# ---------------------------------------------------------------------------

@_skip_if_no_schema
class TestScanRuns:
    def test_insert_returns_id(self, client):
        run_id = insert_scan_run(client, _TEST_DATE, _TEST_SOURCE)
        assert isinstance(run_id, int)
        assert run_id > 0

    def test_inserted_row_is_readable(self, client):
        run_id = insert_scan_run(
            client, _TEST_DATE, _TEST_SOURCE,
            market_json='{"condition":"uptrend"}',
            result_json='{"passed_count":5}',
        )
        res = _tbl(client, "user_scan_runs").select("*").eq("id", run_id).single().execute()
        row = res.data
        assert row["source"] == _TEST_SOURCE
        assert row["market_json"] == '{"condition":"uptrend"}'
        assert row["result_json"] == '{"passed_count":5}'

    def test_scan_date_stored_correctly(self, client):
        run_id = insert_scan_run(client, date(2025, 6, 15), _TEST_SOURCE)
        res = _tbl(client, "user_scan_runs").select("scan_date").eq("id", run_id).single().execute()
        assert res.data["scan_date"] == "2025-06-15"


# ---------------------------------------------------------------------------
# scan_rows
# ---------------------------------------------------------------------------

@_skip_if_no_schema
class TestScanRows:
    def test_append_returns_row_count(self, client):
        run_id = insert_scan_run(client, _TEST_DATE, _TEST_SOURCE)
        df = pd.DataFrame([
            {"symbol": "AAPL", "price": 180.0, "rs_rank": 92},
            {"symbol": "MSFT", "price": 420.0, "rs_rank": 88},
        ])
        n = append_scan_rows(client, run_id, _TEST_DATE, "passed_stocks", df)
        assert n == 2

    def test_rows_are_readable(self, client):
        run_id = insert_scan_run(client, _TEST_DATE, _TEST_SOURCE)
        df = pd.DataFrame([{"symbol": "NVDA", "price": 900.0, "sector": "Technology"}])
        append_scan_rows(client, run_id, _TEST_DATE, "trend_template", df)

        res = (
            _tbl(client, "user_scan_rows")
            .select("symbol,dataset,row_data")
            .eq("run_id", run_id)
            .execute()
        )
        assert len(res.data) == 1
        row = res.data[0]
        assert row["symbol"] == "NVDA"
        assert row["dataset"] == "trend_template"
        parsed = json.loads(row["row_data"])
        assert parsed["price"] == 900.0

    def test_nan_values_become_null(self, client):
        import numpy as np
        run_id = insert_scan_run(client, _TEST_DATE, _TEST_SOURCE)
        df = pd.DataFrame([{"symbol": "XYZ", "price": float("nan"), "rs_rank": None}])
        append_scan_rows(client, run_id, _TEST_DATE, "passed_stocks", df)

        res = _tbl(client, "user_scan_rows").select("row_data").eq("run_id", run_id).single().execute()
        parsed = json.loads(res.data["row_data"])
        assert parsed["price"] is None
        assert parsed["rs_rank"] is None

    def test_empty_dataframe_returns_zero(self, client):
        run_id = insert_scan_run(client, _TEST_DATE, _TEST_SOURCE)
        n = append_scan_rows(client, run_id, _TEST_DATE, "passed_stocks", pd.DataFrame())
        assert n == 0


# ---------------------------------------------------------------------------
# persist_market_wide_scan
# ---------------------------------------------------------------------------

@_skip_if_no_schema
class TestPersistMarketWideScan:
    def test_returns_run_id_and_writes_rows(self):
        df_tt = pd.DataFrame([
            {"symbol": "AAPL", "Passed": True, "RSOver70": True, "sector": "Technology"},
            {"symbol": "MSFT", "Passed": False, "RSOver70": True, "sector": "Technology"},
        ])
        df_rs = pd.DataFrame([{"symbol": "AAPL", "RS": 91.0}])
        df_quote = pd.DataFrame([{"symbol": "AAPL", "price": 180.0}])

        client = get_supabase_client()
        run_id = persist_market_wide_scan(
            _TEST_DATE, _TEST_SOURCE, df_tt, df_rs, df_quote,
            market_json='{"condition":"uptrend"}',
        )
        assert isinstance(run_id, int)

        # Check datasets were written
        datasets = {
            r["dataset"]
            for r in _tbl(client, "user_scan_rows").select("dataset").eq("run_id", run_id).execute().data
        }
        assert datasets == {"trend_template", "rs_rating", "quote"}


# ---------------------------------------------------------------------------
# persist_screener_json_result
# ---------------------------------------------------------------------------

@_skip_if_no_schema
class TestPersistScreenerJsonResult:
    def test_full_result_round_trip(self):
        result = {
            "run_date": _TEST_DATE.isoformat(),
            "fatal": False,
            "market": {"condition": "uptrend", "is_confirmed_uptrend": True, "distribution_days": 1},
            "total_ibd_tickers": 100,
            "total_after_liquidity": 80,
            "pre_screened_count": 50,
            "passed_count": 3,
            "error_count": 0,
            "errors": [],
            "passed_stocks": [
                {"symbol": "AAPL", "sector": "Technology", "within_buy_range": True, "extension_pct": 1.2},
                {"symbol": "MSFT", "sector": "Technology", "within_buy_range": False, "extension_pct": 6.5},
                {"symbol": "NVDA", "sector": "Technology", "within_buy_range": True, "extension_pct": 2.1},
            ],
        }
        run_id = persist_screener_json_result(result, source=_TEST_SOURCE)
        assert isinstance(run_id, int)

        client = get_supabase_client()
        run_res = _tbl(client, "user_scan_runs").select("result_json").eq("id", run_id).single().execute()
        stored = json.loads(run_res.data["result_json"])
        assert stored["passed_count"] == 3

        rows_res = _tbl(client, "user_scan_rows").select("symbol").eq("run_id", run_id).execute()
        symbols = {r["symbol"] for r in rows_res.data}
        assert symbols == {"AAPL", "MSFT", "NVDA"}

    def test_missing_run_date_returns_none(self):
        result = persist_screener_json_result({"passed_stocks": []}, source=_TEST_SOURCE)
        assert result is None


# ---------------------------------------------------------------------------
# scan_jobs lifecycle
# ---------------------------------------------------------------------------

@_skip_if_no_schema
class TestScanJobs:
    def test_full_job_lifecycle(self):
        job_id = create_scan_job(
            _TEST_SOURCE, "scripts/run_screener.py",
            ["--ibd-file", "test.xlsx"],
            "output/test.out.log", "output/test.err.log",
        )
        assert isinstance(job_id, int)

        client = get_supabase_client()

        # Verify initial state
        res = _tbl(client, "user_scan_jobs").select("status,pid,progress_message").eq("id", job_id).single().execute()
        assert res.data["status"] == "running"
        assert res.data["pid"] is None

        # Update PID
        update_scan_job_pid(job_id, 12345)
        res = _tbl(client, "user_scan_jobs").select("pid").eq("id", job_id).single().execute()
        assert res.data["pid"] == 12345

        # Update progress
        update_scan_job_progress(job_id, "Step 2/4: filtering")
        res = _tbl(client, "user_scan_jobs").select("progress_message").eq("id", job_id).single().execute()
        assert res.data["progress_message"] == "Step 2/4: filtering"

        # Finish successfully
        finish_scan_job(job_id, exit_code=0)
        res = _tbl(client, "user_scan_jobs").select("status,exit_code,finished_at").eq("id", job_id).single().execute()
        assert res.data["status"] == "completed"
        assert res.data["exit_code"] == 0
        assert res.data["finished_at"] is not None

    def test_failed_job(self):
        job_id = create_scan_job(
            _TEST_SOURCE, "scripts/run_screener.py", [],
            "output/test.out.log", "output/test.err.log",
        )
        finish_scan_job(job_id, exit_code=1, error_message="something went wrong")

        client = get_supabase_client()
        res = _tbl(client, "user_scan_jobs").select("status,error_message").eq("id", job_id).single().execute()
        assert res.data["status"] == "failed"
        assert res.data["error_message"] == "something went wrong"


# ---------------------------------------------------------------------------
# company_vectors
# ---------------------------------------------------------------------------

@_skip_if_no_schema
class TestCompanyVectors:
    _ticker = "PYTEST"
    _vdate = date(2025, 1, 15)
    _dims = {"momentum": 0.85, "quality": 0.72, "value": 0.40}
    _raw = {"eps_growth": 0.45, "roe": 0.22}
    _meta = {"name": "Pytest Corp", "sector": "Technology"}

    def test_upsert_and_load(self, client):
        upsert_company_vector(
            client,
            ticker=self._ticker,
            vector_date=self._vdate,
            dimensions=self._dims,
            raw=self._raw,
            metadata=self._meta,
            fetched_at=datetime(2025, 1, 15, 12, 0, tzinfo=timezone.utc),
        )
        rows = load_company_vectors(client, tickers=[self._ticker], vector_date=self._vdate)
        assert len(rows) == 1
        r = rows[0]
        assert r["ticker"] == self._ticker
        assert r["dimensions"] == self._dims
        assert r["raw"] == self._raw
        assert r["metadata"] == self._meta

    def test_upsert_overwrites_existing(self, client):
        new_dims = {"momentum": 0.99, "quality": 0.10, "value": 0.55}
        upsert_company_vector(
            client,
            ticker=self._ticker,
            vector_date=self._vdate,
            dimensions=new_dims,
            raw=self._raw,
            metadata=self._meta,
            fetched_at=datetime(2025, 1, 15, 18, 0, tzinfo=timezone.utc),
        )
        rows = load_company_vectors(client, tickers=[self._ticker], vector_date=self._vdate)
        assert len(rows) == 1
        assert rows[0]["dimensions"] == new_dims

    def test_load_latest_per_ticker(self, client):
        """load_company_vectors with no date returns latest row per ticker."""
        for d in [date(2025, 1, 10), date(2025, 1, 15), date(2025, 1, 20)]:
            upsert_company_vector(
                client, ticker=self._ticker, vector_date=d,
                dimensions={"momentum": 0.5}, raw={}, metadata={},
                fetched_at=datetime(2025, 1, 20, tzinfo=timezone.utc),
            )
        rows = load_company_vectors(client, tickers=[self._ticker])
        assert len(rows) == 1
        assert rows[0]["vector_date"] == date(2025, 1, 20)


# ---------------------------------------------------------------------------
# news_article_tickers
# ---------------------------------------------------------------------------

@_skip_if_no_schema
class TestArticleTickers:
    def test_save_and_replace(self, client):
        art_res = _tbl(client, "news_articles").insert({
            "body": "Test article body",
            "source": _TEST_SOURCE,
            "article_hash": "pytest_hash_001",
        }).execute()
        article_id = art_res.data[0]["id"]

        save_article_tickers(client, article_id, ["AAPL", "MSFT", "NVDA"], source="extracted")
        res = _tbl(client, "news_article_tickers").select("ticker").eq("article_id", article_id).execute()
        assert {r["ticker"] for r in res.data} == {"AAPL", "MSFT", "NVDA"}

        # Re-save with different tickers — should replace
        save_article_tickers(client, article_id, ["TSLA", "AMZN"], source="extracted")
        res = _tbl(client, "news_article_tickers").select("ticker").eq("article_id", article_id).execute()
        assert {r["ticker"] for r in res.data} == {"TSLA", "AMZN"}

    def test_save_empty_list_clears_tickers(self, client):
        art_res = _tbl(client, "news_articles").insert({
            "body": "Another test body",
            "source": _TEST_SOURCE,
            "article_hash": "pytest_hash_002",
        }).execute()
        article_id = art_res.data[0]["id"]

        save_article_tickers(client, article_id, ["AAPL"], source="extracted")
        save_article_tickers(client, article_id, [], source="extracted")

        res = _tbl(client, "news_article_tickers").select("ticker").eq("article_id", article_id).execute()
        assert res.data == []
