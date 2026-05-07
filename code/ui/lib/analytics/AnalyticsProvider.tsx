"use client";

import { Suspense, useEffect, useRef } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import { getPosthog } from "./posthog";

function PageviewTracker() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const previousPathname = useRef<string | null>(null);

  useEffect(() => {
    const ph = getPosthog();
    if (!ph || !pathname) return;

    ph.capture("$pageview", {
      pathname,
      previous_pathname: previousPathname.current,
    });

    previousPathname.current = pathname;
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

    void supabase.auth.getUser().then(({ data }) => identify(data.user ?? null));

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
