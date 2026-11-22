import "server-only";
import { cacheLife, cacheTag } from "next/cache";
import { createServiceClient } from "@/lib/supabase/service";

/**
 * The correction stress test: whose priced-in narrative survives the drawdown.
 *
 * Written nightly by `code/analytics/services/drawdown/narrative.py` into
 * `swingtrader.drawdown_narrative_scores` (one row per ticker per day) and
 * `drawdown_narrative_runs` (written LAST — a day is shown only once its run
 * row exists).
 *
 * What it is: for each name, the revenue growth its share price requires (10y
 * reverse DCF re-solved at the latest close) against what analysts forecast
 * (3y consensus, faded to terminal growth), and how big a cut to that forecast
 * the price can absorb. A description of whether a narrative is FUNDED, not a
 * return forecast — the priced-in walk-forward found implied growth alone is no
 * return signal, and these groups have not been graded yet. Every surface that
 * shows them says so.
 *
 * `declines` (what the price refuses to pay for) is members-only on /quote, so
 * it is never selected here.
 */

const SCHEMA = "swingtrader";

import type {
  EarningsQuality,
  Exposure,
  NarrativeDetail,
  NarrativeGroup,
  NarrativeRow,
  NarrativeRun,
} from "./narrative-format";

export * from "./narrative-format";

const BASE_COLUMNS =
  "ticker, company, sector, grp, rank, thesis, breaks_if, reason, price, close_date, drawdown_from_peak, " +
  "required_cagr, consensus_3y, supported_cagr, breakeven_cut, margin_used, upside_to_median, n_targets, " +
  "targets_predate_drop, model_as_of, epicenter, epicenter_linked, linked_with, beta, exposure, flags";
const ROW_COLUMNS =
  `${BASE_COLUMNS}, margin_basis, breakeven_consensus, breakeven_quality, consensus_margin, quality_margin, ` +
  "quality, quality_flags";
const DETAIL_COLUMNS =
  `${ROW_COLUMNS}, cash_conversion, cash_margin, cfo_to_ni, accruals, sbc_to_revenue, share_growth, ` +
  "one_off_share, quality_years, crux, position, pays_for";
const BASE_DETAIL_COLUMNS = `${BASE_COLUMNS}, crux, position, pays_for`;

/** Postgres "undefined column": the earnings-quality migration is not applied yet. */
const missingColumn = (e: { code?: string; message?: string } | null) =>
  !!e && (e.code === "42703" || /column .* does not exist/i.test(e.message ?? ""));

const n = (v: unknown): number | null => (v == null || !Number.isFinite(Number(v)) ? null : Number(v));
const s = (v: unknown): string | null => (v == null || v === "" ? null : String(v));

function toRow(r: Record<string, unknown>): NarrativeRow {
  return {
    ticker: String(r.ticker),
    company: s(r.company),
    sector: s(r.sector),
    group: r.grp as NarrativeGroup,
    rank: n(r.rank),
    thesis: s(r.thesis),
    breaksIf: s(r.breaks_if),
    reason: s(r.reason),
    price: n(r.price),
    closeDate: s(r.close_date),
    drawdownFromPeak: n(r.drawdown_from_peak),
    requiredCagr: n(r.required_cagr),
    consensus3y: n(r.consensus_3y),
    supportedCagr: n(r.supported_cagr),
    breakevenCut: n(r.breakeven_cut),
    marginUsed: n(r.margin_used),
    upsideToMedian: n(r.upside_to_median),
    nTargets: n(r.n_targets),
    targetsPredateDrop: Boolean(r.targets_predate_drop),
    modelAsOf: s(r.model_as_of),
    epicenter: Boolean(r.epicenter),
    epicenterLinked: Boolean(r.epicenter_linked),
    linkedWith: s(r.linked_with)?.split(",").filter(Boolean) ?? [],
    beta: n(r.beta),
    exposure: (s(r.exposure) ?? "low") as Exposure,
    flags: s(r.flags)?.split("; ").filter(Boolean) ?? [],
    marginBasis: (s(r.margin_basis) as NarrativeRow["marginBasis"]) ?? null,
    breakevenConsensus: n(r.breakeven_consensus),
    breakevenQuality: n(r.breakeven_quality),
    consensusMargin: n(r.consensus_margin),
    qualityMargin: n(r.quality_margin),
    quality: (s(r.quality) ?? "unknown") as EarningsQuality,
    qualityFlags: s(r.quality_flags)?.split("; ").filter(Boolean) ?? [],
  };
}

function toStrings(v: unknown): string[] {
  if (Array.isArray(v)) return v.map(String);
  if (typeof v === "string" && v.trim().startsWith("[")) {
    try {
      return (JSON.parse(v) as unknown[]).map(String);
    } catch {
      return [v];
    }
  }
  return [];
}

async function latestRun(): Promise<NarrativeRun | null> {
  const { data, error } = await createServiceClient()
    .schema(SCHEMA)
    .from("drawdown_narrative_runs")
    .select("as_of, estimate_snapshot, drop_date, universe, groups, seal_sha256")
    .order("as_of", { ascending: false })
    .limit(1);
  if (error || !data?.length) return null;
  const r = data[0] as Record<string, unknown>;
  return {
    asOf: String(r.as_of),
    estimateSnapshot: String(r.estimate_snapshot),
    dropDate: String(r.drop_date),
    universe: Number(r.universe),
    groups: (r.groups ?? {}) as NarrativeRun["groups"],
    sealSha256: String(r.seal_sha256),
  };
}

/** The latest complete day: its run row and every scored name, ranked within group. */
export async function getCorrectionBoard(): Promise<{ run: NarrativeRun; rows: NarrativeRow[] } | null> {
  "use cache";
  cacheLife("hours");
  cacheTag("correction-board");
  try {
    const run = await latestRun();
    if (!run) return null;
    const query = (cols: string) =>
      createServiceClient()
        .schema(SCHEMA)
        .from("drawdown_narrative_scores")
        .select(cols)
        .eq("as_of", run.asOf)
        .order("grp")
        .order("rank")
        .limit(2000);
    let { data, error } = await query(ROW_COLUMNS);
    // Until migration 20261121180000 is applied the quality columns do not exist;
    // render the board without them rather than not at all.
    if (missingColumn(error)) ({ data, error } = await query(BASE_COLUMNS));
    if (error) throw error;
    return { run, rows: ((data ?? []) as unknown as Record<string, unknown>[]).map(toRow) };
  } catch {
    return null;
  }
}

/** One name's breakdown on the latest complete day, or null if it was not scored. */
export async function getCorrectionDetail(
  symbol: string,
): Promise<{ run: NarrativeRun; row: NarrativeDetail } | null> {
  "use cache";
  cacheLife("hours");
  cacheTag("correction-board", `correction:${symbol}`);
  try {
    const run = await latestRun();
    if (!run) return null;
    const query = (cols: string) =>
      createServiceClient()
        .schema(SCHEMA)
        .from("drawdown_narrative_scores")
        .select(cols)
        .eq("as_of", run.asOf)
        .eq("ticker", symbol)
        .limit(1);
    let { data, error } = await query(DETAIL_COLUMNS);
    if (missingColumn(error)) ({ data, error } = await query(BASE_DETAIL_COLUMNS));
    if (error || !data?.length) return null;
    const r = data[0] as unknown as Record<string, unknown>;
    return {
      run,
      row: {
        ...toRow(r),
        cashConversion: n(r.cash_conversion),
        cashMargin: n(r.cash_margin),
        cfoToNi: n(r.cfo_to_ni),
        accruals: n(r.accruals),
        sbcToRevenue: n(r.sbc_to_revenue),
        shareGrowth: n(r.share_growth),
        oneOffShare: n(r.one_off_share),
        qualityYears: n(r.quality_years),
        crux: s(r.crux),
        position: s(r.position),
        paysFor: toStrings(r.pays_for),
      },
    };
  } catch {
    return null;
  }
}

/** The headline lists: most cushion first / biggest shortfall first. */
export function topAndDrowning(rows: NarrativeRow[], k: number, exposure?: Exposure[]) {
  const ok = (r: NarrativeRow) => !exposure || exposure.includes(r.exposure);
  const top = rows
    .filter((r) => r.group === "on_top" && ok(r))
    .sort((a, b) => (b.breakevenCut ?? 0) - (a.breakevenCut ?? 0))
    .slice(0, k);
  const drowning = rows
    .filter((r) => r.group === "drowns" && ok(r))
    .sort((a, b) => (a.breakevenCut ?? 0) - (b.breakevenCut ?? 0))
    .slice(0, k);
  return { top, drowning };
}

