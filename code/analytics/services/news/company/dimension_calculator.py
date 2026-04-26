"""
Dimension calculator — converts RawCompanyData into a flat dict of raw
(un-normalised) dimension values.

Returns float | None per key.  None means data was insufficient; the
normaliser will assign 0.5 in the final ranked vector.

A module-level set tracks which dimension keys have already emitted a
"missing data" warning so each key warns at most once per process run.
"""

import logging
import statistics
from typing import Optional

from services.news.company.fmp_fetcher import RawCompanyData

logger = logging.getLogger(__name__)

# Warn once per dimension key across the whole run, not per ticker
_warned: set[str] = set()


def _warn_once(key: str, msg: str) -> None:
    if key not in _warned:
        logger.warning("[DimensionCalculator] %s: %s", key, msg)
        _warned.add(key)


# ---------------------------------------------------------------------------
# Sector / industry mapping helpers
# ---------------------------------------------------------------------------

# FMP returns various sector string variants; map them to our dimension keys
_SECTOR_TO_KEY: dict[str, str] = {
    "financial services": "sector_financials",
    "financials":         "sector_financials",
    "technology":         "sector_technology",
    "information technology": "sector_technology",
    "healthcare":         "sector_healthcare",
    "health care":        "sector_healthcare",
    "energy":             "sector_energy",
    "real estate":        "sector_realestate",
    "consumer cyclical":  "sector_consumer",
    "consumer defensive": "sector_consumer",
    "consumer discretionary": "sector_consumer",
    "consumer staples":   "sector_consumer",
    "industrials":        "sector_industrials",
    "utilities":          "sector_utilities",
}

# Commodity input exposure by sector (proxy)
_COMMODITY_BY_SECTOR: dict[str, float] = {
    "basic materials":    0.9,
    "materials":          0.9,
    "energy":             0.8,
    "industrials":        0.6,
    "consumer staples":   0.5,
    "consumer defensive": 0.5,
}

# Emerging market country codes (ISO 2-letter, non-exhaustive)
_EM_COUNTRIES = {
    "CN", "IN", "BR", "RU", "MX", "ZA", "TH", "ID", "MY", "PH",
    "TR", "EG", "AR", "CL", "CO", "PK", "BD", "VN", "NG", "KE",
    "PE", "CZ", "HU", "PL", "RO", "QA", "AE", "SA", "KW", "BH",
    "GR", "TW", "KR", "HK",
}


def _safe_div(num: Optional[float], den: Optional[float]) -> Optional[float]:
    """Return num/den or None if either is missing / zero denominator."""
    if num is None or den is None:
        return None
    try:
        if den == 0:
            return None
        return num / den
    except (TypeError, ZeroDivisionError):
        return None


def _get(d: dict, *keys: str) -> Optional[float]:
    """
    Walk nested dicts by key chain.  Returns None if any key is missing
    or the final value is not numeric.
    """
    val = d
    for k in keys:
        if not isinstance(val, dict):
            return None
        val = val.get(k)
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _compute_institutional_pct(
    inst: list[dict],
    income: list[dict],
) -> Optional[float]:
    """
    Aggregate institutional ownership % from v3 institutional-holder records.
    Sums shares for the most recent reporting date and divides by weightedAverageShsOut.
    Returns None if either input is insufficient.
    """
    if not inst or not income:
        return None
    shares_out = _get(income[0], "weightedAverageShsOut")
    if not shares_out or shares_out <= 0:
        return None
    # Group by reportedDate and take the most recent batch
    most_recent_date = inst[0].get("dateReported")
    total_inst_shares = sum(
        float(h.get("shares") or 0)
        for h in inst
        if h.get("dateReported") == most_recent_date
    )
    return min(total_inst_shares / shares_out, 1.0)


class DimensionCalculator:
    """
    Computes raw (un-normalised) dimension values from RawCompanyData.

    raw_values = DimensionCalculator().calculate(raw)
    """

    def calculate(self, raw: RawCompanyData) -> dict[str, Optional[float]]:
        results: dict[str, Optional[float]] = {}

        # Convenience references
        income      = raw.income       # list newest-first
        balance     = raw.balance
        cashflow    = raw.cashflow
        metrics     = raw.metrics
        ratios      = raw.ratios
        quote       = raw.quote
        profile     = raw.profile
        inst        = raw.institutional
        estimates   = raw.estimates

        sector   = (profile.get("sector")   or "").lower().strip()
        industry = (profile.get("industry") or "").lower().strip()
        country  = (profile.get("country")  or "").upper().strip()

        # ------------------------------------------------------------------
        # MACRO_SENSITIVITY
        # ------------------------------------------------------------------

        # interest_rate_sensitivity — P/E as duration proxy; high P/E = long duration
        # key-metrics uses peRatio not present; ratios uses priceToEarningsRatio
        pe = (
            _get(ratios, "priceToEarningsRatio")
            or _get(metrics, "peRatio")
            or _get(quote, "pe")
        )
        results["interest_rate_sensitivity"] = pe
        if pe is None:
            _warn_once("interest_rate_sensitivity", "P/E not available; will be None")

        # dollar_sensitivity — 1 - (domestic / total) proxy via country
        if income:
            # FMP doesn't expose geographic revenue breakdown in stable endpoints,
            # so we use country as a proxy:
            #   US headquartered → ~0.3 international exposure
            #   Non-US           → ~0.7 international exposure
            if country in ("US", "USA", ""):
                results["dollar_sensitivity"] = 0.3
            else:
                results["dollar_sensitivity"] = 0.7
        else:
            results["dollar_sensitivity"] = None

        # inflation_sensitivity — 1 - gross_margin
        # income-statement has grossProfit + revenue but not grossProfitRatio
        gm = None
        if income:
            gp  = _get(income[0], "grossProfit")
            rev = _get(income[0], "revenue")
            gm  = _safe_div(gp, rev)
        if gm is None:
            # ratios uses grossProfitMargin (confirmed field name)
            gm = _get(ratios, "grossProfitMargin")
        results["inflation_sensitivity"] = (1.0 - gm) if gm is not None else None
        if gm is None:
            _warn_once("inflation_sensitivity", "gross margin not available")

        # credit_spread_sensitivity — total_debt / EBITDA (same calc as debt_burden)
        net_debt_ebitda = _get(metrics, "netDebtToEBITDA")
        results["credit_spread_sensitivity"] = net_debt_ebitda
        if net_debt_ebitda is None:
            _warn_once("credit_spread_sensitivity", "netDebtToEBITDA not in key-metrics")

        # commodity_input_exposure — sector proxy
        results["commodity_input_exposure"] = _COMMODITY_BY_SECTOR.get(sector, 0.2)

        # energy_cost_intensity — industry proxy
        high_energy = ("airline", "shipping", "chemical", "cement", "steel",
                       "aluminum", "paper", "mining", "rail", "trucking")
        results["energy_cost_intensity"] = (
            0.8 if any(h in industry for h in high_energy) else
            0.5 if sector in ("energy", "industrials", "materials", "basic materials") else
            0.2
        )

        # ------------------------------------------------------------------
        # SECTOR_ROTATION — one-hot
        # ------------------------------------------------------------------
        matched_sector_key = _SECTOR_TO_KEY.get(sector)
        all_sector_keys = [
            "sector_financials", "sector_technology", "sector_healthcare",
            "sector_energy", "sector_realestate", "sector_consumer",
            "sector_industrials", "sector_utilities",
        ]
        for sk in all_sector_keys:
            results[sk] = 1.0 if sk == matched_sector_key else 0.0

        # ------------------------------------------------------------------
        # BUSINESS_MODEL
        # ------------------------------------------------------------------

        # revenue_recurring — sector / industry proxy
        if "software" in industry or "saas" in industry:
            results["revenue_recurring"] = 0.8
        elif sector in ("utilities",):
            results["revenue_recurring"] = 0.9
        elif sector in ("healthcare", "health care"):
            results["revenue_recurring"] = 0.6
        elif sector in ("technology", "information technology"):
            results["revenue_recurring"] = 0.5
        else:
            results["revenue_recurring"] = 0.2

        # revenue_transactional — industry proxy
        trans_keywords = ("payment", "advertising", "ad tech", "marketplace", "exchange")
        results["revenue_transactional"] = (
            0.8 if any(k in industry for k in trans_keywords) else 0.2
        )

        # revenue_cyclical — sector proxy
        cyclical_sectors = ("industrials", "basic materials", "materials", "energy")
        results["revenue_cyclical"] = 0.8 if sector in cyclical_sectors else 0.2

        # pricing_power — gross margin stdev (lower stdev → higher power → return 1-stdev)
        # income-statement has grossProfit + revenue; compute ratio per period
        if len(income) >= 2:
            gms = []
            for p in income[:4]:
                gp_  = _get(p, "grossProfit")
                rev_ = _get(p, "revenue")
                gm_  = _safe_div(gp_, rev_)
                if gm_ is not None:
                    gms.append(gm_)
            gms = [v for v in gms if v is not None]
            if len(gms) >= 2:
                stdev = statistics.stdev(gms)
                results["pricing_power"] = max(0.0, 1.0 - stdev)
            else:
                results["pricing_power"] = None
                _warn_once("pricing_power", "insufficient gross margin history")
        else:
            results["pricing_power"] = None
            _warn_once("pricing_power", "fewer than 2 income periods")

        # capex_intensity — capex / revenue
        if cashflow and income:
            capex   = _get(cashflow[0], "capitalExpenditure")
            revenue = _get(income[0], "revenue")
            # FMP returns capex as negative; take abs
            if capex is not None:
                capex = abs(capex)
            results["capex_intensity"] = _safe_div(capex, revenue)
        else:
            results["capex_intensity"] = None
            _warn_once("capex_intensity", "missing cashflow or income data")

        # ------------------------------------------------------------------
        # FINANCIAL_STRUCTURE
        # ------------------------------------------------------------------

        # debt_burden — total debt / EBITDA via netDebtToEBITDA proxy
        # Prefer computing directly if we have the raw fields
        total_debt = _get(balance[0], "totalDebt") if balance else None
        if total_debt is None and balance:
            ltd = _get(balance[0], "longTermDebt") or 0.0
            std = _get(balance[0], "shortTermDebt") or 0.0
            total_debt = ltd + std if (ltd or std) else None

        # EBITDA = operating income + D&A
        op_income = _get(income[0], "operatingIncome") if income else None
        da = None
        if cashflow:
            da = _get(cashflow[0], "depreciationAndAmortization")
        if da is None and income:
            da = _get(income[0], "depreciationAndAmortization")
        ebitda = (op_income + (da or 0.0)) if op_income is not None else None

        debt_ebitda = _safe_div(total_debt, ebitda)
        if debt_ebitda is None:
            debt_ebitda = _get(metrics, "netDebtToEBITDA")
        results["debt_burden"] = debt_ebitda
        if debt_ebitda is None:
            _warn_once("debt_burden", "cannot compute total_debt/EBITDA")

        # floating_rate_debt_ratio — short-term debt / total debt (proxy)
        std_val = _get(balance[0], "shortTermDebt") if balance else None
        results["floating_rate_debt_ratio"] = _safe_div(std_val, total_debt)
        if results["floating_rate_debt_ratio"] is None:
            _warn_once("floating_rate_debt_ratio", "shortTermDebt or totalDebt missing")

        # debt_maturity_nearterm — same proxy as floating_rate_debt_ratio
        # (note: true near-term maturity schedule not available in FMP stable)
        results["debt_maturity_nearterm"] = results["floating_rate_debt_ratio"]

        # financial_health — composite: min(cr/5,1)*0.5 + min(ic/20,1)*0.5
        # ratios field: currentRatio, interestCoverageRatio (not interestCoverage)
        cr = _get(metrics, "currentRatio") or _get(ratios, "currentRatio")
        ic = _get(ratios, "interestCoverageRatio") or _get(ratios, "debtServiceCoverageRatio")
        if cr is not None and ic is not None:
            cr_norm = min(cr / 5.0, 1.0)
            ic_norm = min(ic / 20.0, 1.0)
            results["financial_health"] = cr_norm * 0.5 + ic_norm * 0.5
        elif cr is not None:
            results["financial_health"] = min(cr / 5.0, 1.0) * 0.5
        else:
            results["financial_health"] = None
            _warn_once("financial_health", "currentRatio and interestCoverage both missing")

        # earnings_quality — FCF / net income
        if cashflow and income:
            fcf       = _get(cashflow[0], "freeCashFlow")
            net_inc   = _get(income[0], "netIncome") or _get(cashflow[0], "netIncome")
            results["earnings_quality"] = _safe_div(fcf, net_inc)
        else:
            results["earnings_quality"] = None
            _warn_once("earnings_quality", "missing cashflow or income data")

        # buyback_capacity — (cash - short_term_debt) / market_cap
        cash   = _get(balance[0], "cashAndCashEquivalents") if balance else None
        mktcap = _get(quote, "marketCap") or _get(metrics, "marketCap")
        if cash is not None and std_val is not None and mktcap and mktcap > 0:
            results["buyback_capacity"] = (cash - std_val) / mktcap
        else:
            results["buyback_capacity"] = None
            _warn_once("buyback_capacity", "cash, shortTermDebt or marketCap missing")

        # ------------------------------------------------------------------
        # GROWTH_PROFILE
        # ------------------------------------------------------------------

        # revenue_growth_rate — sequential (index 0 vs index 1)
        if len(income) >= 2:
            rev0 = _get(income[0], "revenue")
            rev1 = _get(income[1], "revenue")
            results["revenue_growth_rate"] = _safe_div(
                (rev0 - rev1) if (rev0 is not None and rev1 is not None) else None,
                rev1,
            )
        else:
            results["revenue_growth_rate"] = None
            _warn_once("revenue_growth_rate", "fewer than 2 income periods")

        # eps_growth_rate — sequential EPS
        eps0 = _get(income[0], "eps") if income else None
        eps1 = _get(income[1], "eps") if len(income) >= 2 else None
        if eps0 is not None and eps1 is not None and eps1 != 0:
            results["eps_growth_rate"] = (eps0 - eps1) / abs(eps1)
        else:
            results["eps_growth_rate"] = None
            _warn_once("eps_growth_rate", "insufficient EPS data")

        # eps_acceleration — change in eps_growth_rate QoQ
        eps2 = _get(income[2], "eps") if len(income) >= 3 else None
        if eps1 is not None and eps2 is not None and eps2 != 0 and eps1 != 0:
            growth_q0 = (eps0 - eps1) / abs(eps1) if eps0 is not None else None
            growth_q1 = (eps1 - eps2) / abs(eps2)
            results["eps_acceleration"] = (
                (growth_q0 - growth_q1) if growth_q0 is not None else None
            )
        else:
            results["eps_acceleration"] = None
            _warn_once("eps_acceleration", "insufficient EPS history for acceleration")

        # forward_growth_expectations — (forward_eps - trailing_eps) / abs(trailing_eps)
        # analyst-estimates field is epsAvg (not estimatedEpsAvg)
        fwd_eps = _get(estimates, "epsAvg")
        trailing_eps = eps0
        if fwd_eps is not None and trailing_eps is not None and trailing_eps != 0:
            results["forward_growth_expectations"] = (fwd_eps - trailing_eps) / abs(trailing_eps)
        else:
            results["forward_growth_expectations"] = None
            _warn_once("forward_growth_expectations", "estimatedEpsAvg or trailing EPS missing")

        # earnings_revision_trend — (estimatedEpsAvg - last_actual_eps) / abs(last_actual_eps)
        # Same formula as forward_growth_expectations with current data
        results["earnings_revision_trend"] = results["forward_growth_expectations"]

        # ------------------------------------------------------------------
        # VALUATION_POSITIONING
        # ------------------------------------------------------------------

        # valuation_multiple — EV/EBITDA preferred, P/E fallback
        # key-metrics field is evToEBITDA (confirmed); ratios has enterpriseValueMultiple
        ev_ebitda = _get(metrics, "evToEBITDA")
        if ev_ebitda is None:
            ev_ebitda = _get(ratios, "enterpriseValueMultiple")
        if ev_ebitda is None:
            ev_ebitda = pe  # P/E already computed above
        results["valuation_multiple"] = ev_ebitda
        if ev_ebitda is None:
            _warn_once("valuation_multiple", "EV/EBITDA and P/E both unavailable")

        # factor_value — inverse of valuation multiple
        results["factor_value"] = (1.0 / ev_ebitda) if ev_ebitda and ev_ebitda > 0 else None

        # short_interest_ratio — not available in FMP stable endpoints
        results["short_interest_ratio"] = None
        _warn_once("short_interest_ratio", "not available in FMP stable; returning None")

        # crowded_long_risk — institutional ownership % as proxy
        # v3 institutional-holder gives per-holder share counts, not aggregate %.
        # Compute: sum(shares from most-recent date) / sharesOutstanding
        inst_pct = _compute_institutional_pct(inst, income)
        results["crowded_long_risk"] = inst_pct
        if inst_pct is None:
            _warn_once("crowded_long_risk", "cannot compute institutional ownership %")

        # price_momentum — price / yearHigh
        price    = _get(quote, "price")
        year_high = _get(quote, "yearHigh")
        results["price_momentum"] = _safe_div(price, year_high)
        if results["price_momentum"] is None:
            _warn_once("price_momentum", "price or yearHigh missing from quote")

        # ------------------------------------------------------------------
        # GEOGRAPHY_TRADE
        # ------------------------------------------------------------------

        # china_revenue_exposure — country / description proxy
        description = (profile.get("description") or "").lower()
        if country == "CN":
            results["china_revenue_exposure"] = 0.9
        elif "china" in description or "chinese" in description:
            results["china_revenue_exposure"] = 0.5
        else:
            results["china_revenue_exposure"] = 0.05

        # emerging_market_exposure — country in EM list
        results["emerging_market_exposure"] = 0.8 if country in _EM_COUNTRIES else 0.1

        # domestic_revenue_concentration — inverse of dollar_sensitivity
        ds = results.get("dollar_sensitivity")
        results["domestic_revenue_concentration"] = (1.0 - ds) if ds is not None else None

        # tariff_sensitivity — composite of sector + international exposure
        high_tariff_sector = sector in ("industrials", "basic materials", "materials",
                                        "consumer cyclical", "consumer discretionary")
        int_exposure = results.get("dollar_sensitivity") or 0.3
        results["tariff_sensitivity"] = (
            min(1.0, int_exposure * 1.5) if high_tariff_sector else int_exposure * 0.5
        )

        # ------------------------------------------------------------------
        # MARKET_BEHAVIOUR
        # ------------------------------------------------------------------

        # institutional_appeal — current institutional ownership %
        results["institutional_appeal"] = inst_pct

        # institutional_ownership_change — estimate change via net share changes
        # v3 holder records include a 'change' field (shares added/removed per holder)
        if inst:
            shares_out = _get(income[0], "weightedAverageShsOut") if income else None
            if shares_out and shares_out > 0:
                net_change = sum(
                    float(h.get("change") or 0) for h in inst
                    if h.get("dateReported") == inst[0].get("dateReported")
                )
                results["institutional_ownership_change"] = net_change / shares_out
            else:
                results["institutional_ownership_change"] = None
                _warn_once("institutional_ownership_change", "sharesOutstanding unavailable for change calc")
        else:
            results["institutional_ownership_change"] = None
            _warn_once("institutional_ownership_change", "no institutional holder data")

        # retail_sentiment_exposure — requires options data; not available
        results["retail_sentiment_exposure"] = None
        _warn_once("retail_sentiment_exposure", "requires options data; returning None")

        # options_implied_volatility — requires options data; not available
        results["options_implied_volatility"] = None
        _warn_once("options_implied_volatility", "requires options data; returning None")

        return results


if __name__ == "__main__":
    import asyncio
    import pathlib
    from dotenv import load_dotenv
    from services.news.company.fmp_fetcher import FMPFetcher

    load_dotenv(pathlib.Path(__file__).parent.parent / ".env")

    async def _demo():
        raw = await FMPFetcher().fetch_all("MSFT")
        calc = DimensionCalculator()
        dims = calc.calculate(raw)
        print(f"\nRaw dimensions for {raw.ticker}:")
        for k, v in dims.items():
            print(f"  {k:<40} {v}")

    asyncio.run(_demo())
