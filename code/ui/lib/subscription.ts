import { unstable_cache, revalidateTag } from "next/cache";
import type { SupabaseClient } from "@supabase/supabase-js";
import { type PlanTier, TRIAL_DAYS, TRIAL_TIER } from "@/lib/plans";
import { createServiceClient } from "@/lib/supabase/service";
import { PRELAUNCH_OPEN_ACCESS } from "@/lib/launch";

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

      // An active/trialing paid subscription always wins.
      if (row && ["active", "trialing"].includes(String(row.status))) {
        const plan = String(row.plan ?? "");
        if (plan === "investor" || plan === "trader") return plan;
      }

      // Otherwise, every account gets the full product free for the first
      // TRIAL_DAYS from signup — no payment method required. Once that window
      // closes with no paid plan, they fall through to Observer.
      if (await withinSignupTrial(supabase, userId)) return TRIAL_TIER;

      return "observer";
    },
    [`subscription-tier-${userId}`],
    { tags: [tierCacheTag(userId)], revalidate: TIER_CACHE_TTL },
  )();
}

/** Signup-anchored trial end (auth.users.created_at + TRIAL_DAYS), or null. */
export async function getSignupTrialEnd(createdAt: string | null | undefined): Promise<string | null> {
  if (!createdAt) return null;
  const start = new Date(createdAt).getTime();
  if (Number.isNaN(start)) return null;
  return new Date(start + TRIAL_DAYS * 24 * 60 * 60 * 1000).toISOString();
}

/**
 * Whether the account is still inside its signup trial window. Reads
 * auth.users.created_at via the admin API (service client). Fails closed to
 * "not in trial" on any error, so a lookup blip can't grant indefinite access —
 * the paid-subscription check above already runs first for real customers.
 */
async function withinSignupTrial(
  supabase: SupabaseClient,
  userId: string,
): Promise<boolean> {
  try {
    const { data, error } = await supabase.auth.admin.getUserById(userId);
    const createdAt = data?.user?.created_at;
    if (error || !createdAt) return false;
    const start = new Date(createdAt).getTime();
    if (Number.isNaN(start)) return false;
    return Date.now() < start + TRIAL_DAYS * 24 * 60 * 60 * 1000;
  } catch {
    return false;
  }
}

export async function getUserSubscriptionTier(
  supabase: SupabaseClient,
): Promise<PlanTier> {
  const { data: claims } = await supabase.auth.getClaims();
  const userId = claims?.claims?.sub;
  if (!userId) return "observer";
  return getCachedSubscriptionTier(userId);
}

/**
 * Whether AI chat / customization features are available to the caller. Paid
 * and trial users qualify (their tier is investor/trader); Observers do not.
 * Bypassed during the open beta. Use to gate the AI endpoints server-side so
 * the entitlement holds even if the UI gate is bypassed.
 */
export async function aiFeaturesAllowed(supabase: SupabaseClient): Promise<boolean> {
  if (PRELAUNCH_OPEN_ACCESS) return true;
  return (await getUserSubscriptionTier(supabase)) !== "observer";
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
