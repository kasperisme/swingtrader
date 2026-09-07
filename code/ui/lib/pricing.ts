/**
 * The price table — the one place a price is written down.
 *
 * Four surfaces quote the price to a user: the landing tier card, the /pricing
 * cards and comparison table, the pricing checkout buttons, and the onboarding
 * plan step. Each of them used to hold its own literal, and a price change
 * updated three of the four — leaving the onboarding picker offering $9/mo on
 * the same account that had just been shown $29 on the way in. So it is
 * declared ONCE, here, and every surface looks it up.
 *
 * This used to be a three-phase launch ladder ($9 → $29 → $39) with a timeline
 * on /pricing and a `CURRENT_PHASE_INDEX` to advance. That is gone: the price
 * is not going up again, so promising a rise was a countdown the product had no
 * intention of running. Existing subscribers on the old $9/$19 rate keep it —
 * that is the `grandfathered` column on their subscription row, not anything
 * this table has to model.
 *
 * IMPORTANT — this table is what the product SAYS. What a customer is actually
 * charged is the Stripe price object behind `STRIPE_<PLAN>_<INTERVAL>_PRICE_ID`,
 * and nothing here can change that. The two are only in agreement because
 * someone kept them in agreement: after editing an amount below, check it
 * against the live one (`getPlanOptions()` reads them straight from Stripe).
 * /protected/profile is exempt — it reports Stripe's own `unit_amount` and so
 * cannot disagree with what is charged; only the marketing surfaces can.
 */

export type PricedTierId = "observer" | "investor" | "trader";

type TierPrices = {
  /** Monthly price in whole dollars. */
  monthly: number;
  /** Annual price in whole dollars. */
  annual: number;
};

export const PRICES: Record<PricedTierId, TierPrices> = {
  observer: { monthly: 0, annual: 0 },
  investor: { monthly: 29, annual: 299 },
  trader: { monthly: 49, annual: 499 },
};

/** Monthly price of a tier, in whole dollars. */
export function monthlyPrice(tier: PricedTierId): number {
  return PRICES[tier].monthly;
}

/** Annual price of a tier, in whole dollars. */
export function annualPrice(tier: PricedTierId): number {
  return PRICES[tier].annual;
}

/** The annual line as shown under the monthly price, e.g. "$299/yr". */
export function annualLabel(tier: PricedTierId): string {
  const annual = PRICES[tier].annual;
  return annual === 0 ? "Always free" : `$${annual}/yr`;
}

/**
 * How much the annual plan saves against paying monthly, as a whole percent.
 * 0 for a free tier, so callers can hide the badge on a falsy value.
 */
export function annualSavingPct(tier: PricedTierId): number {
  const { monthly, annual } = PRICES[tier];
  if (monthly === 0 || annual === 0) return 0;
  const yearOfMonths = monthly * 12;
  return Math.round(((yearOfMonths - annual) / yearOfMonths) * 100);
}
