import { createServiceClient } from "@/lib/supabase/service";

const SCHEMA = "swingtrader";
const TABLE = "early_access_signups";

/**
 * Idempotently record an email in swingtrader.early_access_signups.
 *
 * Shared by the public waitlist endpoint (/api/early-access) and the news
 * briefing subscribe flow (/api/briefings/subscribe) so every briefing
 * subscriber also lands on the early-access list. A duplicate email (unique
 * violation, 23505) is treated as success — we never overwrite an existing
 * signup's source/metadata.
 *
 * Best-effort: returns a result instead of throwing so callers can keep the
 * primary action (the briefing subscription) succeeding even if this fails.
 */
export async function recordEarlyAccessSignup(input: {
  email: string;
  source: string;
  metadata?: Record<string, unknown>;
}): Promise<{ ok: true; duplicate: boolean } | { ok: false; error: string }> {
  const email = input.email.trim().toLowerCase();
  if (!email) return { ok: false, error: "empty_email" };

  let supabase;
  try {
    supabase = createServiceClient();
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : "no_service_client" };
  }

  const { error } = await supabase
    .schema(SCHEMA)
    .from(TABLE)
    .insert({ email, source: input.source, metadata: input.metadata ?? {} });

  if (error) {
    // Unique violation — already on the list. Idempotent success.
    if (error.code === "23505") return { ok: true, duplicate: true };
    return { ok: false, error: error.message };
  }
  return { ok: true, duplicate: false };
}
