"""Point-in-time alignment — the quietest way a backtest lies."""

import json

import numpy as np
import pandas as pd

from strategylab.data.fundamentals import FundamentalsStore


_QUARTERS = [
    ("2019-03-31", "2019-05-15", 0.80, 800),
    ("2019-06-30", "2019-08-14", 0.85, 850),
    ("2019-09-30", "2019-11-13", 0.90, 900),
    ("2019-12-31", "2020-02-12", 0.95, 950),
    ("2020-03-31", "2020-05-15", 1.00, 1000),
    ("2020-06-30", "2020-08-14", 1.10, 1100),
    ("2020-09-30", "2020-11-13", 1.20, 1200),
    ("2020-12-31", "2021-02-12", 1.30, 1300),
    ("2021-03-31", "2021-05-14", 2.00, 2000),
]


def _payload():
    """Nine quarters, each filed ~45 days after the period it reports."""
    return {"income": [{"date": p, "fillingDate": f, "acceptedDate": f,
                        "epsdiluted": eps, "revenue": rev}
                       for p, f, eps, rev in _QUARTERS],
            "surprises": []}


def test_fundamentals_are_not_knowable_before_they_are_filed(tmp_path):
    fs = FundamentalsStore(tmp_path)
    fs._path("TEST").write_text(json.dumps(_payload()))

    s = fs.series("TEST")
    assert s is not None
    # The Q1-2021 figure reports the period ending 2021-03-31 but was filed on
    # 2021-05-14; knowledge_date must be the FILING date (plus settle), never
    # the period end. Joining on period end lets a backtest trade in April on
    # numbers published in May.
    last = s.iloc[-1]
    assert last["knowledge_date"] >= pd.Timestamp("2021-05-14")
    assert last["knowledge_date"] > pd.Timestamp("2021-03-31")


def test_alignment_forward_fills_only_after_the_filing(tmp_path):
    fs = FundamentalsStore(tmp_path)
    fs._path("TEST").write_text(json.dumps(_payload()))

    dates = pd.bdate_range("2021-04-01", "2021-06-30").values.astype("datetime64[D]")
    out = fs.align(["TEST"], dates)
    eps = out["eps_yoy"][:, 0]

    grid = pd.DatetimeIndex(dates)
    before = grid < pd.Timestamp("2021-05-14")
    after = grid > pd.Timestamp("2021-05-20")

    # Before the filing the value must be the PRIOR quarter's (or NaN), and it
    # must change only once the filing is public.
    pre_values = set(np.round(eps[before][np.isfinite(eps[before])], 6))
    post_values = set(np.round(eps[after][np.isfinite(eps[after])], 6))
    assert post_values, "no value after the filing date"
    assert not (pre_values & post_values) or len(pre_values) == 0


def test_growth_off_a_negative_base_is_not_reported_as_growth(tmp_path):
    fs = FundamentalsStore(tmp_path)
    payload = _payload()
    payload["income"][4]["epsdiluted"] = -1.0     # loss-making year-ago quarter
    fs._path("TEST").write_text(json.dumps(payload))
    s = fs.series("TEST")
    # -1.00 -> 2.00 is not "+300% growth"; it is undefined, and a gate that
    # reads it as spectacular growth would systematically buy turnarounds.
    assert not np.isfinite(s.iloc[-1]["eps_yoy"])


def test_deep_windows_do_not_silently_truncate(monkeypatch):
    """FMP's adjusted endpoint caps at 5000 rows and gives NO indication that it
    truncated — a request for 1995-2026 returns data starting in 2006, which
    reads as 'this symbol has no earlier history'. Nearly a decade of sample,
    including the GFC and the 2009 momentum crash, was being dropped in silence.
    """
    import numpy as np
    from strategylab.data.prices import PriceStore

    store = PriceStore()
    capped, deep = [], []

    def fake_adjusted(symbol, start, end):
        # Vendor behaviour: always exactly the cap, regardless of the request.
        d = pd.bdate_range("2006-08-14", periods=PriceStore.ADJUSTED_ROW_CAP)
        capped.append((start, end))
        return [{"date": str(x.date()), "adjOpen": 10.0, "adjHigh": 10.5,
                 "adjLow": 9.5, "adjClose": 10.0, "volume": 1e6} for x in d]

    def fake_raw(symbol, start, end):
        d = pd.bdate_range("1995-01-03", periods=7925)
        deep.append((start, end))
        return [{"date": str(x.date()), "open": 10.0, "high": 10.5, "low": 9.5,
                 "close": 10.0, "adjClose": 10.0, "volume": 1e6} for x in d]

    monkeypatch.setattr("strategylab.data.prices.fmp.eod_adjusted", fake_adjusted)
    monkeypatch.setattr("strategylab.data.prices.fmp.eod_raw", fake_raw)

    df = store.fetch("TEST", "1995-01-01", "2026-06-30")
    assert len(df) > PriceStore.ADJUSTED_ROW_CAP, "deep request came back truncated"
    assert df["date"].min().year == 1995
    assert deep, "the deep source was never consulted"

    capped.clear(); deep.clear()
    short = store.fetch("TEST", "2015-01-01", "2026-06-30")
    assert len(short) > 0
    assert capped, "a short window should still prefer the vendor-adjusted series"
