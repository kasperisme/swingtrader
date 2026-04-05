"""
Dimension cluster definitions for the company embedding system.

Each dimension maps to a single numeric value (0-1 rank-normalised) that
describes one aspect of a company's exposure or characteristic.
"""

CLUSTERS: dict[str, list[dict]] = {
    "MACRO_SENSITIVITY": [
        {
            "key": "interest_rate_sensitivity",
            "label": "Interest Rate Sensitivity",
            "description": "High duration assets, long-dated cash flows; proxied by P/E or revenue growth rate",
            "cluster": "macro_sensitivity",
            "higher_is": "worse",
        },
        {
            "key": "dollar_sensitivity",
            "label": "Dollar Sensitivity",
            "description": "High international revenue as % of total",
            "cluster": "macro_sensitivity",
            "higher_is": "worse",
        },
        {
            "key": "inflation_sensitivity",
            "label": "Inflation Sensitivity",
            "description": "Input costs as % of revenue (inverse of gross margin)",
            "cluster": "macro_sensitivity",
            "higher_is": "worse",
        },
        {
            "key": "credit_spread_sensitivity",
            "label": "Credit Spread Sensitivity",
            "description": "High yield debt issuers, leveraged balance sheets; total debt / EBITDA",
            "cluster": "macro_sensitivity",
            "higher_is": "worse",
        },
        {
            "key": "commodity_input_exposure",
            "label": "Commodity Input Exposure",
            "description": "Raw material costs as % of COGS; proxied by sector",
            "cluster": "macro_sensitivity",
            "higher_is": "worse",
        },
        {
            "key": "energy_cost_intensity",
            "label": "Energy Cost Intensity",
            "description": "Energy as significant operating cost driver; proxied by industry",
            "cluster": "macro_sensitivity",
            "higher_is": "worse",
        },
    ],
    "SECTOR_ROTATION": [
        {
            "key": "sector_financials",
            "label": "Financials Sector",
            "description": "Banks, insurance, asset managers",
            "cluster": "sector_rotation",
            "higher_is": "better",
        },
        {
            "key": "sector_technology",
            "label": "Technology Sector",
            "description": "Software, semiconductors, hardware, internet",
            "cluster": "sector_rotation",
            "higher_is": "better",
        },
        {
            "key": "sector_healthcare",
            "label": "Healthcare Sector",
            "description": "Pharma, biotech, medical devices, services",
            "cluster": "sector_rotation",
            "higher_is": "better",
        },
        {
            "key": "sector_energy",
            "label": "Energy Sector",
            "description": "Oil, gas, renewables, pipelines",
            "cluster": "sector_rotation",
            "higher_is": "better",
        },
        {
            "key": "sector_realestate",
            "label": "Real Estate Sector",
            "description": "REITs, property developers, real estate services",
            "cluster": "sector_rotation",
            "higher_is": "better",
        },
        {
            "key": "sector_consumer",
            "label": "Consumer Sector",
            "description": "Retail, discretionary, staples, restaurants",
            "cluster": "sector_rotation",
            "higher_is": "better",
        },
        {
            "key": "sector_industrials",
            "label": "Industrials Sector",
            "description": "Manufacturing, aerospace, transportation, logistics",
            "cluster": "sector_rotation",
            "higher_is": "better",
        },
        {
            "key": "sector_utilities",
            "label": "Utilities Sector",
            "description": "Electric, gas, water utilities",
            "cluster": "sector_rotation",
            "higher_is": "better",
        },
    ],
    "BUSINESS_MODEL": [
        {
            "key": "revenue_recurring",
            "label": "Recurring Revenue",
            "description": "Subscription, SaaS, contracted revenue streams",
            "cluster": "business_model",
            "higher_is": "better",
        },
        {
            "key": "revenue_transactional",
            "label": "Transactional Revenue",
            "description": "Volume-based, ad spend, payment processing",
            "cluster": "business_model",
            "higher_is": "better",
        },
        {
            "key": "revenue_cyclical",
            "label": "Cyclical Revenue",
            "description": "Tied to economic cycle, capex, construction",
            "cluster": "business_model",
            "higher_is": "worse",
        },
        {
            "key": "pricing_power",
            "label": "Pricing Power",
            "description": "Gross margin stability over time (lower stdev = higher power)",
            "cluster": "business_model",
            "higher_is": "better",
        },
        {
            "key": "capex_intensity",
            "label": "Capex Intensity",
            "description": "Capex as % of revenue",
            "cluster": "business_model",
            "higher_is": "worse",
        },
    ],
    "FINANCIAL_STRUCTURE": [
        {
            "key": "debt_burden",
            "label": "Debt Burden",
            "description": "Total debt / EBITDA",
            "cluster": "financial_structure",
            "higher_is": "worse",
        },
        {
            "key": "floating_rate_debt_ratio",
            "label": "Floating Rate Debt Ratio",
            "description": "Proportion of debt at variable rates (proxy: short-term debt / total debt)",
            "cluster": "financial_structure",
            "higher_is": "worse",
        },
        {
            "key": "debt_maturity_nearterm",
            "label": "Near-Term Debt Maturity",
            "description": "Debt due within 2 years as % of total debt (proxy: short-term debt / total debt)",
            "cluster": "financial_structure",
            "higher_is": "worse",
        },
        {
            "key": "financial_health",
            "label": "Financial Health",
            "description": "Composite of current ratio and interest coverage",
            "cluster": "financial_structure",
            "higher_is": "better",
        },
        {
            "key": "earnings_quality",
            "label": "Earnings Quality",
            "description": "FCF / net income ratio",
            "cluster": "financial_structure",
            "higher_is": "better",
        },
        {
            "key": "buyback_capacity",
            "label": "Buyback Capacity",
            "description": "Cash minus short-term debt as % of market cap",
            "cluster": "financial_structure",
            "higher_is": "better",
        },
    ],
    "GROWTH_PROFILE": [
        {
            "key": "revenue_growth_rate",
            "label": "Revenue Growth Rate",
            "description": "YoY revenue growth (TTM)",
            "cluster": "growth_profile",
            "higher_is": "better",
        },
        {
            "key": "eps_growth_rate",
            "label": "EPS Growth Rate",
            "description": "YoY EPS growth (TTM)",
            "cluster": "growth_profile",
            "higher_is": "better",
        },
        {
            "key": "eps_acceleration",
            "label": "EPS Acceleration",
            "description": "Change in EPS growth rate QoQ",
            "cluster": "growth_profile",
            "higher_is": "better",
        },
        {
            "key": "forward_growth_expectations",
            "label": "Forward Growth Expectations",
            "description": "Forward EPS estimate vs trailing EPS",
            "cluster": "growth_profile",
            "higher_is": "better",
        },
        {
            "key": "earnings_revision_trend",
            "label": "Earnings Revision Trend",
            "description": "Direction of analyst estimate revisions vs last actual EPS",
            "cluster": "growth_profile",
            "higher_is": "better",
        },
    ],
    "VALUATION_POSITIONING": [
        {
            "key": "valuation_multiple",
            "label": "Valuation Multiple",
            "description": "EV/EBITDA or P/E (higher = more expensive)",
            "cluster": "valuation_positioning",
            "higher_is": "worse",
        },
        {
            "key": "factor_value",
            "label": "Value Factor",
            "description": "Inverse of valuation multiple (lower multiple = more value)",
            "cluster": "valuation_positioning",
            "higher_is": "better",
        },
        {
            "key": "short_interest_ratio",
            "label": "Short Interest Ratio",
            "description": "Short interest as % of float — not available in FMP stable",
            "cluster": "valuation_positioning",
            "higher_is": "worse",
        },
        {
            "key": "crowded_long_risk",
            "label": "Crowded Long Risk",
            "description": "Institutional ownership concentration as proxy",
            "cluster": "valuation_positioning",
            "higher_is": "worse",
        },
        {
            "key": "price_momentum",
            "label": "Price Momentum",
            "description": "Price vs 52-week high (%)",
            "cluster": "valuation_positioning",
            "higher_is": "better",
        },
    ],
    "GEOGRAPHY_TRADE": [
        {
            "key": "china_revenue_exposure",
            "label": "China Revenue Exposure",
            "description": "Revenue derived from China operations",
            "cluster": "geography_trade",
            "higher_is": "worse",
        },
        {
            "key": "emerging_market_exposure",
            "label": "Emerging Market Exposure",
            "description": "Revenue from EM ex-China",
            "cluster": "geography_trade",
            "higher_is": "worse",
        },
        {
            "key": "domestic_revenue_concentration",
            "label": "Domestic Revenue Concentration",
            "description": "US-only or home-market revenue %",
            "cluster": "geography_trade",
            "higher_is": "better",
        },
        {
            "key": "tariff_sensitivity",
            "label": "Tariff Sensitivity",
            "description": "Import-dependent cost structure",
            "cluster": "geography_trade",
            "higher_is": "worse",
        },
    ],
    "MARKET_BEHAVIOUR": [
        {
            "key": "institutional_appeal",
            "label": "Institutional Appeal",
            "description": "Institutional ownership %",
            "cluster": "market_behaviour",
            "higher_is": "better",
        },
        {
            "key": "institutional_ownership_change",
            "label": "Institutional Ownership Change",
            "description": "QoQ change in institutional holders",
            "cluster": "market_behaviour",
            "higher_is": "better",
        },
        {
            "key": "retail_sentiment_exposure",
            "label": "Retail Sentiment Exposure",
            "description": "Short interest + options activity proxy — requires options data",
            "cluster": "market_behaviour",
            "higher_is": "worse",
        },
        {
            "key": "options_implied_volatility",
            "label": "Options Implied Volatility",
            "description": "Market's priced-in uncertainty — requires options data",
            "cluster": "market_behaviour",
            "higher_is": "worse",
        },
    ],
}

# Flat list of all dimension dicts for easy iteration
ALL_DIMENSIONS: list[dict] = [dim for dims in CLUSTERS.values() for dim in dims]

# Flat mapping key → dimension dict
DIMENSION_MAP: dict[str, dict] = {dim["key"]: dim for dim in ALL_DIMENSIONS}


if __name__ == "__main__":
    total = sum(len(v) for v in CLUSTERS.values())
    print(f"Clusters: {len(CLUSTERS)}  |  Total dimensions: {total}")
    for cluster, dims in CLUSTERS.items():
        print(f"\n{cluster}")
        for d in dims:
            print(f"  {d['key']:<40} higher_is={d['higher_is']}")
