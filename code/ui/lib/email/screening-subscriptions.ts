import { createHmac, timingSafeEqual } from "crypto";
import { createServiceClient } from "@/lib/supabase/service";

const SCHEMA = "swingtrader";
const TABLE = "market_screening_email_subscriptions";

export type ScreeningRef = { id: string; slug: string; name: string };

export type SubscribeOutcome = {
  /** Screenings the email was freshly subscribed to (rows created or re-activated). */
  subscribed: ScreeningRef[];
  /** Screenings the email was already actively subscribed to. */
  alreadySubscribed: ScreeningRef[];
};

const validEmail = (raw: string): boolean =>
  /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(raw.trim().toLowerCase());

export function isValidEmail(raw: string): boolean {
  return validEmail(raw);
}

// ── Unsubscribe token (stateless, HMAC-signed) ──────────────────────────────
//
// payload = base64url(JSON{ email, slugs }) ; token = payload + "." + sig
// sig = base64url(HMAC-SHA256(payload, UNSUBSCRIBE_SECRET)). No DB lookup needed
// to validate — the signature proves the link was minted by us.

type UnsubPayload = { email: string; slugs: string[] };

function getUnsubscribeSecret(): string {
  const secret = process.env.UNSUBSCRIBE_SECRET;
  if (!secret) throw new Error("Missing UNSUBSCRIBE_SECRET");
  return secret;
}

function b64url(input: Buffer | string): string {
  return Buffer.from(input).toString("base64url");
}

export function signUnsubscribeToken(payload: UnsubPayload): string {
  const body = b64url(JSON.stringify(payload));
  const sig = createHmac("sha256", getUnsubscribeSecret())
    .update(body)
    .digest("base64url");
  return `${body}.${sig}`;
}

export function verifyUnsubscribeToken(token: string): UnsubPayload | null {
  if (!token || typeof token !== "string" || !token.includes(".")) return null;
  const [body, sig] = token.split(".");
  if (!body || !sig) return null;

  let expected: string;
  try {
    expected = createHmac("sha256", getUnsubscribeSecret())
      .update(body)
      .digest("base64url");
  } catch {
    return null;
  }

  const a = Buffer.from(sig);
  const b = Buffer.from(expected);
  if (a.length !== b.length || !timingSafeEqual(a, b)) return null;

  try {
    const parsed = JSON.parse(Buffer.from(body, "base64url").toString("utf8"));
    if (
      parsed &&
      typeof parsed.email === "string" &&
      Array.isArray(parsed.slugs)
    ) {
      return {
        email: parsed.email,
        slugs: parsed.slugs.filter((s: unknown) => typeof s === "string"),
      };
    }
  } catch {
    /* fall through */
  }
  return null;
}

/** Build the absolute one-click unsubscribe URL for a confirmation email. */
export function buildUnsubscribeUrl(
  baseUrl: string,
  payload: UnsubPayload,
): string {
  const token = signUnsubscribeToken(payload);
  return `${baseUrl.replace(/\/$/, "")}/api/unsubscribe?token=${encodeURIComponent(token)}`;
}

// ── Persistence ─────────────────────────────────────────────────────────────

/** Resolve published screenings by slug, preserving the requested order. */
export async function resolveScreeningsBySlugs(
  slugs: string[],
): Promise<ScreeningRef[]> {
  const wanted = [...new Set(slugs.map((s) => s.trim()).filter(Boolean))];
  if (wanted.length === 0) return [];

  const service = createServiceClient();
  const { data, error } = await service
    .schema(SCHEMA)
    .from("market_screenings")
    .select("id, slug, name")
    .in("slug", wanted)
    .eq("is_published", true);

  if (error || !data) return [];
  const bySlug = new Map(
    (data as ScreeningRef[]).map((s) => [s.slug, s] as const),
  );
  return wanted.map((s) => bySlug.get(s)).filter((s): s is ScreeningRef => Boolean(s));
}

/**
 * Subscribe an email to one or more screenings. Idempotent: a row that already
 * exists and is active counts as `alreadySubscribed`; a previously-unsubscribed
 * row is re-activated and counts as `subscribed`.
 */
export async function subscribeEmailToScreenings(input: {
  email: string;
  screenings: ScreeningRef[];
  source?: string;
  userId?: string | null;
  referrer?: string | null;
  userAgent?: string | null;
  metadata?: Record<string, unknown>;
}): Promise<SubscribeOutcome> {
  const email = input.email.trim().toLowerCase();
  const service = createServiceClient();
  const nowIso = new Date().toISOString();

  const subscribed: ScreeningRef[] = [];
  const alreadySubscribed: ScreeningRef[] = [];

  for (const screening of input.screenings) {
    // Check current state first so we can distinguish fresh vs already-active.
    const { data: existing } = await service
      .schema(SCHEMA)
      .from(TABLE)
      .select("id, status")
      .eq("market_screening_id", screening.id)
      .ilike("email", email)
      .limit(1)
      .maybeSingle();

    if (existing && (existing as { status: string }).status === "active") {
      alreadySubscribed.push(screening);
      continue;
    }

    const { error } = await service
      .schema(SCHEMA)
      .from(TABLE)
      .upsert(
        {
          email,
          market_screening_id: screening.id,
          channel: "email",
          status: "active",
          source: input.source || "email_subscribe",
          user_id: input.userId ?? null,
          referrer: input.referrer ?? null,
          user_agent: input.userAgent ?? null,
          metadata: input.metadata ?? {},
          unsubscribed_at: null,
          updated_at: nowIso,
        },
        { onConflict: "email,market_screening_id" },
      );

    if (error) {
      console.error(
        "[email-subscriptions] upsert failed",
        screening.slug,
        error.message,
      );
      continue;
    }
    subscribed.push(screening);
  }

  return { subscribed, alreadySubscribed };
}

/** Mark the confirmation email as sent (best-effort, non-blocking). */
export async function markConfirmationSent(
  email: string,
  screeningIds: string[],
): Promise<void> {
  if (screeningIds.length === 0) return;
  const service = createServiceClient();
  await service
    .schema(SCHEMA)
    .from(TABLE)
    .update({ confirmation_sent_at: new Date().toISOString() })
    .ilike("email", email.trim().toLowerCase())
    .in("market_screening_id", screeningIds);
}

/**
 * Soft-unsubscribe an email from the given screening slugs (or all of its
 * subscriptions when `slugs` is empty). Returns the names of the screenings
 * the email was removed from.
 */
export async function unsubscribeEmail(input: {
  email: string;
  slugs?: string[];
}): Promise<{ removed: string[] }> {
  const email = input.email.trim().toLowerCase();
  const service = createServiceClient();
  const nowIso = new Date().toISOString();

  let screeningIds: string[] | null = null;
  if (input.slugs && input.slugs.length > 0) {
    const refs = await resolveScreeningsBySlugs(input.slugs);
    screeningIds = refs.map((r) => r.id);
    if (screeningIds.length === 0) return { removed: [] };
  }

  let query = service
    .schema(SCHEMA)
    .from(TABLE)
    .update({ status: "unsubscribed", unsubscribed_at: nowIso, updated_at: nowIso })
    .ilike("email", email)
    .eq("status", "active");
  if (screeningIds) query = query.in("market_screening_id", screeningIds);

  const { data, error } = await query.select(
    "market_screening_id, market_screenings(name)",
  );
  if (error) {
    console.error("[email-subscriptions] unsubscribe failed", error.message);
    return { removed: [] };
  }

  const removed = (data ?? [])
    .map((r) => {
      const j = (r as { market_screenings?: { name?: string } | null })
        .market_screenings;
      return j?.name ?? null;
    })
    .filter((n): n is string => Boolean(n));
  return { removed };
}
