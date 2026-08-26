"use server";

import { createClient } from "@/lib/supabase/server";
import { getUserSubscriptionTier } from "@/lib/subscription";
import { computeNewsTrendsGate, type TimeGate } from "@/lib/gate";
import { PRELAUNCH_OPEN_ACCESS } from "@/lib/launch";
import type { PlanTier } from "@/lib/plans";

export async function getUserPlanTier(): Promise<PlanTier> {
  const supabase = await createClient();
  return getUserSubscriptionTier(supabase);
}

/**
 * The server-side news-trends lookback gate for the current user. During the
 * open beta this is disabled (unrestricted) for everyone; at launch it clamps to
 * the user's tier window (observer 24h / investor 30d / trader 400d). This is the
 * single source of truth — data queries clamp their `since`/`from` to it.
 */
export async function getNewsTrendsGate(): Promise<TimeGate> {
  if (PRELAUNCH_OPEN_ACCESS) return computeNewsTrendsGate("trader");
  const tier = await getUserPlanTier();
  return computeNewsTrendsGate(tier);
}

/**
 * Auth + AI entitlement in one round trip, for surfaces that resolve the gate
 * on the client.
 *
 * The quote pages are public and statically prerendered, so they cannot read
 * auth cookies during render without going dynamic and losing that. The chart
 * workspace embedded there asks for this instead, after mount: the chart itself
 * is public, only the saved annotations and the AI panel are gated.
 *
 * `signedIn` and `aiEnabled` are separate because the two failure states need
 * different words — a logged-out reader needs an account, an Observer needs a
 * plan — and `getUserPlanTier()` reports both as "observer".
 */
export async function getChartWorkspaceAccess(): Promise<{
  signedIn: boolean;
  aiEnabled: boolean;
}> {
  const supabase = await createClient();
  const { data: claims } = await supabase.auth.getClaims();
  const signedIn = Boolean(claims?.claims?.sub);
  if (!signedIn) return { signedIn: false, aiEnabled: false };
  if (PRELAUNCH_OPEN_ACCESS) return { signedIn: true, aiEnabled: true };
  const tier = await getUserSubscriptionTier(supabase);
  return { signedIn: true, aiEnabled: tier !== "observer" };
}
