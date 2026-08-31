/**
 * The priced-in vote's shape and its pure presentation helpers.
 *
 * Split out of `priced-in.ts` because that module is `server-only` — it holds
 * the service-role query — and the panel that renders a vote is now mounted
 * from a client component (the workspace's Priced-in tab) as well as from the
 * quote page's server render. Importing the query module from the client half
 * is a build error, and the right fix is that the *types and formatting* were
 * never server concerns to begin with.
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

export const STALE_AFTER_DAYS = 45;

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
  /**
   * The evidence behind this driver — one case per driver, or null.
   *
   * Null on two paths that must not be confused: a `priced-in/2` row predates
   * per-driver cases entirely, and a `priced-in/3` row only investigates the
   * least-priced N drivers, so a fully-priced one at the bottom of the list can
   * legitimately have none. Either way the UI shows the driver without a deep
   * dive rather than pretending the evidence is missing.
   */
  case: PricedInDriverCase | null;
};

/**
 * What is known about one driver: the coverage on it, and the data outside it.
 *
 * Three sources that answer different questions, and the UI has to keep them
 * apart exactly as `case.py` does:
 *
 *   `narrative`    how loudly the scored coverage speaks to this driver. This is
 *                  evidence of being KNOWN — and known is, by this programme's
 *                  governing assumption, already in the price. It is never
 *                  evidence that the driver is true.
 *   `evidenceFor` / `evidenceAgainst`  what the passages actually assert.
 *   `measurement`  the non-news series wired for the driver's observable. The
 *                  only source here that can speak to whether it is TRUE,
 *                  because it is the only one the market has not read. Usually
 *                  absent, and absence is stated rather than proxied.
 */
export type PricedInDriverCase = {
  /** What the market has been told about this driver, and how settled it is. */
  whatCoverageSays: string | null;
  evidenceFor: string[];
  evidenceAgainst: string[];
  /** What the wired series establishes — or that nothing is wired. */
  whatTheDataShows: string | null;
  /** The observation that would move this from argued to observed. */
  stillNeeded: string | null;
  /** The measured coverage read. Deterministic, not a model's impression. */
  narrative: {
    /** Claims in circulation about the company that were scanned. */
    scanned: number;
    /** Of those, how many clear this corpus's own relatedness bar. */
    related: number;
    /** Mean signed impact of the related claims, [-1, +1]. */
    netImpact: number;
    positive: number;
    negative: number;
    /** Set when nothing cleared the bar — the coverage does not speak to it. */
    note: string | null;
  } | null;
  /** Which series ran, or why none could. */
  measurement: {
    kind: string | null;
    /** True when a wired series exists for this observable. */
    testable: boolean;
    tool: string | null;
    /** Why it cannot be measured, when it cannot. */
    note: string | null;
    /** Whether the tool actually returned something. */
    ran: boolean;
  } | null;
  confidence: "high" | "medium" | "low" | null;
  nPassages: number;
  /** False when the corpus was too thin for retrieval to discriminate. */
  selective: boolean;
  distinctArticles: number | null;
  /** Headlines the reading drew on, linked to the article page when known. */
  sources: PricedInSource[];
  model: string | null;
};

/**
 * One cited headline.
 *
 * `slug` is null on two paths: a row written before the generator carried
 * slugs, and an article whose corpus row has none. The UI renders those as
 * plain text — a citation you cannot follow is still a citation, and a link to
 * nowhere is worse than no link.
 */
export type PricedInSource = { title: string; slug: string | null };

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
  /**
   * LEGACY. The published analyst models, reconstructed one per firm.
   *
   * This is what a case WAS, up to `priced-in/2`. The pipeline was inverted at
   * `priced-in/3`: the price is the vote, the drivers are what it decomposes
   * into, and a case is now the evidence behind one driver — carried on
   * `drivers[].case`, one each. These are kept only so the rows already
   * published keep rendering until the batch regenerates them, and they are
   * empty on every `/3` row.
   */
  analystCases: PricedInAnalystCase[];
};

/**
 * One published analyst model, reconstructed against the news corpus. LEGACY —
 * see `PricedInVote.analystCases`.
 *
 * The generator (`strategylab/social/case.py`) picks a handful of the models
 * behind the distribution — the consensus one the price is roughly paying, plus
 * the most-rejected bull and bear — and reconstructs each: what the analyst must
 * believe, the assumption it turns on, the counter-argument, and the one
 * observable OUTSIDE financial news that would settle it.
 *
 * Two tiers are mixed here and the UI must keep them apart. `stance`, `target`
 * and `impliedMove` are arithmetic on published numbers — the same grounded tier
 * as the distribution above. Everything else is a language model's
 * reconstruction, which is why it lives behind a disclosure rather than in the
 * summary line.
 */
export type PricedInAnalystCase = {
  firm: string;
  /** Often absent — FMP names the firm far more reliably than the analyst. */
  analyst: string | null;
  target: number;
  /** target / priceAtAsOf - 1. The whole verdict is a threshold on this. */
  impliedMove: number | null;
  stance: PricedInStance;
  /** What the analyst must believe to reach the target. */
  thesis: string | null;
  /** The single assumption the case turns on. */
  loadBearing: string | null;
  /**
   * For a rejected model, why a rational marginal buyer declines to pay it. For
   * an endorsed one, the schema field carries what the consensus takes for
   * granted instead — the same slot, a different question, so the label the UI
   * puts on it has to follow `stance`.
   */
  objection: string | null;
  /** The measurable that would settle it, deliberately outside financial news. */
  observable: string | null;
  /** Which wired data family the observable belongs to, e.g. `web_traffic`. */
  dataSource: string | null;
  evidenceFor: string[];
  evidenceAgainst: string[];
  confidence: "high" | "medium" | "low" | null;
  nPassages: number;
  /**
   * False when the corpus was too thin for retrieval to discriminate — a top-k
   * pull then returns most of what exists rather than a targeted set, so the
   * evidence is the company's general coverage, not evidence about this case.
   */
  selective: boolean;
  distinctArticles: number | null;
  /** Headlines the reconstruction drew on. */
  /** Headlines the reconstruction drew on, linked where the slug is known. */
  sources: PricedInSource[];
  /** A batch pass mixes backends, so the row says which model answered. */
  model: string | null;
};

/** |move| <= 8% priced, >= 15% rejected, and the band between the two. */
export type PricedInStance =
  | "endorsed"
  | "neutral"
  | "rejected_bull"
  | "rejected_bear";

export const ENDORSED_BAND = 0.08;
export const REJECTED_MIN_MOVE = 0.15;

export type CaseVerdict = {
  label: string;
  /** What the label means, in the same voice as the rest of the panel. */
  gloss: string;
  /** Sequential emphasis, not polarity: a rejected model is not a bad model. */
  dot: string;
  text: string;
};

/**
 * The verdict on one published model — and it is the PRICE's verdict, not ours.
 *
 * Every branch is a threshold on one number the market set, which is what makes
 * this the grounded tier: no judgement of whether the analyst is right, only
 * whether the market is paying them. The reconstruction below a card explains
 * what the model claims; it never moves the verdict.
 */
export function caseVerdict(stance: PricedInStance): CaseVerdict {
  switch (stance) {
    case "endorsed":
      return {
        label: "Priced in",
        gloss: "the market is paying about this number",
        dot: "bg-muted-foreground/40",
        text: "text-muted-foreground",
      };
    case "neutral":
      return {
        label: "Close to priced",
        gloss: "near the price, but not the number it is paying",
        dot: "bg-[#f59e0b] dark:bg-[#d97706]",
        text: "text-muted-foreground",
      };
    case "rejected_bull":
      return {
        label: "Not paid for",
        gloss: "published, and the market declines this upside",
        dot: "bg-[#b45309] dark:bg-[#fbbf24]",
        text: "text-[#b45309] dark:text-[#fbbf24]",
      };
    case "rejected_bear":
      return {
        label: "Not accepted",
        gloss: "published, and the market declines this downside",
        dot: "bg-[#b45309] dark:bg-[#fbbf24]",
        text: "text-[#b45309] dark:text-[#fbbf24]",
      };
  }
}

/** The arithmetic behind the verdict, spelled out so it can be checked. */
export function verdictReason(
  c: PricedInAnalystCase,
  priceAtAsOf: number | null,
): string {
  const at =
    priceAtAsOf != null && Number.isFinite(priceAtAsOf)
      ? `the ${new Intl.NumberFormat(undefined, {
          style: "currency",
          currency: "USD",
          maximumFractionDigits: priceAtAsOf >= 100 ? 0 : 2,
        }).format(priceAtAsOf)} price this was computed at`
      : "the price this was computed at";
  const move =
    c.impliedMove == null
      ? null
      : `${c.impliedMove > 0 ? "+" : ""}${(c.impliedMove * 100).toFixed(0)}%`;
  if (move == null) return `Position against ${at} is unavailable.`;
  switch (c.stance) {
    case "endorsed":
      return `This target is ${move} from ${at} — inside the ±8% band, so the market is paying roughly what this model says.`;
    case "neutral":
      return `This target is ${move} from ${at} — outside the ±8% band the price pays, but short of the 15% that counts as a model the market is refusing.`;
    case "rejected_bull":
      return `This target is ${move} above ${at}. It was published, so the market has seen it and declines to pay it — the argument is known and not believed.`;
    case "rejected_bear":
      return `This target is ${move} below ${at}. It was published, so the market has seen it and declines to accept it — the warning is known and not believed.`;
  }
}

// ---------------------------------------------------------------------------
// Parsing.
//
// These live here rather than beside the query for the same reason the types
// do: turning a stored jsonb row into the shape above is not a server concern,
// and keeping it out of the `server-only` module is what lets it be tested
// without a database. `priced-in.ts` imports them and does nothing but the
// query and the arithmetic around it.
// ---------------------------------------------------------------------------

function strList(v: unknown): string[] {
  return Array.isArray(v)
    ? v.filter((x): x is string => typeof x === "string" && x.trim().length > 0)
    : [];
}

/** Null when the row predates the structured summary, so the UI can fall back. */
export function parseParts(raw: unknown): PricedInParts | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const d = raw as Record<string, unknown>;
  const position = typeof d.position === "string" ? d.position.trim() : "";
  const crux = typeof d.crux === "string" ? d.crux.trim() : "";
  const paysFor = strList(d.pays_for);
  const declines = strList(d.declines);
  if (!position && !crux && !paysFor.length && !declines.length) return null;
  return { position: position || null, paysFor, declines, crux: crux || null };
}

/**
 * The drivers, each carrying the case that investigated it.
 *
 * The join is `driver_index` — a position into THIS array as the generator
 * emitted it — so the cases have to be attached before the array is reordered
 * for display. Sorting first and matching afterwards would pair each case with
 * whichever driver happened to land in its old slot, which is exactly the
 * mispairing this rewrite exists to remove.
 *
 * Tolerant of a missing or malformed array — a bad row yields no drivers, not a
 * crash.
 */
export function parseDrivers(raw: unknown, casesRaw: unknown): PricedInDriver[] {
  if (!Array.isArray(raw)) return [];
  const byIndex = parseDriverCases(casesRaw);
  const out: PricedInDriver[] = [];
  for (const [i, item] of raw.entries()) {
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
      case: byIndex.get(i) ?? null,
    });
  }
  // Least-priced first: what the price does NOT reflect is the end worth reading.
  return out.sort((a, b) => a.pricedInPct - b.pricedInPct);
}

/**
 * The per-driver cases (`priced-in/3`), keyed by the driver index they belong to.
 *
 * A case whose reading failed carries the failure in its own text — the
 * generator writes "reading failed: …" and marks it `not_explicable` — so it is
 * dropped rather than shown. Its deterministic halves are dropped with it: a
 * coverage count with no reading around it is a number the reader cannot use.
 */
export function parseDriverCases(raw: unknown): Map<number, PricedInDriverCase> {
  const out = new Map<number, PricedInDriverCase>();
  if (!Array.isArray(raw)) return out;
  for (const item of raw) {
    if (!item || typeof item !== "object") continue;
    const d = item as Record<string, unknown>;
    const idx = num(d.driver_index);
    // `firm` marks a legacy analyst case; those never belong to a driver.
    if (idx == null || !Number.isInteger(idx) || idx < 0 || d.firm) continue;
    const confidence = str(d.confidence);
    if (confidence === "not_explicable") continue;
    const says = str(d.what_coverage_says);
    if (!says) continue;

    const nar = obj(d.narrative);
    const mes = obj(d.measurement);
    const retrieval = obj(d.retrieval);

    out.set(idx, {
      whatCoverageSays: says,
      evidenceFor: strList(d.evidence_for),
      evidenceAgainst: strList(d.evidence_against),
      whatTheDataShows: str(d.what_the_data_shows),
      stillNeeded: str(d.still_needed),
      narrative: nar
        ? {
            scanned: num(nar.n_claims_scanned) ?? 0,
            related: num(nar.n_related) ?? 0,
            netImpact: num(nar.net_impact) ?? 0,
            positive: num(nar.positive) ?? 0,
            negative: num(nar.negative) ?? 0,
            note: str(nar.note),
          }
        : null,
      measurement: mes
        ? {
            kind: str(mes.kind),
            testable: mes.testable === true,
            tool: str(mes.tool),
            note: str(mes.error) ?? str(mes.note),
            // `result` is the tool's own payload and is not rendered — the
            // reading already says what it showed, and a raw series on a quote
            // page is noise. What matters here is only whether one exists.
            ran: mes.result != null,
          }
        : null,
      confidence:
        confidence === "high" || confidence === "medium" || confidence === "low"
          ? confidence
          : null,
      nPassages: num(d.n_passages) ?? 0,
      selective: retrieval ? retrieval.selective !== false : true,
      distinctArticles: retrieval ? num(retrieval.distinct_articles) : null,
      sources: parseSources(d.sources),
      model: str(d.model),
    });
  }
  return out;
}

/**
 * Cited headlines, in either shape the column holds.
 *
 * `priced-in/3` writes `{title, slug}`; everything before it wrote a bare
 * title. Both are read here rather than migrating the stored rows, because the
 * bare-title rows are still the ones on the page until the batch comes round
 * again — and their slugs can be recovered by title at query time.
 */
export function parseSources(raw: unknown): PricedInSource[] {
  if (!Array.isArray(raw)) return [];
  const out: PricedInSource[] = [];
  for (const item of raw) {
    if (typeof item === "string") {
      const title = item.trim();
      if (title) out.push({ title, slug: null });
      continue;
    }
    const o = obj(item);
    const title = o ? str(o.title) : null;
    if (title) out.push({ title, slug: o ? str(o.slug) : null });
  }
  return out.slice(0, 6);
}

/** A plain JSON object, or null — arrays and scalars are not one. */
export function obj(v: unknown): Record<string, unknown> | null {
  return v && typeof v === "object" && !Array.isArray(v)
    ? (v as Record<string, unknown>)
    : null;
}

export function num(v: unknown): number | null {
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

export function str(v: unknown): string | null {
  return typeof v === "string" && v.trim() ? v.trim() : null;
}

const STANCES: PricedInStance[] = [
  "endorsed",
  "neutral",
  "rejected_bull",
  "rejected_bear",
];

/**
 * LEGACY (`priced-in/2`): the reconstructed analyst cases.
 *
 * Two things are dropped rather than rendered. A case whose reconstruction
 * failed carries its own failure in the `case` field — the generator writes
 * "reconstruction failed: …" there and marks it `not_explicable` — and putting
 * that on a public page shows the reader a broken pipeline instead of an
 * analysis. A case with no firm or no target cannot be matched to a point on
 * the rail, which is the whole reason it is here.
 */
export function parseAnalystCases(raw: unknown): PricedInAnalystCase[] {
  if (!Array.isArray(raw)) return [];
  const out: PricedInAnalystCase[] = [];
  for (const item of raw) {
    if (!item || typeof item !== "object") continue;
    const d = item as Record<string, unknown>;
    const firm = str(d.firm);
    const target = num(d.target);
    const stance = STANCES.find((s) => s === d.stance);
    const confidence = str(d.confidence);
    if (!firm || target == null || !stance) continue;
    if (confidence === "not_explicable") continue;
    const thesis = str(d.case);
    if (!thesis) continue;

    const retrieval =
      d.retrieval && typeof d.retrieval === "object" && !Array.isArray(d.retrieval)
        ? (d.retrieval as Record<string, unknown>)
        : {};

    out.push({
      firm,
      analyst: str(d.analyst),
      target,
      impliedMove: num(d.implied_move),
      stance,
      thesis,
      loadBearing: str(d.load_bearing),
      objection: str(d.market_objection),
      observable: str(d.observable),
      dataSource: str(d.data_source),
      evidenceFor: strList(d.evidence_for),
      evidenceAgainst: strList(d.evidence_against),
      confidence:
        confidence === "high" || confidence === "medium" || confidence === "low"
          ? confidence
          : null,
      nPassages: num(d.n_passages) ?? 0,
      // Absent means nothing was recorded, and an unrecorded warning must not
      // read as a clean bill of health — default to selective only when the
      // generator said so.
      selective: retrieval.selective !== false,
      distinctArticles: num(retrieval.distinct_articles),
      sources: parseSources(d.sources),
      model: str(d.model),
    });
  }
  // Highest target first, so the list reads top-to-bottom down the same axis as
  // the distribution rail and a case's rank is its position on it.
  return out.sort((a, b) => b.target - a.target).slice(0, 6);
}
