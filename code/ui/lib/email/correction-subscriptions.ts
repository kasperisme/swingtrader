import { createServiceClient } from "@/lib/supabase/service";
import { signUnsubscribeToken } from "@/lib/email/screening-subscriptions";

/**
 * Email updates for the correction stress test (/correction): one mail per new
 * analysis, sent by services/drawdown/notify.py when a reviewed day is published.
 *
 * Table: swingtrader.drawdown_analysis_subscriptions (migration 20261122120000).
 * Until that migration is applied the table does not exist; the signup is then
 * kept in early_access_signups (source "correction_updates") so no lead is lost,
 * and the notifier backfills from there.
 */

const SCHEMA = "swingtrader";
const TABLE = "drawdown_analysis_subscriptions";
export const CORRECTION_SLUG = "correction";

export type CorrectionSubscribeOutcome = "subscribed" | "already_subscribed" | "queued" | "failed";

const tableMissing = (e: { code?: string; message?: string } | null) =>
  !!e && (e.code === "42P01" || e.code === "PGRST205" || /could not find the table|does not exist/i.test(e.message ?? ""));

export async function subscribeToCorrection(input: {
  email: string;
  source: string;
  userId?: string | null;
  referrer?: string | null;
  userAgent?: string | null;
  metadata?: Record<string, unknown>;
}): Promise<CorrectionSubscribeOutcome> {
  const email = input.email.trim().toLowerCase();
  const service = createServiceClient();
  const now = new Date().toISOString();

  const { data: existing, error: readErr } = await service
    .schema(SCHEMA)
    .from(TABLE)
    .select("status")
    .eq("email", email)
    .maybeSingle();

  if (tableMissing(readErr)) {
    const { error } = await service
      .schema(SCHEMA)
      .from("early_access_signups")
      .insert({ email, source: "correction_updates", metadata: { magnet: CORRECTION_SLUG, ...input.metadata } });
    if (error && error.code !== "23505" && !/duplicate key/i.test(error.message)) {
      console.error("[correction-subscribe] fallback insert failed", error.message);
      return "failed";
    }
    return "queued";
  }
  if ((existing as { status?: string } | null)?.status === "active") return "already_subscribed";

  const { error } = await service
    .schema(SCHEMA)
    .from(TABLE)
    .upsert(
      {
        email,
        status: "active",
        source: input.source,
        user_id: input.userId ?? null,
        referrer: input.referrer ?? null,
        user_agent: input.userAgent ?? null,
        metadata: input.metadata ?? {},
        unsubscribed_at: null,
        updated_at: now,
      },
      { onConflict: "email" },
    );
  if (error) {
    console.error("[correction-subscribe] upsert failed", error.message);
    return "failed";
  }
  return "subscribed";
}

export async function markCorrectionConfirmationSent(email: string): Promise<void> {
  await createServiceClient()
    .schema(SCHEMA)
    .from(TABLE)
    .update({ confirmation_sent_at: new Date().toISOString() })
    .eq("email", email.trim().toLowerCase());
}

export async function unsubscribeFromCorrection(email: string): Promise<boolean> {
  const now = new Date().toISOString();
  const { data, error } = await createServiceClient()
    .schema(SCHEMA)
    .from(TABLE)
    .update({ status: "unsubscribed", unsubscribed_at: now, updated_at: now })
    .eq("email", email.trim().toLowerCase())
    .eq("status", "active")
    .select("email");
  if (error) {
    console.error("[correction-unsubscribe] failed", error.message);
    return false;
  }
  return (data ?? []).length > 0;
}

export function buildCorrectionUnsubscribeUrl(baseUrl: string, email: string): string {
  const token = signUnsubscribeToken({ email: email.trim().toLowerCase(), slugs: [CORRECTION_SLUG] });
  return `${baseUrl.replace(/\/$/, "")}/api/correction/unsubscribe?token=${encodeURIComponent(token)}`;
}
