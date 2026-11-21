"""Offline tests for the drawdown snapshot parsers (no network, no DB)."""

from datetime import date

from services.drawdown.snapshots import parse_estimates, parse_fred_csv


def _rec(d, eps):
    return {"symbol": "NVDA", "date": d, "epsAvg": eps, "revenueAvg": 1.0, "numAnalystsEps": 10}


def test_estimates_keep_last_reported_and_three_forward_years():
    payload = [_rec(f"{y}-01-25", y) for y in range(2031, 2021, -1)]  # FMP order: farthest first
    rows = parse_estimates("NVDA", payload, date(2026, 11, 21))
    assert [r["fiscal_date"] for r in rows] == ["2026-01-25", "2027-01-25", "2028-01-25", "2029-01-25"]
    assert rows[0]["snapshot_date"] == "2026-11-21"
    assert rows[1]["eps_avg"] == 2027


def test_estimates_tolerate_garbage():
    assert parse_estimates("X", {"Error Message": "limit"}, date(2026, 11, 21)) == []
    assert parse_estimates("X", [{"date": "bad"}], date(2026, 11, 21)) == []


def test_fred_csv_skips_missing_and_old():
    text = "observation_date,DGS2\n2026-10-30,3.5\n2026-11-19,.\n2026-11-20,3.41\n"
    rows = parse_fred_csv("DGS2", text, date(2026, 11, 1))
    assert rows == [{"series_id": "FRED:DGS2", "obs_date": "2026-11-20", "value": 3.41, "source": "fred"}]


class _Resp:
    def __init__(self, body, code=200):
        self._b, self.status_code = body, code

    def json(self):
        return self._b


def test_error_body_counts_as_failure_not_success(monkeypatch):
    import services.drawdown.snapshots as s

    bodies = {"GOOD": [_rec("2027-01-25", 1.0)], "ERR": {"Error Message": "Limit Reach"}, "NONE": []}
    monkeypatch.setenv("FMP_API_KEY", "x")
    monkeypatch.setattr(s, "_get", lambda url, params, **k: _Resp(bodies[params["symbol"]]))
    rows, failed, empty = s.fetch_estimates(["GOOD", "ERR", "NONE"], date(2026, 11, 21), workers=1)
    assert {r["symbol"] for r in rows} == {"GOOD"}
    assert failed == ["ERR"]
    assert empty == ["NONE"]
