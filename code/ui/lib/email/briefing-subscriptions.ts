import { createHmac, timingSafeEqual } from "crypto";
import { createServiceClient } from "@/lib/supabase/service";

const SCHEMA = "swingtrader";
const TABLE = "news_briefing_subscriptions";

export type BriefingSubscription = {
  email: string;
  tickers: string[];
  tags: string[];
  status: "active" | "unsubscribed";
};

const validEmail = (raw: string): boolean =>
  /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(raw.trim().toLowerCase());

export function isValidEmail(raw: string): boolean {
  return validEmail(raw);
}

/** Tickers stored upper-case, de-duped, max 25. */
export function normalizeTickers(input: unknown): string[] {
  if (!Array.isArray(input)) return [];
  const seen = new Set<string>();
  for (const raw of input) {
    if (typeof raw !== "string") continue;
    const t = raw.trim().toUpperCase().replace(/[^A-Z0-9.\-]/g, "");
    if (t && t.length <= 12) seen.add(t);
  }
  return [...seen].slice(0, 25);
}

/** Tags stored lower-case slugs, de-duped, max 25. */
export function normalizeTags(input: unknown): string[] {
  if (!Array.isArray(input)) return [];
  const seen = new Set<string>();
  for (const raw of input) {
    if (typeof raw !== "string") continue;
    const t = raw.trim().toLowerCase().replace(/\s+/g, "-").replace(/[^a-z0-9-]/g, "");
    if (t && t.length <= 40) seen.add(t);
  }
  return [...seen].slice(0, 25);
}

// ── Manage / unsubscribe token (stateless, HMAC-signed) ─────────────────────
//
// One briefing per email, so the email is the whole identity. payload =
// base64url(JSON{email}); token = payload + "." + base64url(HMAC-SHA256(payload,
// UNSUBSCRIBE_SECRET)). Same shape the Python sender mints (shared/email.py
// sign_briefing_token), so links cross-verify.

type BriefingTokenPayload = { email: string };

function getSecret(): string {
  const secret = process.env.UNSUBSCRIBE_SECRET;
  if (!secret) throw new Error("Missing UNSUBSCRIBE_SECRET");
  return secret;
}

function b64url(input: Buffer | string): string {
  return Buffer.from(input).toString("base64url");
}

export function signBriefingToken(payload: BriefingTokenPayload): string {
  const body = b64url(JSON.stringify({ email: payload.email }));
  const sig = createHmac("sha256", getSecret()).update(body).digest("base64url");
  return `${body}.${sig}`;
}

export function verifyBriefingToken(token: string): BriefingTokenPayload | null {
  if (!token || typeof token !== "string" || !token.includes(".")) return null;
  const [body, sig] = token.split(".");
  if (!body || !sig) return null;

  let expected: string;
  try {
    expected = createHmac("sha256", getSecret()).update(body).digest("base64url");
  } catch {
    return null;
  }

  const a = Buffer.from(sig);
  const b = Buffer.from(expected);
  if (a.length !== b.length || !timingSafeEqual(a, b)) return null;

  try {
    const parsed = JSON.parse(Buffer.from(body, "base64url").toString("utf8"));
    if (parsed && typeof parsed.email === "string") {
      return { email: parsed.email };
    }
  } catch {
    /* fall through */
  }
  return null;
}

export function buildManageUrl(baseUrl: string, email: string): string {
  const token = signBriefingToken({ email });
  return `${baseUrl.replace(/\/$/, "")}/briefings/manage?token=${encodeURIComponent(token)}`;
}

export function buildUnsubscribeUrl(baseUrl: string, email: string): string {
  const token = signBriefingToken({ email });
  return `${baseUrl.replace(/\/$/, "")}/api/briefings/unsubscribe?token=${encodeURIComponent(token)}`;
}

// ── Persistence ─────────────────────────────────────────────────────────────

export type UpsertResult = { created: boolean; reactivated: boolean };

/**
 * Create or update the one-briefing-per-email row. Sets
 * `initial_briefing_requested_at` so the Python tick sends the first PDF
 * immediately. Idempotent: re-subscribing replaces the watchlist and re-arms
 * the immediate send.
 */
export async function upsertBriefingSubscription(input: {
  email: string;
  tickers: string[];
  tags: string[];
  source?: string;
  userId?: string | null;
  referrer?: string | null;
  userAgent?: string | null;
  metadata?: Record<string, unknown>;
  /** When false, don't (re)trigger an immediate send (used by edit). */
  sendNow?: boolean;
}): Promise<UpsertResult> {
  const email = input.email.trim().toLowerCase();
  const service = createServiceClient();
  const nowIso = new Date().toISOString();

  const { data: existing } = await service
    .schema(SCHEMA)
    .from(TABLE)
    .select("id, status")
    .ilike("email", email)
    .limit(1)
    .maybeSingle();

  const wasUnsub =
    existing != null && (existing as { status: string }).status !== "active";

  const row: Record<string, unknown> = {
    email,
    tickers: input.tickers,
    tags: input.tags,
    status: "active",
    source: input.source || "briefing_subscribe",
    user_id: input.userId ?? null,
    referrer: input.referrer ?? null,
    user_agent: input.userAgent ?? null,
    metadata: input.metadata ?? {},
    unsubscribed_at: null,
    updated_at: nowIso,
  };
  if (input.sendNow !== false) row.initial_briefing_requested_at = nowIso;

  const { error } = await service
    .schema(SCHEMA)
    .from(TABLE)
    .upsert(row, { onConflict: "email" });

  if (error) {
    console.error("[briefing-subscriptions] upsert failed", error.message);
    throw new Error(error.message);
  }
  return { created: existing == null, reactivated: wasUnsub };
}

/** Load a briefing by email (for the manage page). Null if none. */
export async function getBriefingByEmail(
  email: string,
): Promise<BriefingSubscription | null> {
  const service = createServiceClient();
  const { data } = await service
    .schema(SCHEMA)
    .from(TABLE)
    .select("email, tickers, tags, status")
    .ilike("email", email.trim().toLowerCase())
    .limit(1)
    .maybeSingle();
  if (!data) return null;
  const row = data as BriefingSubscription;
  return {
    email: row.email,
    tickers: row.tickers ?? [],
    tags: row.tags ?? [],
    status: (row.status as "active" | "unsubscribed") ?? "active",
  };
}

/** Replace the watchlist for an existing email; re-activates if needed. */
export async function updateBriefingPreferences(input: {
  email: string;
  tickers: string[];
  tags: string[];
}): Promise<boolean> {
  const email = input.email.trim().toLowerCase();
  const service = createServiceClient();
  const nowIso = new Date().toISOString();
  const { error } = await service
    .schema(SCHEMA)
    .from(TABLE)
    .update({
      tickers: input.tickers,
      tags: input.tags,
      status: "active",
      unsubscribed_at: null,
      updated_at: nowIso,
    })
    .ilike("email", email);
  if (error) {
    console.error("[briefing-subscriptions] update failed", error.message);
    return false;
  }
  return true;
}

/** Soft-unsubscribe the email's briefing. */
export async function unsubscribeBriefing(email: string): Promise<boolean> {
  const service = createServiceClient();
  const nowIso = new Date().toISOString();
  const { error } = await service
    .schema(SCHEMA)
    .from(TABLE)
    .update({
      status: "unsubscribed",
      unsubscribed_at: nowIso,
      updated_at: nowIso,
      initial_briefing_requested_at: null,
    })
    .ilike("email", email.trim().toLowerCase())
    .eq("status", "active");
  if (error) {
    console.error("[briefing-subscriptions] unsubscribe failed", error.message);
    return false;
  }
  return true;
}
