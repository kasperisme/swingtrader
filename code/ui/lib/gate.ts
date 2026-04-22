import type { PlanTier } from "@/lib/plans";
import { PLAN_GATE } from "@/lib/plans";

export interface TimeGate {
  enabled: boolean;
  fromGte: string | null;
  restrictionDays: number;
  upgradePlan: PlanTier;
}

/**
 * Compute a server-side time gate for the News Trends data queries.
 *
 * - observer  → last 24 hours  (1 day)
 * - investor  → last 30 days
 * - trader    → unrestricted (400 days via existing constant)
 */
export function computeNewsTrendsGate(tier: PlanTier): TimeGate {
  const allowedDays = PLAN_GATE[tier].newsTrendsLookbackDays;

  if (allowedDays >= PLAN_GATE.trader.newsTrendsLookbackDays) {
    return {
      enabled: false,
      fromGte: null,
      restrictionDays: allowedDays,
      upgradePlan: tier,
    };
  }

  const upgradePlan: PlanTier =
    tier === "observer" ? "investor" : "trader";

  const now = new Date();
  const cutoff = new Date(now);
  cutoff.setDate(cutoff.getDate() - allowedDays);
  cutoff.setHours(0, 0, 0, 0);

  return {
    enabled: true,
    fromGte: cutoff.toISOString(),
    restrictionDays: allowedDays,
    upgradePlan,
  };
}
