/**
 * The article page's lead: the IMPACT_SUMMARY head, which reads every other
 * head plus each affected company's latest priced-in reconstruction and says
 * what the article means once you account for what the price already assumes.
 *
 * Written by code/analytics/services/news/scoring/impact_summary.py:
 *   scores_json    {TICKER: impact in priced-in context, −1…+1}
 *   reasoning_json {"_summary": overall read, TICKER: per-ticker read}
 *   meta_json      {TICKER: {relation, assumption?, priced_in_as_of?, priced_in_id?}}
 *
 * Pure — no I/O — so the page stays a thin renderer (tests in
 * __tests__/impact-summary.test.ts).
 */

export type Relation =
  | "confirms"
  | "challenges"
  | "new_information"
  | "not_material"
  | "no_reconstruction";

export type ImpactSummaryTicker = {
  ticker: string;
  score: number;
  relation: Relation;
  /** The pays-for / declines item the article touches, when there is one. */
  assumption: string | null;
  read: string;
  /** Date of the reconstruction it was read against; null = none on file. */
  pricedInAsOf: string | null;
};

export type ImpactSummary = {
  summary: string;
  tickers: ImpactSummaryTicker[];
};

const SUMMARY_KEY = "_summary";
const RELATIONS = new Set<Relation>([
  "confirms",
  "challenges",
  "new_information",
  "not_material",
  "no_reconstruction",
]);

/** Reconstruction-backed reads first, then by magnitude. */
const MAX_TICKERS = 3;

function obj(v: unknown): Record<string, unknown> {
  if (!v) return {};
  if (typeof v === "string") {
    try {
      return obj(JSON.parse(v));
    } catch {
      return {};
    }
  }
  return typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
}

export function parseImpactSummary(head: {
  scores_json: unknown;
  reasoning_json: unknown;
  meta_json?: unknown;
} | null | undefined): ImpactSummary | null {
  if (!head) return null;
  const scores = obj(head.scores_json);
  const reasoning = obj(head.reasoning_json);
  const meta = obj(head.meta_json);

  const summary = String(reasoning[SUMMARY_KEY] ?? "").trim();
  if (!summary) return null;

  const tickers: ImpactSummaryTicker[] = [];
  for (const [ticker, raw] of Object.entries(scores)) {
    const score = Number(raw);
    if (!Number.isFinite(score)) continue;
    const m = obj(meta[ticker]);
    const asOf = typeof m.priced_in_as_of === "string" && m.priced_in_as_of ? m.priced_in_as_of : null;
    const rel = String(m.relation ?? "");
    // Rows written before the head set no_reconstruction itself carry the
    // model's guess ("not_material", assumption "unknown"). No reconstruction
    // date means there was nothing to relate to, whatever the label says.
    const relation: Relation = !asOf
      ? "no_reconstruction"
      : RELATIONS.has(rel as Relation)
        ? (rel as Relation)
        : "not_material";
    const assumption = asOf && typeof m.assumption === "string" ? m.assumption.trim() : "";
    tickers.push({
      ticker: ticker.toUpperCase(),
      score: Math.max(-1, Math.min(1, score)),
      relation,
      assumption: assumption && !/^(unknown|none|n\/a)$/i.test(assumption) ? assumption : null,
      read: String(reasoning[ticker] ?? "").trim(),
      pricedInAsOf: asOf,
    });
  }

  tickers.sort(
    (a, b) =>
      Number(b.pricedInAsOf != null) - Number(a.pricedInAsOf != null) ||
      Math.abs(b.score) - Math.abs(a.score),
  );

  return { summary, tickers: tickers.slice(0, MAX_TICKERS) };
}
