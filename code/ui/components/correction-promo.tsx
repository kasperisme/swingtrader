"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { ArrowRight, X } from "lucide-react";
import { track } from "@/lib/analytics/events";
import { CorrectionSubscribeForm, CORRECTION_SUBSCRIBED_KEY } from "@/components/correction-subscribe-form";

/**
 * Site-wide nudge toward /correction (the drawdown stress test) for visitors who
 * have been around a while. Real readers land on one article and leave (Nov 2026:
 * 3% reach a second page), so this targets the ones who stay.
 *
 * Shows once per session, after VISIBLE_SECONDS of visible time on the site, or
 * after MIN_PAGES pages with at least MIN_SECONDS_WITH_PAGES. Never on /correction,
 * auth, member or studio pages, never after a signup, and not for DISMISS_DAYS
 * after a dismissal. A corner card, not a modal: it never blocks the article.
 */

const VISIBLE_SECONDS = 75;
const MIN_PAGES = 3;
const MIN_SECONDS_WITH_PAGES = 30;
const DISMISS_DAYS = 7;
const SESSION_KEY = "nis:site-engagement"; // {seconds, pages, shown}
const DISMISS_KEY = "nis:correction-promo-dismissed";
const EXCLUDED = ["/correction", "/auth", "/protected", "/studio", "/login", "/x/"];

type Engagement = { seconds: number; pages: number; shown: boolean };

function read(): Engagement {
  try {
    const v = JSON.parse(sessionStorage.getItem(SESSION_KEY) ?? "null") as Engagement | null;
    if (v && typeof v.seconds === "number") return v;
  } catch {
    /* blocked storage */
  }
  return { seconds: 0, pages: 0, shown: false };
}

function write(e: Engagement) {
  try {
    sessionStorage.setItem(SESSION_KEY, JSON.stringify(e));
  } catch {
    /* blocked storage: the promo simply never shows */
  }
}

function suppressed(): boolean {
  try {
    if (localStorage.getItem(CORRECTION_SUBSCRIBED_KEY)) return true;
    const at = Number(localStorage.getItem(DISMISS_KEY) ?? 0);
    return at > 0 && Date.now() - at < DISMISS_DAYS * 86_400_000;
  } catch {
    return true;
  }
}

export function CorrectionPromo() {
  const pathname = usePathname() ?? "/";
  const [open, setOpen] = useState(false);
  const lastPath = useRef<string | null>(null);
  const excluded = EXCLUDED.some((p) => pathname.startsWith(p));

  // Count pages; once the promo has been shown in this session it stays gone.
  useEffect(() => {
    if (lastPath.current === pathname) return;
    lastPath.current = pathname;
    const e = read();
    write({ ...e, pages: e.pages + 1 });
    if (excluded) setOpen(false);
  }, [pathname, excluded]);

  useEffect(() => {
    if (excluded || open) return;
    if (suppressed() || read().shown) return;
    const id = window.setInterval(() => {
      if (document.visibilityState !== "visible") return;
      const e = read();
      const next = { ...e, seconds: e.seconds + 5 };
      write(next);
      const due =
        next.seconds >= VISIBLE_SECONDS || (next.pages >= MIN_PAGES && next.seconds >= MIN_SECONDS_WITH_PAGES);
      if (due && !next.shown && !suppressed()) {
        write({ ...next, shown: true });
        setOpen(true);
        track("correction_promo_shown", { pathname, seconds_on_site: next.seconds, pageviews: next.pages });
        window.clearInterval(id);
      }
    }, 5000);
    return () => window.clearInterval(id);
  }, [excluded, open, pathname]);

  if (!open || excluded) return null;

  const dismiss = () => {
    try {
      localStorage.setItem(DISMISS_KEY, String(Date.now()));
    } catch {
      /* ignore */
    }
    track("correction_promo_clicked", { action: "dismiss" });
    setOpen(false);
  };

  return (
    <aside
      role="dialog"
      aria-labelledby="correction-promo-title"
      className="fixed inset-x-3 bottom-3 z-[60] rounded-2xl border border-border bg-background/95 p-5 shadow-2xl backdrop-blur-md animate-in fade-in slide-in-from-bottom-4 duration-300 sm:inset-x-auto sm:right-5 sm:bottom-5 sm:w-[380px]"
    >
      <button
        type="button"
        onClick={dismiss}
        aria-label="Dismiss"
        className="absolute right-3 top-3 rounded-md p-1 text-muted-foreground transition-colors hover:text-foreground"
      >
        <X className="h-4 w-4" />
      </button>
      <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-amber-600 dark:text-amber-500">
        New · Correction stress test
      </p>
      <h2 id="correction-promo-title" className="mt-2 pr-6 text-base font-semibold leading-snug">
        The market sold off. Which stories still hold up?
      </h2>
      <p className="mt-1.5 text-sm text-muted-foreground">
        We re-solved what every share price needs to be true after the sell-off, and
        sorted the names into those that hold and those that drown.
      </p>
      <Link
        href="/correction"
        onClick={() => {
          track("correction_promo_clicked", { action: "open" });
          setOpen(false);
        }}
        className="mt-3 inline-flex items-center gap-1.5 text-sm font-medium text-foreground underline-offset-4 hover:underline"
      >
        See the stress test <ArrowRight className="h-3.5 w-3.5" />
      </Link>
      <div className="mt-4 border-t border-border pt-4">
        <p className="mb-2 text-xs font-medium text-muted-foreground">Get an email when the next analysis is out</p>
        <CorrectionSubscribeForm
          source="correction_promo"
          compact
          onSubscribed={() => track("correction_promo_clicked", { action: "subscribe" })}
        />
      </div>
    </aside>
  );
}
