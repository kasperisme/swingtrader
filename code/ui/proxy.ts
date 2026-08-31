import { updateSession } from "@/lib/supabase/proxy";
import { NextResponse, type NextRequest } from "next/server";

export async function proxy(request: NextRequest) {
  // Handle CORS preflight for the versioned public API
  if (
    request.method === "OPTIONS" &&
    request.nextUrl.pathname.startsWith("/api/v1/")
  ) {
    return new NextResponse(null, {
      status: 204,
      headers: {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, OPTIONS",
        "Access-Control-Allow-Headers": "Authorization",
        "Access-Control-Max-Age": "86400",
      },
    });
  }

  // Canonical-case ticker URLs. `/quote/nvda` and `/quote/NVDA` are the same
  // page, and anchors in the wild are lowercase often enough to matter. Doing
  // it here rather than in the route: the quote page is prerendered under
  // Cache Components, where `permanentRedirect()` comes back as a 200 carrying
  // a client-side redirect — a soft redirect that costs a full render and is a
  // weaker signal than the 308 this issues before the route is touched.
  const quote = /^\/quote\/([^/]+)$/.exec(request.nextUrl.pathname);
  if (quote) {
    const raw = decodeURIComponent(quote[1]);
    const canonical = raw.trim().toUpperCase();
    if (canonical && canonical !== raw) {
      const url = request.nextUrl.clone();
      url.pathname = `/quote/${encodeURIComponent(canonical)}`;
      return NextResponse.redirect(url, 308);
    }
  }

  return updateSession(request);
}

export const config = {
  matcher: [
    // `.txt` was missing here, so /llms.txt — and any IndexNow key file —
    // 307ed to /auth/login for every logged-out client, crawlers included.
    "/((?!_next/static|_next/image|favicon\\.ico|sitemap\\.xml|robots\\.txt|.*\\.(?:txt|svg|png|jpg|jpeg|gif|webp|pdf|ico|woff|woff2|ttf|otf)$).*)",
  ],
};
