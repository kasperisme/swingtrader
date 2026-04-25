"use server";

import { createClient } from "@/lib/supabase/server";
import { getUserPlanTier } from "./plan-gate";
import { hasPlan, type PlanTier } from "@/lib/plans";

type ActionResult<T> = Promise<{ ok: true; data: T } | { ok: false; error: string }>;

const SCHEMA = "swingtrader";

const SCREENING_LIMITS: Record<PlanTier, number> = {
  observer: 1,
  investor: 5,
  trader: 25,
};

const SCHEDULE_GATES: Record<PlanTier, string> = {
  observer: "0 7 * * 1-5",
  investor: "0 */4 * * *",
  trader: "*/15 * * * *",
};

export type ScheduledScreening = {
  id: string;
  name: string;
  prompt: string;
  schedule: string;
  timezone: string;
  is_active: boolean;
  run_requested_at: string | null;
  last_run_at: string | null;
  last_triggered: boolean | null;
  created_at: string;
  updated_at: string;
};

export type ScreeningResult = {
  id: string;
  screening_id: string;
  run_at: string;
  triggered: boolean;
  summary: string | null;
  data_used: Record<string, unknown> | null;
  is_test: boolean;
  delivered: boolean;
  created_at: string;
};

export async function listScheduledScreenings(): Promise<
  ActionResult<ScheduledScreening[]>
> {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return { ok: false, error: "Not authenticated" };

  const { data, error } = await supabase
    .schema(SCHEMA)
    .from("user_scheduled_screenings")
    .select("*")
    .eq("user_id", user.id)
    .order("created_at", { ascending: false });

  if (error) return { ok: false, error: error.message };
  return { ok: true, data: (data ?? []) as ScheduledScreening[] };
}

export async function createScheduledScreening(input: {
  name: string;
  prompt: string;
  schedule: string;
  timezone: string;
}): ActionResult<ScheduledScreening> {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return { ok: false, error: "Not authenticated" };

  const plan = await getUserPlanTier();
  const limit = SCREENING_LIMITS[plan];

  const { count, error: countErr } = await supabase
    .schema(SCHEMA)
    .from("user_scheduled_screenings")
    .select("*", { count: "exact", head: true })
    .eq("user_id", user.id)
    .eq("is_active", true);

  if (countErr) return { ok: false, error: countErr.message };
  if ((count ?? 0) >= limit)
    return {
      ok: false,
      error: `${plan} plan allows ${limit} active screenings. Upgrade for more.`,
    };

  const { data, error } = await supabase
    .schema(SCHEMA)
    .from("user_scheduled_screenings")
    .insert({
      user_id: user.id,
      name: input.name,
      prompt: input.prompt,
      schedule: input.schedule,
      timezone: input.timezone,
    })
    .select("*")
    .single();

  if (error) return { ok: false, error: error.message };
  return { ok: true, data: data as ScheduledScreening };
}

export async function updateScheduledScreening(
  id: string,
  input: {
    name?: string;
    prompt?: string;
    schedule?: string;
    timezone?: string;
    is_active?: boolean;
  }
): ActionResult<ScheduledScreening> {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return { ok: false, error: "Not authenticated" };

  const { data, error } = await supabase
    .schema(SCHEMA)
    .from("user_scheduled_screenings")
    .update(input)
    .eq("id", id)
    .eq("user_id", user.id)
    .select("*")
    .single();

  if (error) return { ok: false, error: error.message };
  return { ok: true, data: data as ScheduledScreening };
}

export async function toggleScreening(
  id: string,
  active: boolean
): ActionResult<ScheduledScreening> {
  return updateScheduledScreening(id, { is_active: active });
}

export async function deleteScheduledScreening(
  id: string
): ActionResult<{ deleted: true }> {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return { ok: false, error: "Not authenticated" };

  const { error } = await supabase
    .schema(SCHEMA)
    .from("user_scheduled_screenings")
    .delete()
    .eq("id", id)
    .eq("user_id", user.id);

  if (error) return { ok: false, error: error.message };
  return { ok: true, data: { deleted: true } };
}

export async function getScreeningResults(
  screeningId: string,
  limit = 20
): ActionResult<ScreeningResult[]> {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return { ok: false, error: "Not authenticated" };

  const { data, error } = await supabase
    .schema(SCHEMA)
    .from("user_screening_results")
    .select("*")
    .eq("screening_id", screeningId)
    .eq("user_id", user.id)
    .order("run_at", { ascending: false })
    .limit(limit);

  if (error) return { ok: false, error: error.message };
  return { ok: true, data: (data ?? []) as ScreeningResult[] };
}

export async function getScreeningLimits(): ActionResult<{
  limit: number;
  used: number;
  plan: PlanTier;
  minSchedule: string;
}> {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return { ok: false, error: "Not authenticated" };

  const plan = await getUserPlanTier();
  const { count } = await supabase
    .schema(SCHEMA)
    .from("user_scheduled_screenings")
    .select("*", { count: "exact", head: true })
    .eq("user_id", user.id)
    .eq("is_active", true);

  return {
    ok: true,
    data: {
      limit: SCREENING_LIMITS[plan],
      used: count ?? 0,
      plan,
      minSchedule: SCHEDULE_GATES[plan],
    },
  };
}

export async function testRunScreening(
  screeningId: string
): Promise<{ ok: true; data: { requested: true } } | { ok: false; error: string }> {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return { ok: false, error: "Not authenticated" };

  const { error } = await supabase
    .schema(SCHEMA)
    .from("user_scheduled_screenings")
    .update({ run_requested_at: new Date().toISOString() })
    .eq("id", screeningId)
    .eq("user_id", user.id);

  if (error) return { ok: false, error: error.message };
  return { ok: true, data: { requested: true } };
}

export async function pollTestResult(
  screeningId: string
): Promise<
  { ok: true; data: ScreeningResult | null } | { ok: false; error: string }
> {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return { ok: false, error: "Not authenticated" };

  const { data, error } = await supabase
    .schema(SCHEMA)
    .from("user_screening_results")
    .select("*")
    .eq("screening_id", screeningId)
    .eq("user_id", user.id)
    .eq("is_test", true)
    .order("run_at", { ascending: false })
    .limit(1)
    .maybeSingle();

  if (error) return { ok: false, error: error.message };
  return { ok: true, data: (data as ScreeningResult) ?? null };
}
