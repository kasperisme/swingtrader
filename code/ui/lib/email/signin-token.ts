import { createHmac, timingSafeEqual } from "crypto";

/**
 * One-click sign-in tokens minted by the briefing sender.
 *
 * The subscriber proved their address when they confirmed the subscription, so
 * the briefing can carry a signed assertion of "we sent this to this address"
 * and the route can trade it for a session. That removes the password step,
 * which was re-verifying a fact we already hold — and it is the step that stood
 * between 105 verified addresses and 19 accounts.
 *
 * Mirrors `sign_signin_token` in code/analytics/shared/email.py: same secret,
 * same body bytes, HMAC re-derived over the token's body substring so JSON key
 * order on the minting side is irrelevant.
 *
 * Two guards that the manage/unsubscribe tokens do not carry, because those
 * links only ever expose a preferences form and this one hands over an account:
 *
 *   - `exp`. A briefing lives in an inbox indefinitely and gets forwarded. A
 *     link that mints a session without an expiry is a permanent credential
 *     sitting in a marketing email.
 *   - `p === "signin"`. The purpose is inside the signed body, so a manage
 *     token — same secret, same shape — cannot be replayed here to take over
 *     the account. Verifying the signature is not enough when one key signs two
 *     families of link; the families have to be disjoint by construction.
 */

export type SigninTokenPayload = {
  email: string;
  next: string;
  exp: number;
};

function getSecret(): string {
  const secret = process.env.UNSUBSCRIBE_SECRET;
  if (!secret) throw new Error("Missing UNSUBSCRIBE_SECRET");
  return secret;
}

/**
 * Same-origin, path-only destinations. A valid signature proves we minted the
 * link, not that the destination is safe: without this a bug in the sender —
 * or anyone who ever gets to choose a `next` — turns the sign-in route into an
 * open redirect that arrives with a live session attached.
 *
 * `//evil.com` and `https://evil.com` are the two shapes that matter; the first
 * is protocol-relative and is what a naive `startsWith("/")` check lets through.
 */
export function isSafeNext(next: unknown): next is string {
  if (typeof next !== "string" || next.length === 0 || next.length > 512) return false;
  if (!next.startsWith("/")) return false;
  if (next.startsWith("//") || next.startsWith("/\\")) return false;
  return true;
}

export function verifySigninToken(
  token: string,
  now: number = Date.now(),
): SigninTokenPayload | null {
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
    if (!parsed || typeof parsed !== "object") return null;
    // Purpose first — a manage token verifies against this same secret.
    if (parsed.p !== "signin") return null;
    if (typeof parsed.email !== "string" || !parsed.email.includes("@")) return null;
    if (typeof parsed.exp !== "number" || !Number.isFinite(parsed.exp)) return null;
    if (parsed.exp * 1000 <= now) return null;
    if (!isSafeNext(parsed.next)) return null;
    return {
      email: parsed.email.trim().toLowerCase(),
      next: parsed.next,
      exp: parsed.exp,
    };
  } catch {
    return null;
  }
}
