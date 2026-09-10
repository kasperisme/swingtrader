"use client";

import { Suspense, useEffect, useRef } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import { getPosthog } from "./posthog";

function PageviewTracker() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const previousPathname = useRef<string | null>(null);
  // Keyed on path + query, not path alone: /articles?tag=MPC -> /articles?tag=NVDA
  // is a real navigation to a reader, and treating it as the same page loses
  // both the leave event and the scroll figures for the first one.
  const previousKey = useRef<string | null>(null);

  useEffect(() => {
    const ph = getPosthog();
    if (!ph || !pathname) return;

    const key = searchParams?.toString()
      ? `${pathname}?${searchParams.toString()}`
      : pathname;

    // A manual-pageview SPA has to emit $pageleave manually too.
    //
    // PostHog's automatic pageleave fires on pagehide/beforeunload — an actual
    // document unload. In the App Router that happens when the tab closes and
    // never on a client-side route change, so almost every navigation went
    // unrecorded: 35 $pageleave events against 1,590 article pageviews.
    //
    // It is not just a missing count. The scroll figures
    // ($prev_pageview_max_scroll_percentage, $prev_pageview_max_content_percentage)
    // ride on this event, so without it scroll depth is unmeasurable — which is
    // exactly the number you want when asking why readers do not reach the
    // links at the bottom of an article.
    //
    // Order matters: $pageleave closes out the page being left and carries its
    // scroll properties; the new $pageview then opens the next one.
    if (previousKey.current && previousKey.current !== key) {
      ph.capture("$pageleave");
    }

    ph.capture("$pageview", {
      pathname,
      previous_pathname: previousPathname.current,
    });

    previousPathname.current = pathname;
    previousKey.current = key;
  }, [pathname, searchParams]);

  return null;
}

function IdentityTracker() {
  useEffect(() => {
    const ph = getPosthog();
    if (!ph) return;

    const supabase = createClient();
    let cancelled = false;

    const identify = (user: { id: string; email?: string | null } | null) => {
      if (cancelled || !ph) return;
      if (user) {
        ph.identify(user.id, {
          email: user.email ?? undefined,
        });
      } else {
        ph.reset();
      }
    };

    void supabase.auth.getClaims().then(({ data }) => {
      const c = data?.claims;
      if (!c?.sub) {
        identify(null);
        return;
      }
      identify({
        id: c.sub,
        email: typeof c.email === "string" ? c.email : null,
      });
    });

    const { data: sub } = supabase.auth.onAuthStateChange((event, session) => {
      if (event === "SIGNED_OUT") {
        identify(null);
      } else if (session?.user) {
        identify(session.user);
      }
    });

    return () => {
      cancelled = true;
      sub.subscription.unsubscribe();
    };
  }, []);

  return null;
}

export function AnalyticsProvider() {
  useEffect(() => {
    getPosthog();
  }, []);

  return (
    <>
      <Suspense fallback={null}>
        <PageviewTracker />
      </Suspense>
      <IdentityTracker />
    </>
  );
}
