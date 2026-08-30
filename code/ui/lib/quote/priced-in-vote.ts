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
  /**
   * The individual published models behind the distribution, reconstructed.
   *
   * The counts above say three models call the price too cheap; these say WHICH
   * models, what each of them claims, and what the price's verdict on it is.
   * Ordered by target, high to low, so the list reads down the same axis as the
   * rail — a case's position in it is its position on the distribution.
   */
  cases: PricedInCase[];
};

/**
 * One published analyst model, reconstructed against the news corpus.
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
export type PricedInCase = {
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
  sources: string[];
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
export function verdictReason(c: PricedInCase, priceAtAsOf: number | null): string {
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
