export interface ScanRun {
  id: number;
  created_at: string;
  scan_date: string;
  source: string;
}

export interface ScreeningRow {
  scan_row_id: number;
  run_id: number;
  symbol: string;
  rowData: Record<string, unknown>;
  sector: string;
  industry: string;
  subSector: string;
  RS_Rank: number | null;
  Passed: boolean;
  PASSED_FUNDAMENTALS: boolean;
  PriceOverSMA150And200: boolean;
  SMA150AboveSMA200: boolean;
  SMA50AboveSMA150And200: boolean;
  SMA200Slope: boolean;
  PriceAbove25Percent52WeekLow: boolean;
  PriceWithin25Percent52WeekHigh: boolean;
  RSOver70: boolean;
  adr_pct: number | null;
  vol_ratio_today: number | null;
  up_down_vol_ratio: number | null;
  accumulation: boolean | null;
  rs_line_new_high: boolean | null;
  within_buy_range: boolean | null;
  extended: boolean | null;
  increasing_eps: boolean;
  beat_estimate: boolean;
  eps_growth_yoy: number | null;
  rev_growth_yoy: number | null;
  eps_accelerating: boolean | null;
  three_yr_annual_eps_25pct: boolean | null;
  roe: number | null;
  roe_above_17pct: boolean | null;
  passes_oneil_fundamentals: boolean | null;
  sector_is_leader: boolean | null;
  sector_rank: number | null;
  total_sectors: number | null;
  inst_shares_increasing: boolean | null;
  inst_pct_accumulating: number | null;
}

export type NoteStatus = "active" | "dismissed" | "watchlist" | "pipeline";

export interface ScanRowNote {
  scan_row_id: number;
  run_id: number;
  ticker: string;
  user_id: string;
  status: NoteStatus;
  highlighted: boolean;
  comment: string | null;
  stage: string | null;
  priority: number | null;
  tags: string[];
  metadata_json: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export type ViewTab =
  | "results"
  | "quotes"
  | "charts"
  | "news"
  | "sentiment"
  | "relationship"
  | "tradeMonitoring";

export const DEEP_DIVE_VIEWS: ViewTab[] = ["charts", "news", "relationship"];

export function isDeepDiveView(v: ViewTab): boolean {
  return DEEP_DIVE_VIEWS.includes(v);
}

export type ScreeningsPrimaryTabDef = {
  id: ViewTab;
  label: string;
  icon: React.ReactNode;
};