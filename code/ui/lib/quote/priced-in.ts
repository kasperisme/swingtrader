import "server-only";
import { createServiceClient } from "@/lib/supabase/service";
import type {
  PricedInParts,
  PricedInSource,
  PricedInVote,
} from "./priced-in-vote";
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

// ── Landing-page showcase ─────────────────────────────────────────────────────

/**
 * One published reconstruction, flattened for marketing use.
 *
 * Deliberately NOT a `PricedInVote`: the showcase never renders drivers,
 * analyst cases or cited sources, and building those means parsing every case
 * and running the source-slug lookup — a lot of work for a card that shows a
 * rail and four bullets. The fields here are exactly what the landing page
 * draws, so a landing render costs two small queries and no JSON walking
 * beyond `summary_json`.
 */
export type PricedInHighlight = {
  ticker: string;
  asOf: string;
  nTargets: number;
  low: number;
  high: number;
  median: number;
  priceAtAsOf: number | null;
  medianGap: number | null;
  nEndorsed: number;
  nContestedBull: number;
  nContestedBear: number;
  parts: PricedInParts;
};

export type NarrativeShowcase = {
  /** The reconstruction the landing page reads in full. Null when none qualify. */
  featured: PricedInHighlight | null;
  /** Other covered names, newest first — the "and 200 more" proof strip. */
  others: string[];
  /** Distinct tickers carrying a published reconstruction right now. */
  totalCovered: number;
};

/**
 * Names a visitor recognises without being told what they are.
 *
 * The featured card has to teach "narrative trading" in one read, and it cannot
 * do that while the reader is still working out what the company sells. A
 * household name spends none of the reader's attention on the ticker and all of
 * it on the idea. Ordered by how widely held they are, and consulted only as a
 * PREFERENCE — the newest qualifying row wins if none of these are covered.
 */
const SHOWCASE_PREFERRED = [
  "AAPL", "NVDA", "MSFT", "TSLA", "AMZN", "GOOGL", "META", "NFLX",
  "AMD", "DIS", "MCD", "NKE", "SBUX", "KO", "BA", "UBER", "PLTR", "RIVN",
];

/** Enough published models that the distribution is a vote, not a handful. */
const SHOWCASE_MIN_TARGETS = 8;

function toHighlight(row: Record<string, unknown>): PricedInHighlight | null {
  const low = num(row.target_low);
  const high = num(row.target_high);
  const median = num(row.target_median);
  const nTargets = num(row.n_targets) ?? 0;
  if (low == null || high == null || median == null) return null;
  if (!(high > low) || nTargets < SHOWCASE_MIN_TARGETS) return null;

  // The showcase leads on the prose, so a row without it is worse than useless
  // here — it would render a rail under a heading promising a narrative.
  const parts = parseParts(row.summary_json);
  if (!parts?.position || !parts.paysFor.length || !parts.declines.length) {
    return null;
  }

  return {
    ticker: String(row.ticker),
    asOf: String(row.as_of),
    nTargets,
    low,
    high,
    median,
    priceAtAsOf: num(row.price),
    medianGap: num(row.median_gap),
    nEndorsed: num(row.n_endorsed) ?? 0,
    nContestedBull: num(row.n_rejected_bull) ?? 0,
    nContestedBear: num(row.n_rejected_bear) ?? 0,
    parts,
  };
}

const SHOWCASE_COLUMNS =
  "ticker, as_of, price, n_targets, target_low, target_high, target_median, " +
  "median_gap, n_rejected_bull, n_rejected_bear, n_endorsed, summary_json";

/**
 * The live example the landing page markets "narrative trading" with.
 *
 * Read fresh rather than hardcoded, so the card on the marketing page is the
 * same reconstruction a visitor lands on when they click through. A pinned
 * ticker would drift from the batch within a week and start advertising a
 * price that has since moved.
 *
 * Best-effort: every failure path returns an empty showcase, because the
 * landing page must render for a visitor whether or not this table answers.
 */
export async function getNarrativeShowcase(): Promise<NarrativeShowcase> {
  const empty: NarrativeShowcase = { featured: null, others: [], totalCovered: 0 };
  try {
    const supabase = createServiceClient();

    const [preferredRes, coveredRes] = await Promise.all([
      supabase
        .schema(SCHEMA)
        .from("research_priced_in")
        .select(SHOWCASE_COLUMNS)
        .eq("published", true)
        .in("ticker", SHOWCASE_PREFERRED)
        .order("as_of", { ascending: false })
        .order("created_at", { ascending: false })
        .limit(40),
      // Every covered name, one column wide. `count: "exact"` would count ROWS,
      // and a ticker holds several — a point-in-time run and a live one — so
      // "204 names covered" would be an overstatement of a headline figure. The
      // tickers are cheap enough to just fetch and count distinctly.
      supabase
        .schema(SCHEMA)
        .from("research_priced_in")
        .select("ticker, as_of")
        .eq("published", true)
        .order("as_of", { ascending: false })
        .limit(1000),
    ]);

    if (preferredRes.error) throw preferredRes.error;
    if (coveredRes.error) throw coveredRes.error;

    const preferred = (preferredRes.data ?? []) as unknown as Record<string, unknown>[];
    const covered = (coveredRes.data ?? []) as unknown as Record<string, unknown>[];

    // Newest-first already, so the first sighting of a ticker is its latest row.
    const seen = new Set<string>();
    for (const row of covered) {
      const t = String(row.ticker ?? "").toUpperCase();
      if (t) seen.add(t);
    }

    // Preference order, not recency, decides which household name leads —
    // otherwise the batch's run order picks the marketing example.
    const byRank = [...preferred].sort(
      (a, b) =>
        SHOWCASE_PREFERRED.indexOf(String(a.ticker)) -
        SHOWCASE_PREFERRED.indexOf(String(b.ticker)),
    );

    let featured: PricedInHighlight | null = null;
    for (const row of byRank) {
      featured = toHighlight(row);
      if (featured) break;
    }

    // No household name qualified — fall back to the newest row that does. Costs
    // a second full-column read, and only on the path where the first found
    // nothing renderable.
    if (!featured) {
      const { data } = await supabase
        .schema(SCHEMA)
        .from("research_priced_in")
        .select(SHOWCASE_COLUMNS)
        .eq("published", true)
        .order("as_of", { ascending: false })
        .order("created_at", { ascending: false })
        .limit(40);
      for (const row of (data ?? []) as unknown as Record<string, unknown>[]) {
        featured = toHighlight(row);
        if (featured) break;
      }
    }

    const others: string[] = [];
    for (const row of covered) {
      const t = String(row.ticker ?? "").toUpperCase();
      if (t && t !== featured?.ticker && !others.includes(t)) others.push(t);
      if (others.length >= 24) break;
    }

    return { featured, others, totalCovered: seen.size };
  } catch (e) {
    console.error("[priced-in] showcase query failed:", e);
    return empty;
  }
}
