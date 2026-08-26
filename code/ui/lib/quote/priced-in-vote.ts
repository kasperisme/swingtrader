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
};
