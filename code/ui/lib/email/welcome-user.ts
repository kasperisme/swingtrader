import type { User } from "@supabase/supabase-js";
import { createClient } from "@/lib/supabase/server";
import { sendTemplateEmail } from "./send";

const WELCOME_FLAG = "welcome_email_sent_at";

function deriveFirstName(user: User): string {
  const meta = (user.user_metadata ?? {}) as Record<string, unknown>;
  const candidates = [meta.first_name, meta.firstName, meta.name, meta.full_name];
  for (const c of candidates) {
    if (typeof c === "string" && c.trim()) return c.trim().split(/\s+/)[0];
  }
  // Fall back to email local-part, prettified.
  const local = (user.email ?? "").split("@")[0]?.replace(/[._-]+/g, " ").trim();
  if (local) {
    return local.charAt(0).toUpperCase() + local.slice(1);
  }
  return "trader";
}

/**
 * Send the post-signup welcome email exactly once per user, using a
 * Resend stored template. Idempotent — safe to call from any auth flow
 * (signup confirm, magic link, etc.); the metadata flag prevents
 * duplicates. Returns silently on missing config.
 */
export async function welcomeUserIfNeeded(user: User): Promise<void> {
  if (!user.email) return;

  const templateId = process.env.RESEND_WELCOME_TEMPLATE_ID;
  if (!templateId) return;

  const supabase = await createClient();

  const { data: profile, error: fetchError } = await supabase
    .schema("swingtrader")
    .from("user_profiles")
    .select("metadata")
    .eq("user_id", user.id)
    .maybeSingle();

  if (fetchError) {
    console.error("[welcome-user] profile fetch failed", fetchError.message);
    return;
  }

  const metadata = (profile?.metadata ?? {}) as Record<string, unknown>;
  if (metadata[WELCOME_FLAG]) return;

  const firstName = deriveFirstName(user);
  const appUrl =
    process.env.NEXT_PUBLIC_APP_URL ?? "https://newsimpactscreener.com";

  const result = await sendTemplateEmail({
    to: user.email,
    templateId,
    variables: { firstName, email: user.email, appUrl },
    tags: [{ name: "type", value: "signup_welcome" }],
  });

  if (!result.ok) {
    console.error("[welcome-user] send failed", result.error);
    return;
  }

  const nextMetadata = { ...metadata, [WELCOME_FLAG]: new Date().toISOString() };
  const { error: upsertError } = await supabase
    .schema("swingtrader")
    .from("user_profiles")
    .upsert(
      { user_id: user.id, metadata: nextMetadata },
      { onConflict: "user_id" },
    );

  if (upsertError) {
    // Worst case: user gets a second welcome email on a later confirm. Log and continue.
    console.error("[welcome-user] flag write failed", upsertError.message);
  }
}
