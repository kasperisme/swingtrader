"""
Single canonical definition of the 9 impact clusters and their dimensions.

Previously duplicated across video/config.py and agent/engine.py system prompt.
All services should import from here.
"""

from __future__ import annotations

CLUSTERS: list[dict] = [
    {
        "id": "MACRO_SENSITIVITY",
        "label": "Macro Sensitivity",
        "dimensions": [
            ("interest_rate_sensitivity_duration", "Interest Rate (Duration)"),
            ("interest_rate_sensitivity_debt", "Interest Rate (Debt)"),
            ("dollar_sensitivity", "Dollar Sensitivity"),
            ("inflation_sensitivity", "Inflation Sensitivity"),
            ("credit_spread_sensitivity", "Credit Spread Sensitivity"),
            ("commodity_input_exposure", "Commodity Input Exposure"),
            ("energy_cost_intensity", "Energy Cost Intensity"),
        ],
    },
    {
        "id": "SECTOR_ROTATION",
        "label": "Sector Rotation",
        "dimensions": [
            ("sector_financials", "Financials"),
            ("sector_technology", "Technology"),
            ("sector_healthcare", "Healthcare"),
            ("sector_energy", "Energy"),
            ("sector_realestate", "Real Estate"),
            ("sector_consumer", "Consumer"),
            ("sector_industrials", "Industrials"),
            ("sector_utilities", "Utilities"),
        ],
    },
    {
        "id": "BUSINESS_MODEL",
        "label": "Business Model",
        "dimensions": [
            ("revenue_predictability", "Revenue Predictability"),
            ("revenue_cyclicality", "Revenue Cyclicality"),
            ("pricing_power_structural", "Structural Pricing Power"),
            ("pricing_power_cyclical", "Cyclical Pricing Power"),
            ("capex_intensity", "Capex Intensity"),
        ],
    },
    {
        "id": "FINANCIAL_STRUCTURE",
        "label": "Financial Structure",
        "dimensions": [
            ("debt_burden", "Debt Burden"),
            ("floating_rate_debt_ratio", "Floating Rate Debt"),
            ("debt_maturity_nearterm", "Near-Term Debt Maturity"),
            ("financial_health", "Financial Health"),
            ("earnings_quality", "Earnings Quality"),
            ("accruals_ratio", "Accruals Ratio"),
            ("buyback_capacity", "Buyback Capacity"),
        ],
    },
    {
        "id": "GROWTH_PROFILE",
        "label": "Growth Profile",
        "dimensions": [
            ("revenue_growth_rate", "Revenue Growth"),
            ("eps_growth_rate", "EPS Growth"),
            ("eps_acceleration", "EPS Acceleration"),
            ("forward_growth_expectations", "Forward Growth"),
            ("earnings_revision_trend", "Earnings Revisions"),
        ],
    },
    {
        "id": "VALUATION_POSITIONING",
        "label": "Valuation & Positioning",
        "dimensions": [
            ("valuation_multiple", "Valuation Multiple"),
            ("factor_value", "Value Factor"),
            ("short_interest_ratio", "Short Interest"),
            ("short_squeeze_risk", "Short Squeeze Risk"),
            ("price_momentum", "Price Momentum"),
        ],
    },
    {
        "id": "GEOGRAPHY_TRADE",
        "label": "Geography & Trade",
        "dimensions": [
            ("china_revenue_exposure", "China Exposure"),
            ("emerging_market_exposure", "EM Exposure"),
            ("domestic_revenue_concentration", "Domestic Revenue"),
            ("tariff_sensitivity", "Tariff Sensitivity"),
        ],
    },
    {
        "id": "SUPPLY_CHAIN_EXPOSURE",
        "label": "Supply Chain",
        "dimensions": [
            ("upstream_concentration", "Supplier Concentration"),
            ("geographic_supply_risk", "Geographic Supply Risk"),
            ("inventory_intensity", "Inventory Intensity"),
            ("input_specificity", "Input Specificity"),
            ("supplier_bargaining_power", "Supplier Bargaining Power"),
            ("downstream_customer_concentration", "Customer Concentration"),
        ],
    },
    {
        "id": "MARKET_BEHAVIOUR",
        "label": "Market Behaviour",
        "dimensions": [
            ("institutional_appeal", "Institutional Appeal"),
            ("institutional_ownership_change", "Inst. Ownership Change"),
            ("short_squeeze_potential", "Short Squeeze Potential"),
            ("earnings_surprise_volatility", "Earnings Surprise Vol."),
        ],
    },
]

CLUSTER_ID_TO_LABEL: dict[str, str] = {c["id"]: c["label"] for c in CLUSTERS}

DIM_KEY_TO_LABEL: dict[str, str] = {}
for _c in CLUSTERS:
    for _key, _label in _c["dimensions"]:
        DIM_KEY_TO_LABEL[_key] = _label
