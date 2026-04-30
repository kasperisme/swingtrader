import { unstable_cache, revalidateTag } from "next/cache";
import type { SupabaseClient } from "@supabase/supabase-js";
import type { PlanTier } from "@/lib/plans";
import { createServiceClient } from "@/lib/supabase/service";

export interface UserSubscription {
  plan: PlanTier;
  status: string;
  billing_interval: string | null;
  current_period_end: string | null;
  grandfathered: boolean;
}

const TIER_CACHE_TTL = 300; // 5 minutes

function tierCacheTag(userId: string): string {
  return `subscription-tier:${userId}`;
}

/** Invalidate a user's cached tier — call from Stripe webhooks on plan change. */
export function revalidateSubscriptionTier(userId: string): void {
  revalidateTag(tierCacheTag(userId), "max");
}

/**
 * Fetch and cache the subscription tier for a known user ID.
 * Uses the service client so it can be called without a session-scoped client,
 * enabling cache warming at login time and across request boundaries.
 */
export function getCachedSubscriptionTier(userId: string): Promise<PlanTier> {
  return unstable_cache(
    async (): Promise<PlanTier> => {
      const supabase = createServiceClient();
      const { data: row } = await supabase
        .schema("swingtrader")
        .from("user_subscriptions")
        .select("plan,status")
        .eq("user_id", userId)
        .maybeSingle();

      if (!row) return "observer";
      if (!["active", "trialing"].includes(row.status)) return "observer";
      const plan = String(row.plan ?? "");
      if (plan === "investor" || plan === "trader") return plan;
      return "observer";
    },
    [`subscription-tier-${userId}`],
    { tags: [tierCacheTag(userId)], revalidate: TIER_CACHE_TTL },
  )();
}

export async function getUserSubscriptionTier(
  supabase: SupabaseClient,
): Promise<PlanTier> {
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) return "observer";
  return getCachedSubscriptionTier(user.id);
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
