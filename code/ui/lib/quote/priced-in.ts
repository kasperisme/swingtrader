import "server-only";
import { createServiceClient } from "@/lib/supabase/service";

/**
 * Where a stock's price sits among the analyst models published about it.
 *
 * This is the GROUNDED tier of the priced-in programme (`strategylab/social/`,
 * written up in `research/PRICED-IN-FINDINGS.md`) and it is deliberately the
 * only tier this page reads.
 *
 * The programme produces three tiers of number and they are not equally solid:
 *
 *   grounded   the model spread, the median, where the price sits among them.
 *              Arithmetic on other people's published targets. No model
 *              judgement anywhere in it.
 *   assumption-sensitive   a reverse-DCF implied growth path. Correct
 *              arithmetic, fragile inputs — one company's implied CAGR moved
 *              nine points across three dates purely on which year's free cash
 *              flow margin anchored it.
 *   judged     per-driver "this is 25% priced in" percentages. UNVALIDATED, and
 *              not merely untested: two separate attempts to validate them
 *              failed, the second producing three believable numbers in a row
 *              that were all measurement artefacts.
 *
 * Only the first is exposed here. Publishing the third on a public quote page
 * would put an unvalidated language-model estimate next to a real share price,
 * where it would read as analysis.
 */

/**
 * Substitute the `{price}` token the generator writes in place of a literal
 * share price. Baking the price into prose makes it wrong the next day, and it
 * is the one figure already shown accurately elsewhere on the page.
 */
export function injectPrice(text: string, price: number | null): string {
  if (!text.includes("{price}")) return text;
  const shown =
    price != null && Number.isFinite(price)
      ? new Intl.NumberFormat(undefined, {
          style: "currency",
          currency: "USD",
          maximumFractionDigits: price >= 100 ? 0 : 2,
        }).format(price)
      : "the current price";
  return text.replaceAll("{price}", shown);
}

export type PricedInDriver = {
  /** The assumption itself — what the price does or does not underwrite. */
  driver: string;
  segment: string | null;
  /**
   * 0-100. How much of this driver's plausible value the price already
   * reflects. THIS IS AN UNVALIDATED ESTIMATE — see the note on the type below.
   */
  pricedInPct: number;
  /** What it is worth as a % of price if it proves out, bounded by the model spread. */
  valueIfTruePct: number | null;
  /** The evidence the estimate rests on — a number from the arithmetic or a passage. */
  basis: string | null;
  /** Whether any wired data source can actually settle it. Often false. */
  testable: boolean;
  observable: string | null;
};

export type PricedInParts = {
  /** One sentence: where the price sits versus the published models. */
  position: string | null;
  paysFor: string[];
  declines: string[];
  /** The single investigable question, and whether anything wired settles it. */
  crux: string | null;
};

export type PricedInVote = {
  ticker: string;
  /** Date the reconstruction was computed — NOT necessarily today. */
  asOf: string;
  /** The price it was computed at. Compare with the live quote before trusting it. */
  priceAtAsOf: number | null;
  nTargets: number;
  low: number;
  high: number;
  median: number;
  /** priceAtAsOf / median - 1. Negative = the market pays below the median model. */
  medianGap: number | null;
  /** Published models implying >= +15% that the price declines to pay. */
  nContestedBull: number;
  /** Published models implying <= -15% that the price declines to accept. */
  nContestedBear: number;
  /** Models within +/-8% of the price — what it is roughly paying. */
  nEndorsed: number;
  /** Days between asOf and now. The panel says so when this is large. */
  ageDays: number;
  /**
   * The written reconstruction: what the price pays for, what it declines, and
   * which of the open questions can actually be measured. Grounded in the
   * arithmetic above and in the published models — but written by a language
   * model, so the panel attributes it rather than presenting it as house view.
   */
  summary: string | null;
  /** The same reconstruction split into its four parts, when the row has them. */
  parts: PricedInParts | null;
  /**
   * Per-assumption estimates of how much the price already reflects.
   *
   * These are the JUDGED tier and they are unvalidated — not merely untested.
   * Two attempts to validate them failed: implied-CAGR as a signal came back
   * negative over 188 observations, and testing the percentages against the
   * size of the price reaction when matching news arrived produced a
   * correlation that changed sign across parameter settings and sat inside its
   * own placebo null. A third test — locked forward predictions — is open and
   * does not resolve until Dec 2026.
   *
   * They are exposed because the structure (which assumptions, and which of
   * them anything can measure) is useful even where the percentage is not. The
   * UI must carry that distinction; see `priced-in-panel.tsx`.
   */
  drivers: PricedInDriver[];
};

const SCHEMA = "swingtrader";
/** Past this, the reconstruction describes a different price than today's. */
export const STALE_AFTER_DAYS = 45;

function strList(v: unknown): string[] {
  return Array.isArray(v)
    ? v.filter((x): x is string => typeof x === "string" && x.trim().length > 0)
    : [];
}

/** Null when the row predates the structured summary, so the UI can fall back. */
function parseParts(raw: unknown): PricedInParts | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const d = raw as Record<string, unknown>;
  const position = typeof d.position === "string" ? d.position.trim() : "";
  const crux = typeof d.crux === "string" ? d.crux.trim() : "";
  const paysFor = strList(d.pays_for);
  const declines = strList(d.declines);
  if (!position && !crux && !paysFor.length && !declines.length) return null;
  return { position: position || null, paysFor, declines, crux: crux || null };
}

/** Tolerant of a missing or malformed array — a bad row yields no drivers, not a crash. */
function parseDrivers(raw: unknown): PricedInDriver[] {
  if (!Array.isArray(raw)) return [];
  const out: PricedInDriver[] = [];
  for (const item of raw) {
    if (!item || typeof item !== "object") continue;
    const d = item as Record<string, unknown>;
    const label = typeof d.driver === "string" ? d.driver.trim() : "";
    const pct = num(d.priced_in_pct);
    if (!label || pct == null) continue;
    out.push({
      driver: label,
      segment: typeof d.segment === "string" && d.segment.trim() ? d.segment.trim() : null,
      pricedInPct: Math.max(0, Math.min(100, pct)),
      valueIfTruePct: num(d.value_if_true_pct),
      basis: typeof d.basis === "string" && d.basis.trim() ? d.basis.trim() : null,
      testable: d.testable === true,
      observable:
        typeof d.observable === "string" && d.observable.trim()
          ? d.observable.trim()
          : null,
    });
  }
  // Least-priced first: what the price does NOT reflect is the end worth reading.
  return out.sort((a, b) => a.pricedInPct - b.pricedInPct);
}

function num(v: unknown): number | null {
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

/**
 * Latest published reconstruction for a ticker, or null.
 *
 * Reads only `published = true`, matching the rest of the `research_*` family:
 * nothing is visible until someone decides it is. A row exists for every ticker
 * the programme has run, so an empty result here means the publish flag was not
 * set, not that the analysis is missing.
 */
export async function getPricedInVote(
  symbol: string,
): Promise<PricedInVote | null> {
  const ticker = symbol.trim().toUpperCase();
  if (!ticker) return null;

  const supabase = createServiceClient();
  const { data, error } = await supabase
    .schema(SCHEMA)
    .from("research_priced_in")
    .select(
      "ticker, as_of, price, n_targets, target_low, target_high, target_median, " +
        "median_gap, n_rejected_bull, n_rejected_bear, n_endorsed, summary, " +
        "summary_json, drivers_json, published",
    )
    .eq("ticker", ticker)
    .eq("published", true)
    // A ticker can hold several published rows — a point-in-time run and a live
    // one, or two pipeline versions at the same as_of. Ordering on `as_of`
    // alone leaves same-day rows in arbitrary order, which is how a stale
    // unstructured row wins over the regenerated one. `created_at` breaks the
    // tie toward whatever was written most recently.
    .order("as_of", { ascending: false })
    .order("created_at", { ascending: false })
    .limit(1)
    .maybeSingle();

  if (error) {
    console.error("[priced-in] query failed:", error);
    return null;
  }
  if (!data) return null;

  // The generated Supabase types predate this table, so the client widens the
  // row to an error shape. Narrowing here rather than regenerating types keeps
  // this change to one file; the runtime shape is guaranteed by the migration.
  const row = data as unknown as Record<string, unknown>;

  const low = num(row.target_low);
  const high = num(row.target_high);
  const median = num(row.target_median);
  const nTargets = num(row.n_targets) ?? 0;

  // A distribution needs a real spread to be worth drawing. Below five models
  // it is a handful of stale numbers rather than a vote, which is the same
  // floor the analysis itself applies.
  if (low == null || high == null || median == null || nTargets < 5) return null;
  if (!(high > low)) return null;

  const asOf = String(row.as_of);
  const ageDays = Math.max(
    0,
    Math.round((Date.now() - new Date(asOf + "T00:00:00Z").getTime()) / 86_400_000),
  );

  return {
    ticker: String(row.ticker),
    asOf,
    priceAtAsOf: num(row.price),
    nTargets,
    low,
    high,
    median,
    medianGap: num(row.median_gap),
    nContestedBull: num(row.n_rejected_bull) ?? 0,
    nContestedBear: num(row.n_rejected_bear) ?? 0,
    nEndorsed: num(row.n_endorsed) ?? 0,
    ageDays,
    summary: typeof row.summary === "string" && row.summary.trim()
      ? row.summary.trim()
      : null,
    drivers: parseDrivers(row.drivers_json),
    parts: parseParts(row.summary_json),
  };
}
