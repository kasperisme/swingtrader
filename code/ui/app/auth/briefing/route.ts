import { redirect } from "next/navigation";
import { type NextRequest } from "next/server";

import { verifySigninToken, isSafeNext } from "@/lib/email/signin-token";
import { welcomeUserIfNeeded } from "@/lib/email/welcome-user";
import { createClient } from "@/lib/supabase/server";
import { createServiceClient } from "@/lib/supabase/service";
import { getCachedSubscriptionTier } from "@/lib/subscription";

/**
 * One-click sign-in from a briefing email.
 *
 * This is the rung that was missing. 105 people had given a verified address
 * and 19 had an account, because nothing in the product ever asked — the
 * briefing's calls to action pointed at `/marketscreenings` and `/pricing`,
 * both of which resolve perfectly well while logged out. The email is the only
 * surface that reaches every subscriber on a schedule, so it is the only place
 * the ask can live.
 *
 * The flow is deliberately one click:
 *
 *   1. Verify our own HMAC assertion — that we sent this link to this address,
 *      recently, bound to this destination.
 *   2. Find or create the auth user. Creation is `email_confirm: true`, which
 *      is not a shortcut: they confirmed the address when they subscribed, and
 *      making them confirm a second time is the friction this route exists to
 *      remove.
 *   3. Mint a Supabase magic-link token server-side and immediately spend it,
 *      so the session lands in cookies without a second round trip through the
 *      inbox.
 *   4. Redirect to the destination that was signed into the token — a chart
 *      already scoped to the tickers the email was about.
 *
 * Failure always ends somewhere a human can act: an expired or replayed link
 * goes to the login page with a note, never to a stack trace. Expiry is the
 * expected case, not the exceptional one — a briefing from three weeks ago is
 * supposed to stop working.
 */

function fail(reason: string): never {
  redirect(`/auth/login?notice=${encodeURIComponent(reason)}`);
}

export async function GET(request: NextRequest) {
  const token = new URL(request.url).searchParams.get("token");
  if (!token) fail("That link is missing its token. Sign in to continue.");

  const payload = verifySigninToken(token);
  if (!payload) {
    // Covers expired, tampered, and manage-token-replayed-here. They are not
    // distinguished on purpose: the honest message is the same and the
    // difference is only useful to someone probing.
    fail("That sign-in link has expired. Sign in to pick up where you left off.");
  }

  const { email, next } = payload;
  // Belt and braces: `next` is inside the signature, but a signature proves we
  // minted it, not that it is safe to send a freshly-authenticated browser to.
  const destination = isSafeNext(next) ? next : "/protected";

  const admin = createServiceClient();

  // `generateLink({type:"magiclink"})` requires the user to already exist, and
  // the admin API has no lookup-by-email (`getUserByEmail` is not in
  // supabase-js 2.x; `listUsers` cannot filter). So creation is the probe:
  // create unconditionally and treat "already registered" as the success it is.
  // One call, no race — two subscribers clicking at once both end up signed in
  // rather than one of them hitting a duplicate-key error.
  const { error: createError } = await admin.auth.admin.createUser({
    email,
    email_confirm: true,
    user_metadata: { signup_source: "briefing_email" },
  });
  if (createError && !/already|exist|registered/i.test(createError.message ?? "")) {
    console.error("[auth/briefing] createUser failed:", createError.message);
    fail("We couldn't open your account. Sign in or sign up to continue.");
  }

  const { data: link, error: linkError } = await admin.auth.admin.generateLink({
    type: "magiclink",
    email,
  });
  if (linkError || !link?.properties?.hashed_token) {
    console.error("[auth/briefing] generateLink failed:", linkError?.message);
    fail("We couldn't sign you in from that link. Sign in to continue.");
  }

  // Spend the token against the cookie-bound client so the session is written
  // to this response, exactly as /auth/confirm does for email confirmations.
  const supabase = await createClient();
  const { error: otpError } = await supabase.auth.verifyOtp({
    // Match what we just generated rather than the generic "email": the token
    // was minted as a magiclink, and naming the same type on both sides keeps
    // the pair legible if either half is changed later.
    type: "magiclink",
    token_hash: link.properties.hashed_token,
  });
  if (otpError) {
    console.error("[auth/briefing] verifyOtp failed:", otpError.message);
    fail("We couldn't sign you in from that link. Sign in to continue.");
  }

  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (user) {
    await getCachedSubscriptionTier(user.id);
    await welcomeUserIfNeeded(user); // idempotent, metadata-flagged
  }

  redirect(destination);
}
