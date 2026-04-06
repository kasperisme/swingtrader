export interface Dimension {
  key: string;
  label: string;
  description: string;
  cluster: string;
  higher_is: "better" | "worse";
}

export interface Cluster {
  id: string;
  label: string;
  dimensions: Dimension[];
}

export const CLUSTERS: Cluster[] = [
  {
    id: "MACRO_SENSITIVITY",
    label: "Macro Sensitivity",
    dimensions: [
      {
        key: "interest_rate_sensitivity_duration",
        label: "Interest Rate (Duration)",
        description:
          "Equity duration channel: high P/E, high growth, low dividend yield stocks are most sensitive to rate changes via discount rate effect.",
        cluster: "macro_sensitivity",
        higher_is: "worse",
      },
      {
        key: "interest_rate_sensitivity_debt",
        label: "Interest Rate (Debt)",
        description:
          "Debt refinancing channel: companies with near-term floating rate or short-duration debt face direct cost-of-capital impact from rate moves.",
        cluster: "macro_sensitivity",
        higher_is: "worse",
      },
      {
        key: "dollar_sensitivity",
        label: "Dollar Sensitivity",
        description: "High international revenue as % of total — sensitive to USD strength.",
        cluster: "macro_sensitivity",
        higher_is: "worse",
      },
      {
        key: "inflation_sensitivity",
        label: "Inflation Sensitivity",
        description: "Input costs as % of revenue (inverse of gross margin).",
        cluster: "macro_sensitivity",
        higher_is: "worse",
      },
      {
        key: "credit_spread_sensitivity",
        label: "Credit Spread Sensitivity",
        description: "High yield debt issuers, leveraged balance sheets; total debt / EBITDA.",
        cluster: "macro_sensitivity",
        higher_is: "worse",
      },
      {
        key: "commodity_input_exposure",
        label: "Commodity Input Exposure",
        description: "Raw material costs as % of COGS; proxied by sector.",
        cluster: "macro_sensitivity",
        higher_is: "worse",
      },
      {
        key: "energy_cost_intensity",
        label: "Energy Cost Intensity",
        description: "Energy as significant operating cost driver; proxied by industry.",
        cluster: "macro_sensitivity",
        higher_is: "worse",
      },
    ],
  },
  {
    id: "SECTOR_ROTATION",
    label: "Sector Rotation",
    dimensions: [
      {
        key: "sector_financials",
        label: "Financials",
        description: "Banks, insurance, asset managers.",
        cluster: "sector_rotation",
        higher_is: "better",
      },
      {
        key: "sector_technology",
        label: "Technology",
        description: "Software, semiconductors, hardware, internet.",
        cluster: "sector_rotation",
        higher_is: "better",
      },
      {
        key: "sector_healthcare",
        label: "Healthcare",
        description: "Pharma, biotech, medical devices, services.",
        cluster: "sector_rotation",
        higher_is: "better",
      },
      {
        key: "sector_energy",
        label: "Energy",
        description: "Oil, gas, renewables, pipelines.",
        cluster: "sector_rotation",
        higher_is: "better",
      },
      {
        key: "sector_realestate",
        label: "Real Estate",
        description: "REITs, property developers, real estate services.",
        cluster: "sector_rotation",
        higher_is: "better",
      },
      {
        key: "sector_consumer",
        label: "Consumer",
        description: "Retail, discretionary, staples, restaurants.",
        cluster: "sector_rotation",
        higher_is: "better",
      },
      {
        key: "sector_industrials",
        label: "Industrials",
        description: "Manufacturing, aerospace, transportation, logistics.",
        cluster: "sector_rotation",
        higher_is: "better",
      },
      {
        key: "sector_utilities",
        label: "Utilities",
        description: "Electric, gas, water utilities.",
        cluster: "sector_rotation",
        higher_is: "better",
      },
    ],
  },
  {
    id: "BUSINESS_MODEL",
    label: "Business Model",
    dimensions: [
      {
        key: "revenue_predictability",
        label: "Revenue Predictability",
        description:
          "How forecastable is next quarter's revenue. High for SaaS/subscriptions, utilities. Low for project-based or ad-driven businesses.",
        cluster: "business_model",
        higher_is: "better",
      },
      {
        key: "revenue_cyclicality",
        label: "Revenue Cyclicality",
        description:
          "Degree to which revenue co-moves with the economic cycle. High for industrials, materials. Low for healthcare, utilities.",
        cluster: "business_model",
        higher_is: "worse",
      },
      {
        key: "pricing_power_structural",
        label: "Structural Pricing Power",
        description:
          "Industry structure advantage: oligopoly, regulated monopoly, or strong brand moat enabling sustained high margins.",
        cluster: "business_model",
        higher_is: "better",
      },
      {
        key: "pricing_power_cyclical",
        label: "Cyclical Pricing Power",
        description:
          "Ability to raise prices during inflationary periods without losing volume. Proxy: gross margin stability.",
        cluster: "business_model",
        higher_is: "better",
      },
      {
        key: "capex_intensity",
        label: "Capex Intensity",
        description: "Capex as % of revenue.",
        cluster: "business_model",
        higher_is: "worse",
      },
    ],
  },
  {
    id: "FINANCIAL_STRUCTURE",
    label: "Financial Structure",
    dimensions: [
      {
        key: "debt_burden",
        label: "Debt Burden",
        description: "Total debt / EBITDA.",
        cluster: "financial_structure",
        higher_is: "worse",
      },
      {
        key: "floating_rate_debt_ratio",
        label: "Floating Rate Debt",
        description: "Proportion of debt at variable rates (proxy: short-term debt / total debt).",
        cluster: "financial_structure",
        higher_is: "worse",
      },
      {
        key: "debt_maturity_nearterm",
        label: "Near-Term Debt Maturity",
        description: "Debt due within 2 years as % of total debt.",
        cluster: "financial_structure",
        higher_is: "worse",
      },
      {
        key: "financial_health",
        label: "Financial Health",
        description: "Composite of current ratio and interest coverage.",
        cluster: "financial_structure",
        higher_is: "better",
      },
      {
        key: "earnings_quality",
        label: "Earnings Quality",
        description: "FCF / net income ratio.",
        cluster: "financial_structure",
        higher_is: "better",
      },
      {
        key: "accruals_ratio",
        label: "Accruals Ratio",
        description:
          "Non-cash component of earnings: (net income − operating cash flow) / total assets. Lower = higher quality earnings.",
        cluster: "financial_structure",
        higher_is: "worse",
      },
      {
        key: "buyback_capacity",
        label: "Buyback Capacity",
        description: "Cash minus short-term debt as % of market cap.",
        cluster: "financial_structure",
        higher_is: "better",
      },
    ],
  },
  {
    id: "GROWTH_PROFILE",
    label: "Growth Profile",
    dimensions: [
      {
        key: "revenue_growth_rate",
        label: "Revenue Growth",
        description: "YoY revenue growth (TTM).",
        cluster: "growth_profile",
        higher_is: "better",
      },
      {
        key: "eps_growth_rate",
        label: "EPS Growth",
        description: "YoY EPS growth (TTM).",
        cluster: "growth_profile",
        higher_is: "better",
      },
      {
        key: "eps_acceleration",
        label: "EPS Acceleration",
        description: "Change in EPS growth rate QoQ.",
        cluster: "growth_profile",
        higher_is: "better",
      },
      {
        key: "forward_growth_expectations",
        label: "Forward Growth",
        description: "Forward EPS estimate vs trailing EPS.",
        cluster: "growth_profile",
        higher_is: "better",
      },
      {
        key: "earnings_revision_trend",
        label: "Earnings Revisions",
        description: "Direction of analyst estimate revisions vs last actual EPS.",
        cluster: "growth_profile",
        higher_is: "better",
      },
    ],
  },
  {
    id: "VALUATION_POSITIONING",
    label: "Valuation & Positioning",
    dimensions: [
      {
        key: "valuation_multiple",
        label: "Valuation Multiple",
        description: "EV/EBITDA or P/E (higher = more expensive).",
        cluster: "valuation_positioning",
        higher_is: "worse",
      },
      {
        key: "factor_value",
        label: "Value Factor",
        description: "Inverse of valuation multiple (lower multiple = more value).",
        cluster: "valuation_positioning",
        higher_is: "better",
      },
      {
        key: "short_interest_ratio",
        label: "Short Interest",
        description: "Short interest as % of float.",
        cluster: "valuation_positioning",
        higher_is: "worse",
      },
      {
        key: "short_squeeze_risk",
        label: "Short Squeeze Risk",
        description:
          "Potential for rapid upward price movement if short sellers are forced to cover.",
        cluster: "valuation_positioning",
        higher_is: "better",
      },
      {
        key: "price_momentum",
        label: "Price Momentum",
        description: "Price vs 52-week high (%).",
        cluster: "valuation_positioning",
        higher_is: "better",
      },
    ],
  },
  {
    id: "GEOGRAPHY_TRADE",
    label: "Geography & Trade",
    dimensions: [
      {
        key: "china_revenue_exposure",
        label: "China Exposure",
        description: "Revenue derived from China operations.",
        cluster: "geography_trade",
        higher_is: "worse",
      },
      {
        key: "emerging_market_exposure",
        label: "EM Exposure",
        description: "Revenue from EM ex-China.",
        cluster: "geography_trade",
        higher_is: "worse",
      },
      {
        key: "domestic_revenue_concentration",
        label: "Domestic Revenue",
        description: "US-only or home-market revenue %.",
        cluster: "geography_trade",
        higher_is: "better",
      },
      {
        key: "tariff_sensitivity",
        label: "Tariff Sensitivity",
        description: "Import-dependent cost structure.",
        cluster: "geography_trade",
        higher_is: "worse",
      },
    ],
  },
  {
    id: "SUPPLY_CHAIN_EXPOSURE",
    label: "Supply Chain",
    dimensions: [
      {
        key: "upstream_concentration",
        label: "Supplier Concentration",
        description:
          "Degree of dependency on a small number of suppliers. High = higher disruption risk.",
        cluster: "supply_chain_exposure",
        higher_is: "worse",
      },
      {
        key: "geographic_supply_risk",
        label: "Geographic Supply Risk",
        description:
          "Exposure to supply disruption from geographically concentrated supply chains.",
        cluster: "supply_chain_exposure",
        higher_is: "worse",
      },
      {
        key: "inventory_intensity",
        label: "Inventory Intensity",
        description:
          "Inventory as % of revenue. High = more exposed to supply chain cost shocks.",
        cluster: "supply_chain_exposure",
        higher_is: "worse",
      },
      {
        key: "input_specificity",
        label: "Input Specificity",
        description:
          "How substitutable are the company's key inputs. High = disruption cannot be easily routed around.",
        cluster: "supply_chain_exposure",
        higher_is: "worse",
      },
      {
        key: "supplier_bargaining_power",
        label: "Supplier Bargaining Power",
        description:
          "Relative size of firm vs its suppliers. Small firms dealing with large suppliers have limited leverage.",
        cluster: "supply_chain_exposure",
        higher_is: "worse",
      },
      {
        key: "downstream_customer_concentration",
        label: "Customer Concentration",
        description:
          "Dependency on a small number of customers for revenue. High = amplified revenue volatility.",
        cluster: "supply_chain_exposure",
        higher_is: "worse",
      },
    ],
  },
  {
    id: "MARKET_BEHAVIOUR",
    label: "Market Behaviour",
    dimensions: [
      {
        key: "institutional_appeal",
        label: "Institutional Appeal",
        description: "Institutional ownership %.",
        cluster: "market_behaviour",
        higher_is: "better",
      },
      {
        key: "institutional_ownership_change",
        label: "Inst. Ownership Change",
        description: "QoQ change in institutional holders.",
        cluster: "market_behaviour",
        higher_is: "better",
      },
      {
        key: "short_squeeze_potential",
        label: "Short Squeeze Potential",
        description:
          "Composite of short interest as % of float and days-to-cover. High = forced-covering risk on positive news.",
        cluster: "market_behaviour",
        higher_is: "better",
      },
      {
        key: "earnings_surprise_volatility",
        label: "Earnings Surprise Vol.",
        description:
          "Std dev of EPS surprise magnitude over last 8 quarters. High = unpredictable earnings.",
        cluster: "market_behaviour",
        higher_is: "worse",
      },
    ],
  },
];

export const ALL_DIMENSIONS = CLUSTERS.flatMap((c) => c.dimensions);
export const DIMENSION_MAP = Object.fromEntries(ALL_DIMENSIONS.map((d) => [d.key, d]));
