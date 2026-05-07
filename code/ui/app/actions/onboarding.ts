"use server";

import { createClient } from "@/lib/supabase/server";

export type OnboardingActionResult = { ok: true } | { ok: false; error: string };

/**
 * Mark the current user as having seen the welcome dialog. Idempotent —
 * subsequent calls overwrite welcomed_at, which is fine.
 */
export async function markWelcomed(): Promise<OnboardingActionResult> {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return { ok: false, error: "Not authenticated" };

  const { error } = await supabase
    .schema("swingtrader")
    .from("user_profiles")
    .upsert(
      { user_id: user.id, welcomed_at: new Date().toISOString() },
      { onConflict: "user_id" },
    );

  if (error) {
    console.error("[onboarding] markWelcomed failed", error.message);
    return { ok: false, error: error.message };
  }
  return { ok: true };
}
