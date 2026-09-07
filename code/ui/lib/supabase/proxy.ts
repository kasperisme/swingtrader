import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";
import { hasEnvVars } from "../utils";

export async function updateSession(request: NextRequest) {
  let supabaseResponse = NextResponse.next({
    request,
  });

  // If the env vars are not set, skip proxy check. You can remove this
  // once you setup the project.
  if (!hasEnvVars) {
    return supabaseResponse;
  }

  // Defensive: if Supabase's redirect URL allowlist isn't configured for
  // /auth/callback, the OAuth `code` lands on /. Forward it so the proper
  // callback handler can do the code → session exchange.
  if (
    request.nextUrl.pathname === "/" &&
    request.nextUrl.searchParams.has("code")
  ) {
    const url = request.nextUrl.clone();
    url.pathname = "/auth/callback";
    if (!url.searchParams.has("next")) {
      url.searchParams.set("next", "/protected");
    }
    return NextResponse.redirect(url);
  }

  // With Fluid compute, don't put this client in a global environment
  // variable. Always create a new one on each request.
  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY!,
    {
      cookies: {
        getAll() {
          return request.cookies.getAll();
        },
        setAll(cookiesToSet) {
          cookiesToSet.forEach(({ name, value }) =>
            request.cookies.set(name, value),
          );
          supabaseResponse = NextResponse.next({
            request,
          });
          cookiesToSet.forEach(({ name, value, options }) =>
            supabaseResponse.cookies.set(name, value, options),
          );
        },
      },
    },
  );

  // Do not run code between createServerClient and
  // supabase.auth.getClaims(). A simple mistake could make it very hard to debug
  // issues with users being randomly logged out.

  // IMPORTANT: If you remove getClaims() and you use server-side rendering
  // with the Supabase client, your users may be randomly logged out.
  const { data } = await supabase.auth.getClaims();
  const user = data?.claims;

  const pathname = request.nextUrl.pathname;

  // Authed users hitting the marketing root → ops center.
  if (user && pathname === "/") {
    const url = request.nextUrl.clone();
    url.pathname = "/protected";
    return NextResponse.redirect(url);
  }
  // The gate is a DENY-list, not an allow-list, and the direction matters for
  // more than tidiness.
  //
  // It used to be an allow-list: every public path had to be enumerated, and
  // anything unlisted 307ed to /auth/login. So a URL matching NO route at all
  // — a typo, a stale inbound link, a crawler probing an old path — was
  // answered with a redirect into /auth/login, which robots.txt disallows.
  // Googlebot saw a redirect terminating in a blocked resource instead of a
  // 404, which is strictly worse: a 404 retires a URL, a redirect-to-blocked
  // leaves it in limbo to be re-crawled. The site reported no 404s at all.
  //
  // Inverted, an unmatched path falls through to Next's router and gets a real
  // 404. The cost is that a NEW private page is public until listed here —
  // which is why the page-level guards stay (every /protected page calls
  // redirect("/auth/login") itself) and why API routes keep the opposite
  // default below.
  const isPrivatePage =
    pathname.startsWith("/protected") ||
    pathname.startsWith("/studio") || // Sanity Studio — also has its own login
    pathname.startsWith("/x"); // OAuth callback shim

  // API routes keep DENY-by-default: an endpoint added tomorrow is private
  // until someone lists it. None of it is crawlable, so the argument above
  // does not apply, and the failure modes are asymmetric — a page wrongly
  // public leaks a screen, an endpoint wrongly public leaks data.
  const isPublicApi =
    pathname.startsWith("/api/v1") || // public API — uses its own Bearer auth
    pathname.startsWith("/api/news/semantic-search") || // mirrors the public /articles search
    pathname.startsWith("/api/briefings") || // subscribe/manage/unsub — token-signed
    pathname.startsWith("/api/market-screenings") || // read-only screening JSON
    pathname.startsWith("/api/stripe/checkout") || // creates session; has its own auth check
    pathname.startsWith("/api/telegram-webhook") || // authenticated by secret header
    pathname.startsWith("/api/early-access") || // public waitlist signup
    pathname.startsWith("/api/subscribe") || // public email-only screening signup
    pathname.startsWith("/api/unsubscribe"); // one-click unsubscribe, token-signed

  if (!user) {
    if (pathname.startsWith("/api/")) {
      // API routes return 401 rather than redirecting to the login page.
      if (!isPublicApi) {
        return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
      }
    } else if (isPrivatePage) {
      const url = request.nextUrl.clone();
      url.pathname = "/auth/login";
      return NextResponse.redirect(url);
    }
  }

  // IMPORTANT: You *must* return the supabaseResponse object as it is.
  // If you're creating a new response object with NextResponse.next() make sure to:
  // 1. Pass the request in it, like so:
  //    const myNewResponse = NextResponse.next({ request })
  // 2. Copy over the cookies, like so:
  //    myNewResponse.cookies.setAll(supabaseResponse.cookies.getAll())
  // 3. Change the myNewResponse object to fit your needs, but avoid changing
  //    the cookies!
  // 4. Finally:
  //    return myNewResponse
  // If this is not done, you may be causing the browser and server to go out
  // of sync and terminate the user's session prematurely!

  return supabaseResponse;
}
