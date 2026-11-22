"""Offline tests for the narrative stress-test arithmetic."""

from datetime import date

import pytest

from services.drawdown.narrative import (breakeven_cut, consensus_cagr, dcf_value, faded_cagr,
                                         required_now, solve_growth)


def test_solve_inverts_dcf():
    ev = dcf_value(100.0, 0.2, 0.08, 0.09, 0.025)
    assert solve_growth(ev, 100.0, 0.2, 0.09, 0.025) == pytest.approx(0.08, abs=1e-6)
    assert solve_growth(ev, 100.0, -0.1, 0.09, 0.025) is None


def test_fade_is_flat_at_terminal_and_between_otherwise():
    assert faded_cagr(0.025, 0.025) == pytest.approx(0.025)
    g = faded_cagr(0.20, 0.025)
    assert 0.025 < g < 0.20


def test_breakeven_cut_zero_when_supported_equals_required():
    req = faded_cagr(0.15, 0.025)
    assert breakeven_cut(0.15, 0.025, req) == pytest.approx(0.0, abs=1e-6)
    assert breakeven_cut(0.15, 0.025, req - 0.02) > 0
    assert breakeven_cut(0.15, 0.025, req + 0.02) < 0


def test_lower_price_needs_less_growth():
    p = {"implied_revenue_cagr": 0.12, "fcf_margin": 0.25, "discount_rate": 0.09, "terminal_growth": 0.025, "price": 100.0}
    same, _ = required_now(p, 100.0, 1e9, 2e8)
    lower, _ = required_now(p, 70.0, 0.7e9, 2e8)
    assert same == pytest.approx(0.12, abs=1e-6)
    assert lower < 0.12


def test_consensus_uses_last_reported_to_farthest_of_three():
    rows = [{"fiscal_date": f"{y}-12-31", "revenue_avg": 100 * 1.1 ** (y - 2025)} for y in range(2025, 2031)]
    g, n = consensus_cagr(rows, date(2026, 11, 21))
    assert n == 3 and g == pytest.approx(0.10, abs=1e-6)


# --- earnings quality --------------------------------------------------------
from services.drawdown.quality import assess  # noqa: E402


def _st(years, filed="2026-03-01"):
    """years: list of (date, revenue, ni, cfo, capex, sbc, shares, assets, nonop, pretax), newest first."""
    cf, inc, bs = [], [], []
    for d, rev, ni, cfo, capex, sbc, sh, ta, nonop, pt in years:
        f = filed if d == years[0][0] else d
        cf.append({"date": d, "filingDate": f, "netIncome": ni, "operatingCashFlow": cfo, "capitalExpenditure": capex,
                   "freeCashFlow": cfo + capex, "stockBasedCompensation": sbc})
        inc.append({"date": d, "filingDate": f, "revenue": rev, "netIncome": ni, "weightedAverageShsOutDil": sh,
                    "nonOperatingIncomeExcludingInterest": nonop, "incomeBeforeTax": pt})
        bs.append({"date": d, "filingDate": f, "totalAssets": ta})
    return {"cf": cf, "inc": inc, "bs": bs}


CLEAN = [("2025-12-31", 100, 20, 25, -5, 2, 100, 200, 0, 25),
         ("2024-12-31", 90, 18, 22, -5, 2, 100, 190, 0, 22),
         ("2023-12-31", 80, 16, 20, -4, 2, 100, 180, 0, 20)]


def test_clean_company_has_no_flags_and_cash_margin():
    q = assess(_st(CLEAN), date(2026, 11, 21), consensus_margin=0.20)
    assert q["quality"] == "clean" and q["quality_flags"] == []
    assert q["cash_margin"] == pytest.approx((20 + 17 + 16) / 270)
    assert q["cfo_to_ni"] == pytest.approx(67 / 54)
    assert q["quality_margin"] == pytest.approx(0.20)  # conversion > 1 never raises the margin


def test_quality_margin_cuts_by_conversion_net_of_sbc():
    years = [("2025-12-31", 100, 20, 14, -30, 4, 100, 200, 0, 25),
             ("2024-12-31", 90, 20, 14, -30, 4, 100, 190, 0, 22),
             ("2023-12-31", 80, 20, 14, -30, 4, 100, 180, 0, 20)]
    q = assess(_st(years), date(2026, 11, 21), consensus_margin=0.20)
    assert q["cash_conversion"] == pytest.approx(30 / 60)
    assert q["quality_margin"] == pytest.approx(0.10)
    assert "negative free cash flow over 3 years" in q["quality_flags"]  # heavy capex is flagged, not solved under


def test_accrual_heavy_dilutive_company_is_weak():
    bad = [("2025-12-31", 100, 30, 5, -5, 15, 120, 150, 10, 32),
           ("2024-12-31", 90, 25, 5, -5, 14, 110, 140, 0, 27),
           ("2023-12-31", 80, 20, 5, -5, 12, 100, 130, 0, 22)]
    q = assess(_st(bad), date(2026, 11, 21), consensus_margin=0.30)
    assert q["quality"] == "weak"
    for f in ("profit not turning into cash", "high accruals", "heavy stock-based pay", "share count diluting",
              "negative free cash flow over 3 years"):
        assert f in q["quality_flags"]


def test_statement_filed_after_as_of_is_ignored():
    q = assess(_st(CLEAN, filed="2026-12-15"), date(2026, 11, 21))
    assert q["quality_years"] == 2  # the FY2025 row was not public yet


def test_missing_statements_are_unknown_not_clean():
    assert assess(None, date(2026, 11, 21))["quality"] == "unknown"
    assert assess({"cf": [], "inc": [], "bs": []}, date(2026, 11, 21))["quality"] == "unknown"


def test_clamped_solve_returns_bound():
    ev = dcf_value(100.0, 0.2, 0.08, 0.09, 0.025) * 50
    assert solve_growth(ev, 100.0, 0.2, 0.09, 0.025) is None
    assert solve_growth(ev, 100.0, 0.2, 0.09, 0.025, clamp=True) == 0.60


# --- model inputs (council round 3) --------------------------------------
from services.drawdown.narrative import cost_of_equity, midcycle_margin  # noqa: E402


def test_cost_of_equity_is_capm_clipped():
    assert cost_of_equity(0.05, 1.0) == pytest.approx(0.095)
    assert cost_of_equity(0.05, 0.2) == 0.06      # floor: a staple is not discounted at 5.9%
    assert cost_of_equity(0.05, 3.4) == 0.11      # cap
    assert cost_of_equity(None, None) == pytest.approx(0.045 + 0.045)


def test_midcycle_only_for_cyclicals_running_above_history():
    semi = {"sector": "Technology", "industry": "Semiconductors"}
    assert midcycle_margin(semi, 0.60, 0.20) == pytest.approx(0.40)
    assert midcycle_margin(semi, 0.22, 0.20) is None            # within 25% of history
    assert midcycle_margin({"sector": "Technology", "industry": "Software - Infrastructure"}, 0.60, 0.20) is None
    assert midcycle_margin({"sector": "Energy", "industry": "Oil & Gas E&P"}, 0.30, None) is None


# --- agent review + picks: the deterministic guards around the agents -------
from services.drawdown.judge import _implied_group, _paths  # noqa: E402
from services.drawdown.picks import _hold, validate  # noqa: E402


def test_implied_group_follows_the_agents_own_numbers():
    w = lambda be, lo, cut: {"breakeven_cut": be, "breakeven_cut_1pt_lower_r": lo, "cut": cut}  # noqa: E731
    assert _implied_group(w(0.20, 0.24, 0.15)) == {"on_top", "holds"}
    assert _implied_group(w(0.05, 0.08, 0.15)) == {"fragile", "holds"}
    assert _implied_group(w(0.01, 0.04, 0.15)) == {"fragile"}
    assert _implied_group(w(-0.05, 0.01, 0.15)) == {"fragile"}  # short only at its own rate
    assert _implied_group(w(-0.05, -0.02, 0.15)) == {"drowns"}


def test_paths_resolve_from_any_batch_file():
    for f in ("b/batch_03.json", "b/batch_03.reveal.json", "b/batch_03.news.json", "b/batch_03.verdict.input.json"):
        assert _paths(f)["draft"] == "b/batch_03.draft.json"


def _pick(t, sector="Technology", side="long", beta=1.0, size=10):
    p = {"ticker": t, "sector": sector, "thesis": "x", "evidence": ["y"], "catalyst": "c", "invalidation": "i",
         "risk": "r", "conviction": 2, "entry": {"type": "next_open"}, "stop": {"price": 10.0, "basis": "b"},
         "target": {"price": 20.0}, "size_pct": size, "earnings_date": "2027-02-01", "pre_earnings_action": "halve",
         "beta": beta}
    if side == "short":
        p.update(short_interest_pct_float=4.0, days_to_cover=2.0)
    return p


SECTORS = ["A", "A", "A", "B", "B", "B", "C", "C", "C", "D"]


def _book(lb=1.0, sb=1.0):
    return {"long": [_pick(f"L{i}", s, beta=lb) for i, s in enumerate(SECTORS)],
            "short": [_pick(f"S{i}", s, "short", beta=sb) for i, s in enumerate(SECTORS)]}


def test_validate_accepts_a_balanced_book():
    assert validate(_book()) == []


def test_validate_accepts_a_small_book_but_not_a_single_name():
    b = _book()
    b["long"], b["short"] = b["long"][:4], b["short"][:4]
    assert validate(b) == []
    b["short"] = b["short"][:1]
    assert "need 2-10" in " | ".join(validate(b))


def test_validate_rejects_concentration_and_overlap():
    bad = _book()
    bad["long"][9] = _pick("S0", "D")
    bad["short"] = [_pick(f"S{i}", "A", "short") for i in range(10)]
    errs = " | ".join(validate(bad))
    assert "on both sides: S0" in errs and "10 picks in A" in errs


def test_validate_rejects_a_factor_bet_and_squeezes():
    errs = " | ".join(validate(_book(lb=1.5, sb=0.7)))   # 150 - 70 = +80% of NAV net beta
    assert "beta-weighted net" in errs
    b = _book()
    b["short"][0]["short_interest_pct_float"] = 30
    b["short"][1]["days_to_cover"] = None
    errs = " | ".join(validate(b))
    assert "squeeze risk" in errs and "days_to_cover are required" in errs


def test_hold_enters_next_open_and_honours_stop():
    from datetime import datetime
    bars = [{"date": "2026-11-20", "open": 100, "close": 100}, {"date": "2026-11-23", "open": 101, "close": 95},
            {"date": "2026-11-24", "open": 95, "close": 88}, {"date": "2026-11-25", "open": 88, "close": 120}]
    sealed = datetime(2026, 11, 21, 22, 0)
    h = _hold(bars, sealed, "long", 90.0, 63)
    assert h["entry"] == 101 and h["status"] == "stopped" and h["exit"] == 88
    h = _hold(bars, sealed, "short", 125.0, 2)
    assert h["status"] == "horizon" and h["exit"] == 88


def test_limit_entry_fills_only_on_touch_and_expires():
    from datetime import datetime
    bars = [{"date": "2026-11-23", "open": 150, "high": 160, "low": 148, "close": 155},
            {"date": "2026-11-24", "open": 170, "high": 182, "low": 168, "close": 180},
            {"date": "2026-11-25", "open": 180, "high": 181, "low": 150, "close": 152}]
    sealed = datetime(2026, 11, 21, 22, 0)
    h = _hold(bars, sealed, "short", 218.0, 63, {"type": "limit", "level": 178, "expires": "2026-12-04"})
    assert h["entry"] == 178 and h["entry_date"] == "2026-11-24" and h["exit"] == 152
    h = _hold(bars, sealed, "short", 218.0, 63, {"type": "limit", "level": 190, "expires": "2026-12-04"})
    assert h["status"] == "not_filled"
    h = _hold(bars, sealed, "short", 218.0, 63, {"type": "limit", "level": 178, "expires": "2026-11-23"})
    assert h["status"] == "not_filled"


def test_equity_basis_values_net_margin_against_market_cap():
    from services.drawdown.narrative import dcf_value, required_now
    p = {"implied_revenue_cagr": 0.05, "fcf_margin": 0.10, "discount_rate": 0.09, "terminal_growth": 0.025, "price": 100}
    g, method = required_now(p, 80, 40e9, 10e9, 0.12, solve_r=0.09, method="equity")
    assert method == "equity"
    assert abs(dcf_value(10e9, 0.12, g, 0.09, 0.025) / 40e9 - 1) < 1e-3
    # the stored model's EV (and so its made-up net debt) no longer enters
    g2, _ = required_now({**p, "implied_revenue_cagr": 0.30}, 80, 40e9, 10e9, 0.12, solve_r=0.09, method="equity")
    assert abs(g - g2) < 1e-9
    # legacy basis still re-solves an older sealed solve dict
    _, m = required_now(p, 80, 40e9, 10e9, 0.12, solve_r=0.09, method="net_debt_fixed")
    assert m in ("net_debt_fixed", "ev_scaled")


def test_events_gate():
    from datetime import date
    from services.drawdown.events import check
    ev = {"splits": {"MNST": [{"date": "2026-08-11", "numerator": 2, "denominator": 1}]},
          "mna_targets": {"UTZ": {"companyName": "Buyer", "transactionDate": "2026-10-01", "acquirer_mcap": 9e9, "target_mcap": 2e9},
                          "MDT": {"companyName": "MiniMed", "transactionDate": "2026-09-14", "acquirer_mcap": None, "target_mcap": 1e11}},
          "mna_buyers": {"FOXA": {"targetedCompanyName": "Roku", "transactionDate": "2026-09-01"}}}
    kw = dict(upside=0.1, rev_fy1=None, rev_last=None, g3=0.05, share_step=None)
    assert check("MNST", ev, "2026-09-02", date(2026, 11, 21), **kw)[0]["action"] == "refuse"
    assert check("MNST", ev, "2027-06-01", date(2027, 6, 2), **kw) == []          # split outside the window
    assert check("UTZ", ev, "2026-09-02", date(2026, 11, 21), **kw)[0]["action"] == "not_cash_flow"
    assert check("MDT", ev, "2026-09-02", date(2026, 11, 21), **kw)[0]["kind"] == "mna_spin"
    ev["splits"]["HON"] = [{"date": "2026-06-29", "numerator": 1907, "denominator": 2000}]
    assert check("HON", ev, "2026-09-02", date(2026, 11, 21), **kw)[0]["kind"] == "adjustment"
    assert check("FOXA", ev, "2026-09-02", date(2026, 11, 21), **kw)[0]["action"] == "bar_top"
    per = check("HON", {}, "2026-09-02", date(2026, 11, 21), upside=0.1, rev_fy1=26e9, rev_last=40e9, g3=0.04, share_step=0.15)
    assert {e["kind"] for e in per} == {"perimeter", "share_step"}
    assert check("X", {}, "2026-09-02", date(2026, 11, 21), upside=1.2, rev_fy1=None, rev_last=None, g3=0.3,
                 share_step=None)[0]["kind"] == "stale_targets"


def test_stratified_control_is_proportional_and_seeded():
    import random
    from services.drawdown.picks import _stratified
    rows = [{"ticker": f"T{i}", "sector": "A" if i < 60 else "B"} for i in range(100)]
    a = _stratified(rows, 10, random.Random("seal:long"))
    b = _stratified(rows, 10, random.Random("seal:long"))
    assert a == b and len(a) == 10
    assert sum(r["sector"] == "A" for r in a) == 6


def test_notify_email_is_public_only_and_has_unsubscribe(monkeypatch):
    monkeypatch.setenv("UNSUBSCRIBE_SECRET", "test")
    from services.drawdown.notify import render
    run = {"as_of": "2026-11-23", "universe": 627, "groups": {"on_top": 14, "holds": 104, "fragile": 98, "drowns": 222}}
    prev = {"as_of": "2026-11-21", "groups": {"on_top": 10, "holds": 100, "fragile": 98, "drowns": 230}}
    subject, html, text = render(run, prev, "a@b.co")
    assert "2026-11-23" in subject and "/api/correction/unsubscribe?token=" in html
    assert "+4 since 2026-11-21" in text and "-8 since 2026-11-21" in text
    assert "declines" not in html.lower()
