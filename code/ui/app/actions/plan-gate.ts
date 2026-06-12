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
