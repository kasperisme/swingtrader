import { welcomeUserIfNeeded } from "@/lib/email/welcome-user";
import { createClient } from "@/lib/supabase/server";
import { getCachedSubscriptionTier } from "@/lib/subscription";
import { NextResponse } from "next/server";

export async function GET(request: Request) {
  const { searchParams, origin } = new URL(request.url);
  const code = searchParams.get("code");
  let next = searchParams.get("next") ?? "/protected";
  if (!next.startsWith("/")) {
    next = "/protected";
  }

  if (code) {
    const supabase = await createClient();
    const { error } = await supabase.auth.exchangeCodeForSession(code);
    if (!error) {
      const {
        data: { user },
      } = await supabase.auth.getUser();
      if (user) {
        // Side effects — never block the redirect if they fail.
        try {
          await getCachedSubscriptionTier(user.id);
        } catch (e) {
          console.error("[auth/callback] tier prime failed", e);
        }
        try {
          await welcomeUserIfNeeded(user);
        } catch (e) {
          console.error("[auth/callback] welcome email failed", e);
        }
      }

      const forwardedHost = request.headers.get("x-forwarded-host");
      const isLocalEnv = process.env.NODE_ENV === "development";
      if (isLocalEnv) {
        return NextResponse.redirect(`${origin}${next}`);
      } else if (forwardedHost) {
        return NextResponse.redirect(`https://${forwardedHost}${next}`);
      } else {
        return NextResponse.redirect(`${origin}${next}`);
      }
    }
    return NextResponse.redirect(
      `${origin}/auth/error?error=${encodeURIComponent(error.message)}`,
    );
  }

  return NextResponse.redirect(
    `${origin}/auth/error?error=${encodeURIComponent("Missing OAuth code")}`,
  );
}
