import "server-only";
import { createServiceClient } from "@/lib/supabase/service";
import type { PricedInSource, PricedInVote } from "./priced-in-vote";
import {
  num,
  parseAnalystCases,
  parseDrivers,
  parseParts,
} from "./priced-in-vote";

// The vote's shape and its formatting helpers live in a client-safe module now;
// re-exported here so `getPricedInVote`'s callers still get everything from one
// import.
export {
  caseVerdict,
  injectPrice,
  STALE_AFTER_DAYS,
  verdictReason,
  parseAnalystCases,
  parseDrivers,
  parseParts,
  type CaseVerdict,
  type PricedInAnalystCase,
  type PricedInDriverCase,
  type PricedInDriver,
  type PricedInParts,
  type PricedInStance,
  type PricedInVote,
} from "./priced-in-vote";

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

const SCHEMA = "swingtrader";
/** Past this, the reconstruction describes a different price than today's. */


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
        "summary_json, drivers_json, cases_json, published",
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

  const drivers = parseDrivers(row.drivers_json, row.cases_json);
  const analystCases = parseAnalystCases(row.cases_json);
  await linkSources(supabase, [
    ...drivers.flatMap((d) => d.case?.sources ?? []),
    ...analystCases.flatMap((c) => c.sources),
  ]);

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
    drivers,
    parts: parseParts(row.summary_json),
    analystCases,
  };
}

/**
 * Fill in the slugs for cited headlines that were stored without one.
 *
 * The generator carries `{title, slug}` from `priced-in/3` onward, but every
 * row written before that stored a bare title — and those are the rows on the
 * page until the batch comes round again, which for the full universe is about
 * a week. Rather than migrate the stored JSON, the titles are resolved here in
 * one query, so a citation becomes a link the moment this ships.
 *
 * Mutates in place, deliberately: the sources are already the objects the
 * caller is about to return, and rebuilding the driver tree to attach six
 * strings would be a lot of copying for nothing.
 *
 * Best-effort throughout. A title that does not resolve keeps `slug: null` and
 * renders as plain text, which is the same outcome as before this existed.
 */
async function linkSources(
  supabase: ReturnType<typeof createServiceClient>,
  sources: PricedInSource[],
): Promise<void> {
  const missing = sources.filter((s) => !s.slug);
  if (missing.length === 0) return;
  const titles = [...new Set(missing.map((s) => s.title))];

  const { data, error } = await supabase
    .schema(SCHEMA)
    .from("news_articles")
    .select("title, slug")
    .in("title", titles);

  if (error) {
    // A citation that does not link is a smaller failure than a quote page
    // that does not render, so this never throws.
    console.error("[priced-in] source slug lookup failed:", error);
    return;
  }

  const bySlug = new Map<string, string>();
  for (const r of (data ?? []) as { title: string | null; slug: string | null }[]) {
    // First wins: syndicated copies share a title, and any of them is the
    // article the reader wants.
    if (r.title && r.slug && !bySlug.has(r.title)) bySlug.set(r.title, r.slug);
  }
  for (const s of missing) s.slug = bySlug.get(s.title) ?? null;
}
