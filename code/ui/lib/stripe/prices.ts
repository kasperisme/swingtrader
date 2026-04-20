export type Plan = "investor" | "trader";
export type BillingInterval = "monthly" | "annual";

export function getPriceId(plan: Plan, interval: BillingInterval): string {
  const key = `STRIPE_${plan.toUpperCase()}_${interval.toUpperCase()}_PRICE_ID`;
  const value = process.env[key];
  if (!value) throw new Error(`Missing env var: ${key}`);
  return value;
}