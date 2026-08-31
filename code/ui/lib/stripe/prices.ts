import { unstable_cache } from "next/cache";
import { getStripe } from "@/lib/stripe/client";

export type Plan = "investor" | "trader";
export type BillingInterval = "monthly" | "annual";

export const PLANS: Plan[] = ["investor", "trader"];
export const INTERVALS: BillingInterval[] = ["monthly", "annual"];

export function getPriceId(plan: Plan, interval: BillingInterval): string {
  const key = `STRIPE_${plan.toUpperCase()}_${interval.toUpperCase()}_PRICE_ID`;
  const value = process.env[key];
  if (!value) throw new Error(`Missing env var: ${key}`);
  return value;
}

/** Entitlement rank among the paid plans — higher = more access. */
const PLAN_RANK: Record<Plan, number> = { investor: 0, trader: 1 };

export interface PlanSelection {
  plan: Plan;
  interval: BillingInterval;
}

/**
 * When a plan change should take effect.
 *
 * - `immediate`  — the customer gains access now and Stripe prorates (they pay
 *                  the difference for the rest of the period, or bank a credit).
 * - `period_end` — the customer keeps what they already paid for and the new
 *                  price starts at the next renewal. Used whenever the change
 *                  *reduces* what they get: a lower tier, or trading a paid-up
 *                  year for month-to-month.
 */
export type ChangeTiming = "immediate" | "period_end";

export function changeTiming(from: PlanSelection, to: PlanSelection): ChangeTiming {
  if (PLAN_RANK[to.plan] > PLAN_RANK[from.plan]) return "immediate";
  if (PLAN_RANK[to.plan] < PLAN_RANK[from.plan]) return "period_end";
  // Same tier: only annual → monthly gives up time already paid for.
  return from.interval === "annual" && to.interval === "monthly"
    ? "period_end"
    : "immediate";
}

export function isSameSelection(a: PlanSelection, b: PlanSelection): boolean {
  return a.plan === b.plan && a.interval === b.interval;
}

export interface PlanOption extends PlanSelection {
  priceId: string;
  /** Amount in the currency's minor unit (cents), straight from Stripe. */
  unitAmount: number | null;
  currency: string;
}

/**
 * The configured price ids, in a stable order, for use as cache key parts.
 *
 * Read without throwing: this runs at module scope to build the cache key, and
 * a missing env var must fail at the call site (`getPriceId`) with a message
 * naming the variable — not by killing the import of every module that touches
 * pricing.
 */
const PRICE_ID_KEY_PARTS = PLANS.flatMap((plan) =>
  INTERVALS.map(
    (interval) =>
      process.env[`STRIPE_${plan.toUpperCase()}_${interval.toUpperCase()}_PRICE_ID`] ??
      "unset",
  ),
);

/**
 * The four purchasable prices, read live from Stripe so the UI can never drift
 * from the catalogue. Cached — prices change about once a launch phase.
 *
 * The price ids are part of the CACHE KEY, not just the payload. `unstable_cache`
 * persists to `.next/cache`, which survives a server restart, so a key of just
 * ["stripe-plan-options"] kept serving the old amounts for the full hour after
 * the env vars were repointed at different prices — through restarts, with no
 * way to tell from the UI that it was stale. Keying on the ids means changing
 * one is self-invalidating: different id, different entry, immediate refetch.
 *
 * The `stripe-prices` tag is the manual escape hatch, for when the ids stay the
 * same but the amounts behind them change.
 */
export const getPlanOptions = unstable_cache(
  async (): Promise<PlanOption[]> => {
    const stripe = getStripe();
    const combos = PLANS.flatMap((plan) =>
      INTERVALS.map((interval) => ({ plan, interval })),
    );
    return Promise.all(
      combos.map(async ({ plan, interval }) => {
        const priceId = getPriceId(plan, interval);
        const price = await stripe.prices.retrieve(priceId);
        return {
          plan,
          interval,
          priceId,
          unitAmount: price.unit_amount,
          currency: price.currency,
        };
      }),
    );
  },
  ["stripe-plan-options", ...PRICE_ID_KEY_PARTS],
  { revalidate: 3600, tags: ["stripe-prices"] },
);

/** Map a Stripe price id back to the plan/interval it represents, if it's one of ours. */
export function selectionForPriceId(
  options: PlanOption[],
  priceId: string | null | undefined,
): PlanSelection | null {
  if (!priceId) return null;
  const match = options.find((o) => o.priceId === priceId);
  return match ? { plan: match.plan, interval: match.interval } : null;
}
