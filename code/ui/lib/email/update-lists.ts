import { createServiceClient } from "@/lib/supabase/service";
import { signUnsubscribeToken } from "@/lib/email/screening-subscriptions";

/**
 * Email-only "send me updates" lists: the correction stress test and the Arena
 * daily digest. One table per list, all the same shape
 * (email, status, source, user_id, referrer, user_agent, metadata,
 * confirmation_sent_at, unsubscribed_at, created_at, updated_at), written only by
 * the service role. Unsubscribe is an HMAC-signed link carrying the list slug.
 *
 * Until a list's migration is applied its table does not exist; the signup is
 * then kept in early_access_signups (source `<slug>_updates`) so no lead is lost,
 * and the Python sender backfills from there on its first run.
 */

export type UpdateList = {
  /** Unsubscribe token slug + analytics magnet. */
  slug: "correction" | "arena";
  table: string;
  /** Public path of the list's unsubscribe route. */
  unsubscribePath: string;
};

export const CORRECTION_LIST: UpdateList = {
  slug: "correction",
  table: "drawdown_analysis_subscriptions",
  unsubscribePath: "/api/correction/unsubscribe",
};

export const ARENA_LIST: UpdateList = {
  slug: "arena",
  table: "arena_digest_subscriptions",
  unsubscribePath: "/api/arena/unsubscribe",
};

const SCHEMA = "swingtrader";

export type SubscribeOutcome = "subscribed" | "already_subscribed" | "queued" | "failed";

const tableMissing = (e: { code?: string; message?: string } | null) =>
  !!e && (e.code === "42P01" || e.code === "PGRST205" || /could not find the table|does not exist/i.test(e.message ?? ""));

const norm = (email: string) => email.trim().toLowerCase();

export async function subscribeToList(
  list: UpdateList,
  input: {
    email: string;
    source: string;
    userId?: string | null;
    referrer?: string | null;
    userAgent?: string | null;
    metadata?: Record<string, unknown>;
  },
): Promise<SubscribeOutcome> {
  const email = norm(input.email);
  const service = createServiceClient();

  const { data: existing, error: readErr } = await service
    .schema(SCHEMA)
    .from(list.table)
    .select("status")
    .eq("email", email)
    .maybeSingle();

  if (tableMissing(readErr)) {
    const { error } = await service
      .schema(SCHEMA)
      .from("early_access_signups")
      .insert({ email, source: `${list.slug}_updates`, metadata: { magnet: list.slug, ...input.metadata } });
    if (error && error.code !== "23505" && !/duplicate key/i.test(error.message)) {
      console.error(`[${list.slug}-subscribe] fallback insert failed`, error.message);
      return "failed";
    }
    return "queued";
  }
  if ((existing as { status?: string } | null)?.status === "active") return "already_subscribed";

  const { error } = await service
    .schema(SCHEMA)
    .from(list.table)
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
        updated_at: new Date().toISOString(),
      },
      { onConflict: "email" },
    );
  if (error) {
    console.error(`[${list.slug}-subscribe] upsert failed`, error.message);
    return "failed";
  }
  return "subscribed";
}

export async function markListConfirmationSent(list: UpdateList, email: string): Promise<void> {
  await createServiceClient()
    .schema(SCHEMA)
    .from(list.table)
    .update({ confirmation_sent_at: new Date().toISOString() })
    .eq("email", norm(email));
}

export async function unsubscribeFromList(list: UpdateList, email: string): Promise<boolean> {
  const now = new Date().toISOString();
  const { data, error } = await createServiceClient()
    .schema(SCHEMA)
    .from(list.table)
    .update({ status: "unsubscribed", unsubscribed_at: now, updated_at: now })
    .eq("email", norm(email))
    .eq("status", "active")
    .select("email");
  if (error) {
    console.error(`[${list.slug}-unsubscribe] failed`, error.message);
    return false;
  }
  return (data ?? []).length > 0;
}

export function buildListUnsubscribeUrl(list: UpdateList, baseUrl: string, email: string): string {
  const token = signUnsubscribeToken({ email: norm(email), slugs: [list.slug] });
  return `${baseUrl.replace(/\/$/, "")}${list.unsubscribePath}?token=${encodeURIComponent(token)}`;
}
