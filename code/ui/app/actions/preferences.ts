"use server";

import { createClient } from "@/lib/supabase/server";
import {
  DEFAULT_LANGUAGE,
  isSupportedLanguage,
  normalizeLanguage,
  type LanguageCode,
} from "@/lib/languages";

export type PreferenceResult = { ok: true } | { ok: false; error: string };

/**
 * Persist the user's preferred language to user_profiles.metadata.preferred_language
 * (JSONB — no migration needed). Mirrors the merge-then-upsert pattern used by the
 * onboarding flags. The Python agent + Telegram delivery read this same key.
 */
export async function setPreferredLanguage(
  language: string,
): Promise<PreferenceResult> {
  if (!isSupportedLanguage(language)) {
    return { ok: false, error: "Unsupported language" };
  }

  const supabase = await createClient();
  const { data: claims } = await supabase.auth.getClaims();
  const userId = claims?.claims?.sub;
  if (!userId) return { ok: false, error: "Not authenticated" };

  const { data: existing, error: fetchError } = await supabase
    .schema("swingtrader")
    .from("user_profiles")
    .select("metadata")
    .eq("user_id", userId)
    .maybeSingle();

  if (fetchError) {
    console.error("[preferences] setPreferredLanguage fetch failed", fetchError.message);
    return { ok: false, error: fetchError.message };
  }

  const metadata = (existing?.metadata as Record<string, unknown> | undefined) ?? {};
  if (metadata.preferred_language === language) return { ok: true };

  const { error } = await supabase
    .schema("swingtrader")
    .from("user_profiles")
    .upsert(
      { user_id: userId, metadata: { ...metadata, preferred_language: language } },
      { onConflict: "user_id" },
    );

  if (error) {
    console.error("[preferences] setPreferredLanguage update failed", error.message);
    return { ok: false, error: error.message };
  }
  return { ok: true };
}

/** Read the user's preferred language, defaulting to English. */
export async function getPreferredLanguage(): Promise<LanguageCode> {
  const supabase = await createClient();
  const { data: claims } = await supabase.auth.getClaims();
  const userId = claims?.claims?.sub;
  if (!userId) return DEFAULT_LANGUAGE;

  const { data, error } = await supabase
    .schema("swingtrader")
    .from("user_profiles")
    .select("metadata")
    .eq("user_id", userId)
    .maybeSingle();

  if (error) {
    console.error("[preferences] getPreferredLanguage fetch failed", error.message);
    return DEFAULT_LANGUAGE;
  }

  const metadata = (data?.metadata as Record<string, unknown> | undefined) ?? {};
  return normalizeLanguage(metadata.preferred_language);
}
