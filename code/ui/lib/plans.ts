export type PlanTier = "observer" | "investor" | "trader";

export const PLAN_ORDER: PlanTier[] = ["observer", "investor", "trader"];

/** Plans that can be purchased via Stripe checkout. */
export const PAID_PLANS: PlanTier[] = ["investor", "trader"];

export interface GateSettings {
  /** Max historical data window in days for the News Trends page. */
  newsTrendsLookbackDays: number;
  label: string;
}

export const PLAN_GATE: Record<PlanTier, GateSettings> = {
  observer: {
    newsTrendsLookbackDays: 1,
    label: "Observer",
  },
  investor: {
    newsTrendsLookbackDays: 30,
    label: "Investor",
  },
  trader: {
    newsTrendsLookbackDays: 400,
    label: "Trader",
  },
};

/** Get the minimum tier required to access a given lookback window. */
export function tierForLookbackDays(days: number): PlanTier {
  if (days <= PLAN_GATE.observer.newsTrendsLookbackDays) return "observer";
  if (days <= PLAN_GATE.investor.newsTrendsLookbackDays) return "investor";
  return "trader";
}

/** Plan precedence rank — higher = more access. */
export function planRank(plan: PlanTier): number {
  return PLAN_ORDER.indexOf(plan);
}

export function hasPlan(userPlan: PlanTier, requiredPlan: PlanTier): boolean {
  return planRank(userPlan) >= planRank(requiredPlan);
}

export function isPaid(plan: PlanTier): boolean {
  return PAID_PLANS.includes(plan);
}
