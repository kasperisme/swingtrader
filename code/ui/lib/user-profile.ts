import { createClient } from "@/lib/supabase/server";

export type UserProfile = {
  user_id: string;
  created_at: string;
  updated_at: string;
  welcomed_at: string | null;
  onboarding_dismissed_at: string | null;
  display_name: string | null;
  metadata: Record<string, unknown>;
};

/**
 * Fetch the current user's profile, creating an empty row if none exists.
 * Returns null only if there is no authenticated user.
 */
export async function getOrCreateUserProfile(): Promise<UserProfile | null> {
  const supabase = await createClient();
  const { data: claims } = await supabase.auth.getClaims();
  const userId = claims?.claims?.sub;
  if (!userId) return null;

  const { data: existing, error: fetchError } = await supabase
    .schema("swingtrader")
    .from("user_profiles")
    .select("*")
    .eq("user_id", userId)
    .maybeSingle();

  if (fetchError) {
    console.error("[user-profile] fetch failed", fetchError.message);
    return null;
  }
  if (existing) return existing as UserProfile;

  const { data: inserted, error: insertError } = await supabase
    .schema("swingtrader")
    .from("user_profiles")
    .insert({ user_id: userId })
    .select("*")
    .single();

  if (insertError) {
    // Race: another request may have inserted between fetch + insert.
    // Re-read instead of failing.
    if (insertError.code === "23505") {
      const { data: retry } = await supabase
        .schema("swingtrader")
        .from("user_profiles")
        .select("*")
        .eq("user_id", userId)
        .single();
      return (retry as UserProfile) ?? null;
    }
    console.error("[user-profile] insert failed", insertError.message);
    return null;
  }
  return inserted as UserProfile;
}
