import { createHmac } from "crypto";
import { beforeAll, describe, expect, it } from "vitest";

/**
 * The briefing sign-in token hands over an account, so these tests are about
 * what it must REFUSE far more than what it accepts.
 *
 * Three of them cover mistakes that would each have been invisible in normal
 * use and severe in the wild: a link that never expires sitting in a forwarded
 * marketing email, a manage token replayed at the sign-in route because one
 * secret signs both families, and a protocol-relative `next` turning the route
 * into an open redirect that arrives with a live session attached.
 */

const SECRET = "test-secret-for-signin-tokens";

beforeAll(() => {
  process.env.UNSUBSCRIBE_SECRET = SECRET;
});

function b64url(input: string): string {
  return Buffer.from(input).toString("base64url");
}

/** Mint a token the way code/analytics/shared/email.py does. */
function mint(payload: Record<string, unknown>, secret = SECRET): string {
  const body = b64url(JSON.stringify(payload));
  const sig = createHmac("sha256", secret).update(body).digest("base64url");
  return `${body}.${sig}`;
}

function signinPayload(over: Record<string, unknown> = {}) {
  return {
    p: "signin",
    email: "reader@example.com",
    next: "/protected/charts?tickers=NVDA,AMD",
    exp: Math.floor(Date.now() / 1000) + 7 * 86400,
    ...over,
  };
}

describe("verifySigninToken", () => {
  it("accepts a token minted the way the Python sender mints it", async () => {
    const { verifySigninToken } = await import("@/lib/email/signin-token");
    const got = verifySigninToken(mint(signinPayload()));
    expect(got).not.toBeNull();
    expect(got!.email).toBe("reader@example.com");
    expect(got!.next).toBe("/protected/charts?tickers=NVDA,AMD");
  });

  it("lowercases and trims the email so it matches the subscription row", async () => {
    const { verifySigninToken } = await import("@/lib/email/signin-token");
    const got = verifySigninToken(mint(signinPayload({ email: "  Reader@Example.COM " })));
    expect(got!.email).toBe("reader@example.com");
  });

  it("refuses an expired token", async () => {
    const { verifySigninToken } = await import("@/lib/email/signin-token");
    const expired = signinPayload({ exp: Math.floor(Date.now() / 1000) - 1 });
    expect(verifySigninToken(mint(expired))).toBeNull();
  });

  it("refuses a token with no expiry at all", async () => {
    // The manage token's payload shape. Without this check, dropping `exp`
    // silently produces a permanent credential rather than an error.
    const { verifySigninToken } = await import("@/lib/email/signin-token");
    const noExp = { p: "signin", email: "reader@example.com", next: "/protected" };
    expect(verifySigninToken(mint(noExp))).toBeNull();
  });

  it("refuses a MANAGE token replayed at the sign-in route", async () => {
    // Same secret, same construction, valid signature — separated only by the
    // purpose field being inside the signed body. This is the whole reason `p`
    // exists: a preferences link must not be upgradable into a session.
    const { verifySigninToken } = await import("@/lib/email/signin-token");
    const manage = mint({ email: "reader@example.com" });
    expect(verifySigninToken(manage)).toBeNull();
  });

  it("refuses a token signed with a different secret", async () => {
    const { verifySigninToken } = await import("@/lib/email/signin-token");
    expect(verifySigninToken(mint(signinPayload(), "wrong-secret"))).toBeNull();
  });

  it("refuses a tampered payload", async () => {
    const { verifySigninToken } = await import("@/lib/email/signin-token");
    const good = mint(signinPayload());
    const [, sig] = good.split(".");
    const swapped = b64url(JSON.stringify(signinPayload({ email: "attacker@evil.com" })));
    expect(verifySigninToken(`${swapped}.${sig}`)).toBeNull();
  });

  it.each([
    ["", "empty"],
    ["not-a-token", "no separator"],
    [".", "empty halves"],
    ["abc.", "missing signature"],
  ])("refuses malformed input (%s)", async (token) => {
    const { verifySigninToken } = await import("@/lib/email/signin-token");
    expect(verifySigninToken(token as string)).toBeNull();
  });
});

describe("isSafeNext", () => {
  it("accepts same-origin paths", async () => {
    const { isSafeNext } = await import("@/lib/email/signin-token");
    expect(isSafeNext("/protected")).toBe(true);
    expect(isSafeNext("/protected/charts?tickers=NVDA,AMD")).toBe(true);
  });

  it.each([
    ["//evil.com", "protocol-relative — what a naive startsWith('/') lets through"],
    ["/\\evil.com", "backslash variant some parsers normalise to //"],
    ["https://evil.com", "absolute"],
    ["protected", "no leading slash"],
    ["", "empty"],
  ])("rejects %s (%s)", async (next) => {
    const { isSafeNext } = await import("@/lib/email/signin-token");
    expect(isSafeNext(next)).toBe(false);
  });

  it("refuses a signed token whose next is off-origin", async () => {
    // Signed by us, so the signature is valid — the destination check has to be
    // independent of authenticity, because a redirect bug on our side would
    // otherwise be signed and therefore trusted.
    const { verifySigninToken } = await import("@/lib/email/signin-token");
    expect(verifySigninToken(mint(signinPayload({ next: "//evil.com" })))).toBeNull();
  });
});
