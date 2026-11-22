/**
 * Client-safe half of the correction stress test: types, labels and number
 * formatting, shared by server pages and the client-side /correction board.
 * The reads live in `./narrative` (server-only).
 */

export type NarrativeGroup = "on_top" | "holds" | "fragile" | "drowns" | "not_cash_flow" | "refused";
export type Exposure = "low" | "medium" | "high";
export type EarningsQuality = "clean" | "watch" | "weak" | "unknown";

export const QUALITY_LABEL: Record<EarningsQuality, string> = {
  clean: "Clean earnings",
  watch: "Earnings: one red flag",
  weak: "Weak earnings quality",
  unknown: "Earnings not checked",
};

export const GROUP_LABEL: Record<NarrativeGroup, string> = {
  on_top: "Comes out on top",
  holds: "Holds",
  fragile: "Fragile",
  drowns: "Drowns",
  not_cash_flow: "Not valued on cash flow",
  refused: "Refused",
};

export const GROUP_RULE: Record<NarrativeGroup, string> = {
  on_top: "Survives a bust-sized cut to analyst growth (10 points, or half the forecast if larger), with the median analyst target at least 15% above the price and no more than one earnings-quality red flag.",
  holds: "Survives a correction-sized 3-point cut to analyst growth.",
  fragile: "Paid for today, but breaks on a small cut — or only looks over-priced at a 9% discount rate.",
  drowns: "The price already needs more growth than analysts forecast, at both a 9% and an 8% discount rate.",
  not_cash_flow: "Financials, REITs, negative free cash flow or no revenue consensus — a cash-flow test does not apply.",
  refused: "The stored price does not match the split-adjusted close on the model date.",
};

export interface NarrativeRun {
  asOf: string;
  estimateSnapshot: string;
  dropDate: string;
  universe: number;
  groups: Partial<Record<NarrativeGroup, number>>;
  sealSha256: string;
}

export interface NarrativeRow {
  ticker: string;
  company: string | null;
  sector: string | null;
  group: NarrativeGroup;
  rank: number | null;
  thesis: string | null;
  breaksIf: string | null;
  reason: string | null;
  price: number | null;
  closeDate: string | null;
  drawdownFromPeak: number | null;
  requiredCagr: number | null;
  consensus3y: number | null;
  supportedCagr: number | null;
  breakevenCut: number | null;
  marginUsed: number | null;
  upsideToMedian: number | null;
  nTargets: number | null;
  targetsPredateDrop: boolean;
  modelAsOf: string | null;
  epicenter: boolean;
  epicenterLinked: boolean;
  linkedWith: string[];
  beta: number | null;
  exposure: Exposure;
  flags: string[];
  /** Which margin decided the group: analysts' ('consensus') or cut for cash conversion ('quality'). */
  marginBasis: "consensus" | "quality" | null;
  breakevenConsensus: number | null;
  breakevenQuality: number | null;
  consensusMargin: number | null;
  qualityMargin: number | null;
  quality: EarningsQuality;
  qualityFlags: string[];
}

export interface NarrativeDetail extends NarrativeRow {
  cashConversion: number | null;
  cashMargin: number | null;
  cfoToNi: number | null;
  accruals: number | null;
  sbcToRevenue: number | null;
  shareGrowth: number | null;
  oneOffShare: number | null;
  qualityYears: number | null;
  crux: string | null;
  position: string | null;
  paysFor: string[];
}

// ── formatting (shared by the landing section and the pages) ────────────────

export const fmtPct = (v: number | null, d = 1) =>
  v == null ? "—" : `${v >= 0 ? "+" : "−"}${Math.abs(v * 100).toFixed(d)}%`;
export const fmtPts = (v: number | null) =>
  v == null ? "—" : `${v >= 0 ? "+" : "−"}${Math.abs(v * 100).toFixed(0)}pt`;
export const fmtUsd = (v: number | null) =>
  v == null ? "—" : `$${v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

const DAY = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
export const fmtDay = (iso: string | null) => (iso ? DAY.format(new Date(`${iso}T00:00:00Z`)) : "—");

/** The reconstruction prose carries a `{price}` placeholder. */
export const injectPriceText = (t: string, price: number | null) =>
  t.replaceAll("{price}", price == null ? "the price" : fmtUsd(price));
