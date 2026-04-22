"use server";

import { createClient } from "@/lib/supabase/server";
import { getUserSubscriptionTier } from "@/lib/subscription";
import { computeNewsTrendsGate, type TimeGate } from "@/lib/gate";
import type { PlanTier } from "@/lib/plans";

export async function getUserPlanTier(): Promise<PlanTier> {
  const supabase = await createClient();
  return getUserSubscriptionTier(supabase);
}

export async function getNewsTrendsGate(): Promise<TimeGate> {
  const tier = await getUserPlanTier();
  return computeNewsTrendsGate(tier);
}
