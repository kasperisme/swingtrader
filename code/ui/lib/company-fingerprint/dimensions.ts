import type { HeatmapCluster } from "@/lib/news-impact-heatmap/aggregate";

/** Eight sector classification dimensions. Always rendered in the sector inset
 *  even when raw value is null — zero exposure is informative for sectors. */
export const SECTOR_DIMS = [
  "sector_technology",
  "sector_financials",
  "sector_healthcare",
  "sector_consumer",
  "sector_industrials",
  "sector_energy",
  "sector_utilities",
  "sector_realestate",
] as const;

export type SectorDim = (typeof SECTOR_DIMS)[number];

/** A dim maps to one or more clusters. For sector dims, the mapping carries the
 *  sub-key inside SECTOR_ROTATION's scores_json so we can isolate that one
 *  sector's news pressure rather than averaging across all sectors. */
export type DimMapping = HeatmapCluster | [HeatmapCluster, string];

export const DIM_TO_CLUSTERS: Record<string, DimMapping[]> = {
  // Growth
  eps_growth_rate: ["GROWTH_PROFILE"],
  eps_acceleration: ["GROWTH_PROFILE"],
  earnings_quality: ["GROWTH_PROFILE"],
  earnings_revision_trend: ["GROWTH_PROFILE"],
  forward_growth_expectations: ["GROWTH_PROFILE"],
  revenue_growth_rate: ["GROWTH_PROFILE"],

  // Valuation / momentum
  factor_value: ["VALUATION_POSITIONING"],
  valuation_multiple: ["VALUATION_POSITIONING"],
  price_momentum: ["VALUATION_POSITIONING"],

  // Financial structure
  debt_burden: ["FINANCIAL_STRUCTURE"],
  debt_maturity_nearterm: ["FINANCIAL_STRUCTURE"],
  floating_rate_debt_ratio: ["FINANCIAL_STRUCTURE"],
  financial_health: ["FINANCIAL_STRUCTURE"],
  buyback_capacity: ["FINANCIAL_STRUCTURE"],

  // Business model
  pricing_power: ["BUSINESS_MODEL"],
  revenue_recurring: ["BUSINESS_MODEL"],
  revenue_transactional: ["BUSINESS_MODEL"],
  revenue_cyclical: ["BUSINESS_MODEL"],
  capex_intensity: ["BUSINESS_MODEL"],

  // Geography / trade
  tariff_sensitivity: ["GEOGRAPHY_TRADE"],
  china_revenue_exposure: ["GEOGRAPHY_TRADE"],
  emerging_market_exposure: ["GEOGRAPHY_TRADE"],
  domestic_revenue_concentration: ["GEOGRAPHY_TRADE"],
  dollar_sensitivity: ["GEOGRAPHY_TRADE", "MACRO_SENSITIVITY"],

  // Supply chain
  commodity_input_exposure: ["SUPPLY_CHAIN_EXPOSURE"],
  energy_cost_intensity: ["SUPPLY_CHAIN_EXPOSURE"],

  // Macro
  inflation_sensitivity: ["MACRO_SENSITIVITY"],
  interest_rate_sensitivity: ["MACRO_SENSITIVITY"],
  credit_spread_sensitivity: ["MACRO_SENSITIVITY"],

  // Market behaviour
  short_interest_ratio: ["MARKET_BEHAVIOUR"],
  options_implied_volatility: ["MARKET_BEHAVIOUR"],
  crowded_long_risk: ["MARKET_BEHAVIOUR"],
  retail_sentiment_exposure: ["MARKET_BEHAVIOUR"],

  // Ticker / institutional
  institutional_appeal: ["TICKER_RELATIONSHIPS"],
  institutional_ownership_change: ["TICKER_RELATIONSHIPS"],

  // Sector classification (route through SECTOR_ROTATION sub-keys)
  sector_technology: [["SECTOR_ROTATION", "sector_technology"]],
  sector_financials: [["SECTOR_ROTATION", "sector_financials"]],
  sector_healthcare: [["SECTOR_ROTATION", "sector_healthcare"]],
  sector_consumer: [["SECTOR_ROTATION", "sector_consumer"]],
  sector_industrials: [["SECTOR_ROTATION", "sector_industrials"]],
  sector_energy: [["SECTOR_ROTATION", "sector_energy"]],
  sector_utilities: [["SECTOR_ROTATION", "sector_utilities"]],
  sector_realestate: [["SECTOR_ROTATION", "sector_realestate"]],
};

const SECTOR_DIM_SET: ReadonlySet<string> = new Set<string>(SECTOR_DIMS);

export function isSectorDim(dim: string): dim is SectorDim {
  return SECTOR_DIM_SET.has(dim);
}

/** Pretty-print a dim key for display. */
export function formatDimLabel(dim: string): string {
  return dim
    .split("_")
    .map((p) => p.charAt(0).toUpperCase() + p.slice(1))
    .join(" ");
}

/** Operational dims = everything that isn't a sector classification. Derived
 *  from the row's own raw_json keys, so the canvas adapts if the upstream
 *  schema grows or shrinks. */
export function operationalDimsOf(allKeys: Iterable<string>): string[] {
  const out: string[] = [];
  for (const k of allKeys) {
    if (!isSectorDim(k)) out.push(k);
  }
  return out;
}
