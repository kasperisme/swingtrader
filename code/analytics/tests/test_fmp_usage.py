"""The FMP usage tally: endpoint naming matches the FMP dashboard, and real
requests/httpx calls land in the log attributed to this file."""

import asyncio
import json

import httpx
import pytest
import requests

from shared import fmp_usage


@pytest.mark.parametrize("url, expected", [
    ("https://financialmodelingprep.com/api/v3/historical-price-full/AAPL?from=2026-01-01", "/v3/historical-price-full"),
    ("https://financialmodelingprep.com/api/v3/quote/AAPL,MSFT,BRK-B", "/v3/quote"),
    ("https://financialmodelingprep.com/api/v3/quote/^VIX", "/v3/quote"),
    ("https://financialmodelingprep.com/stable/quote?symbol=AAPL", "/stable/quote"),
    ("https://financialmodelingprep.com/api/v3/historical/earning_calendar/NVDA", "/v3/historical/earning_calendar"),
    ("https://financialmodelingprep.com/api/v3/historical-price-full/stock_split/AAPL", "/v3/historical-price-full/stock_split"),
    ("https://financialmodelingprep.com/api/v3/technical_indicator/1day/AAPL?type=sma", "/v3/technical_indicator/1day"),
    ("https://financialmodelingprep.com/stable/historical-chart/1hour?symbol=AAPL", "/stable/historical-chart/1hour"),
    ("https://financialmodelingprep.com/api/v4/company-outlook?symbol=AAPL", "/v4/company-outlook"),
    ("https://financialmodelingprep.com/api/v3/sectors-list", "/v3/sectors-list"),
])
def test_endpoint_matches_dashboard_naming(url, expected):
    assert fmp_usage.endpoint_of(url) == expected


def test_mcp_tool_calls_are_named():
    body = json.dumps({"jsonrpc": "2.0", "method": "tools/call",
                       "params": {"name": "quote", "arguments": {"endpoint": "quote", "symbol": "AAPL"}}})
    assert fmp_usage.endpoint_of("https://financialmodelingprep.com/mcp?apikey=x", body) == "/mcp[quote:quote]"
    init = json.dumps({"jsonrpc": "2.0", "method": "initialize"})
    assert fmp_usage.endpoint_of("https://financialmodelingprep.com/mcp", init) == "/mcp[initialize]"


class _FakeAdapter(requests.adapters.BaseAdapter):
    def send(self, request, **kwargs):
        r = requests.Response()
        r.status_code = 200 if "quote" in request.url else 402
        r._content = b"[]"
        r.url, r.request = request.url, request
        return r

    def close(self):
        pass


@pytest.fixture
def tally(tmp_path, monkeypatch):
    monkeypatch.setenv("FMP_USAGE_DIR", str(tmp_path))
    monkeypatch.setenv("FMP_USAGE_JOB", "test-job")
    fmp_usage.install(force=True)
    yield tmp_path
    fmp_usage.uninstall()


def _rows(directory):
    fmp_usage.flush()
    return fmp_usage.load(1, directory)


def test_requests_calls_are_tallied_with_caller(tally):
    s = requests.Session()
    s.mount("https://financialmodelingprep.com", _FakeAdapter())
    for _ in range(3):
        s.get("https://financialmodelingprep.com/stable/quote", params={"symbol": "AAPL"})
    s.get("https://financialmodelingprep.com/api/v3/historical-price-full/AAPL")

    by_ep = {r["endpoint"]: r for r in _rows(tally)}
    assert by_ep["/stable/quote"]["n"] == 3
    assert by_ep["/stable/quote"]["bytes"] == 3 * len(b"[]")
    assert by_ep["/stable/quote"]["status"] == "2xx"
    assert by_ep["/v3/historical-price-full"]["status"] == "4xx"
    assert by_ep["/stable/quote"]["job"] == "test-job"
    assert "tests/test_fmp_usage.py:test_requests_calls_are_tallied_with_caller" in by_ep["/stable/quote"]["caller"]


def test_non_fmp_hosts_are_ignored(tally):
    s = requests.Session()
    s.mount("https://example.com", _FakeAdapter())
    s.get("https://example.com/stable/quote")
    assert _rows(tally) == []


def test_httpx_sync_and_async_are_tallied(tally):
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=[]))
    with httpx.Client(transport=transport) as c:
        c.get("https://financialmodelingprep.com/stable/profile", params={"symbol": "AAPL"})

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, json=[]))) as c:
            await c.get("https://financialmodelingprep.com/stable/news/stock-latest")

    asyncio.run(go())
    rows = _rows(tally)
    assert {r["endpoint"] for r in rows} == {"/stable/profile", "/stable/news/stock-latest"}
    assert all(r["bytes"] == len(b"[]") for r in rows)


def test_install_is_idempotent(tally):
    fmp_usage.install(force=True)
    s = requests.Session()
    s.mount("https://financialmodelingprep.com", _FakeAdapter())
    s.get("https://financialmodelingprep.com/stable/quote")
    assert sum(r["n"] for r in _rows(tally)) == 1


def test_report_groups_by_endpoint_and_job(tally):
    s = requests.Session()
    s.mount("https://financialmodelingprep.com", _FakeAdapter())
    s.get("https://financialmodelingprep.com/stable/quote")
    fmp_usage.flush()
    assert "/stable/quote" in fmp_usage.report(1, "endpoint", directory=tally)
    assert "test-job" in fmp_usage.report(1, "job", directory=tally)
