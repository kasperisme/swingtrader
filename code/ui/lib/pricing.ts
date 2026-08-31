/**
 * The launch-phase price table — the one place a price is written down.
 *
 * Four surfaces quote the current price to a user: the landing tier card, the
 * /pricing timeline and its comparison table, the pricing checkout buttons, and
 * the onboarding plan step. Each of them used to hold its own literal, and
 * advancing from phase 1 to phase 2 updated three of the four — leaving the
 * onboarding picker offering $9/mo on the same account that had just been shown
 * $29 on the way in.
 *
 * So the phase is declared ONCE, here, and every price is looked up from it.
 * Moving to phase 3 is a one-line change to `CURRENT_PHASE_INDEX`.
 *
 * IMPORTANT — this table is what the product SAYS. What a customer is actually
 * charged is the Stripe price object behind `STRIPE_<PLAN>_<INTERVAL>_PRICE_ID`,
 * and nothing here can change that. The two are only in agreement because
 * someone kept them in agreement: before flipping `PRELAUNCH_OPEN_ACCESS` to
 * false, check the live amounts (`getPlanOptions()` reads them straight from
 * Stripe) against `currentMonthly`/`currentAnnual` below.
 */

export type PricedTierId = "observer" | "investor" | "trader";

/**
 * Which phase is on sale, 0-based. 0 = "Phase 1", 1 = "Phase 2", 2 = "Phase 3".
 *
 * MUST match the prices behind the live `STRIPE_*_PRICE_ID` env vars. The live
 * deployment points at the Phase 1 objects ($9 / $99 / $19 / $199), so this is
 * 0. Moving it without creating the matching Stripe prices first makes the site
 * advertise a rate Checkout will not charge — which is what happened when this
 * was briefly set to 1.
 */
export const CURRENT_PHASE_INDEX = 0;

export const PHASE_COUNT = 3;

/** Where a phase sits relative to the one currently on sale. */
export type PhaseStatus = "finished" | "current" | "upcoming";

export function phaseStatus(index: number): PhaseStatus {
  if (index < CURRENT_PHASE_INDEX) return "finished";
  if (index === CURRENT_PHASE_INDEX) return "current";
  return "upcoming";
}

type PhasePrices = {
  /** Monthly price in whole dollars, indexed by phase. */
  monthlyByPhase: number[];
  /** Annual price in whole dollars, indexed by phase. */
  annualByPhase: number[];
  /** The annual line as shown, indexed by phase. */
  annualLabelByPhase: string[];
};

export const PRICE_TABLE: Record<PricedTierId, PhasePrices> = {
  observer: {
    monthlyByPhase: [0, 0, 0],
    annualByPhase: [0, 0, 0],
    annualLabelByPhase: ["Always free", "Always free", "Always free"],
  },
  investor: {
    monthlyByPhase: [9, 29, 39],
    annualByPhase: [99, 299, 399],
    annualLabelByPhase: ["$99/yr · lock in forever", "$299/yr", "$399/yr"],
  },
  trader: {
    monthlyByPhase: [19, 49, 69],
    annualByPhase: [199, 499, 699],
    annualLabelByPhase: ["$199/yr · lock in forever", "$499/yr", "$699/yr"],
  },
};

/** Monthly price of a tier in the phase that is currently on sale. */
export function currentMonthly(tier: PricedTierId): number {
  return PRICE_TABLE[tier].monthlyByPhase[CURRENT_PHASE_INDEX] ?? 0;
}

/** Annual price of a tier in the phase that is currently on sale. */
export function currentAnnual(tier: PricedTierId): number {
  return PRICE_TABLE[tier].annualByPhase[CURRENT_PHASE_INDEX] ?? 0;
}

/** The annual line for the phase currently on sale, e.g. "$299/yr · lock in forever". */
export function currentAnnualLabel(tier: PricedTierId): string {
  return PRICE_TABLE[tier].annualLabelByPhase[CURRENT_PHASE_INDEX] ?? "";
}

/** Final-phase monthly price — what the current rate is a discount against. */
export function finalMonthly(tier: PricedTierId): number {
  return PRICE_TABLE[tier].monthlyByPhase[PHASE_COUNT - 1] ?? 0;
}

/** Final-phase annual price. */
export function finalAnnual(tier: PricedTierId): number {
  return PRICE_TABLE[tier].annualByPhase[PHASE_COUNT - 1] ?? 0;
}
