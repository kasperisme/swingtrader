import type { SupabaseClient } from "@supabase/supabase-js";
import type { PlanTier } from "@/lib/plans";

export interface UserSubscription {
  plan: PlanTier;
  status: string;
  billing_interval: string | null;
  current_period_end: string | null;
  grandfathered: boolean;
}

export async function getUserSubscriptionTier(
  supabase: SupabaseClient,
): Promise<PlanTier> {
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) return "observer";

  const { data: row } = await supabase
    .schema("swingtrader")
    .from("user_subscriptions")
    .select("plan,status")
    .eq("user_id", user.id)
    .maybeSingle();

  if (!row) return "observer";

  const validStatuses = ["active", "trialing"];
  if (!validStatuses.includes(row.status)) return "observer";

  const plan = String(row.plan ?? "");
  if (plan === "investor" || plan === "trader") return plan;

  return "observer";
}

export async function getUserSubscription(
  supabase: SupabaseClient,
): Promise<UserSubscription | null> {
  const { data: row } = await supabase
    .schema("swingtrader")
    .from("user_subscriptions")
    .select("plan,status,billing_interval,current_period_end,grandfathered")
    .maybeSingle();

  if (!row) return null;

  const plan = String(row.plan ?? "");
  return {
    plan: plan === "investor" || plan === "trader" ? (plan as PlanTier) : "observer",
    status: String(row.status ?? ""),
    billing_interval: row.billing_interval ? String(row.billing_interval) : null,
    current_period_end: row.current_period_end ? String(row.current_period_end) : null,
    grandfathered: Boolean(row.grandfathered),
  };
}
