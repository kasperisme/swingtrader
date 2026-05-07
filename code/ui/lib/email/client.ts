import { Resend } from "resend";

let cached: Resend | null = null;

/**
 * Resend client singleton. Throws if RESEND_API_KEY is missing — callers
 * that should be best-effort (e.g. waitlist signup) must catch.
 */
export function getResend(): Resend {
  if (cached) return cached;
  const key = process.env.RESEND_API_KEY;
  if (!key) throw new Error("Missing RESEND_API_KEY");
  cached = new Resend(key);
  return cached;
}

export const EMAIL_FROM =
  process.env.RESEND_FROM_EMAIL ?? "News Impact Screener <noreply@newsimpactscreener.com>";

export const EMAIL_REPLY_TO = process.env.RESEND_REPLY_TO ?? undefined;

/**
 * Resend "Segment" ID — the new contacts grouping primitive that replaced
 * Audiences in late 2025. See https://resend.com/docs/dashboard/segments.
 *
 * The SDK accepts multiple segments per contact; we keep one env var for
 * the waitlist segment and add more as we need finer slicing.
 */
export const RESEND_WAITLIST_SEGMENT_ID =
  process.env.RESEND_WAITLIST_SEGMENT_ID ?? undefined;
