"use client";

import { useEffect, useState } from "react";
import { ArrowDown, ArrowUp, X } from "lucide-react";

import { createClient } from "@/lib/supabase/client";

const DISMISS_KEY = "article_floating_cta_dismissed";

type Props = {
  /** Element id of the on-page early-access section to scroll to. */
  targetId?: string;
  /** Delay before the button appears, in milliseconds. */
  delayMs?: number;
  label?: string;
};

/**
 * Floating "Get early access" pill that fades in after the reader has spent
 * `delayMs` on the page, then smooth-scrolls to the on-page early-access form
 * and focuses its email input. Auto-hides while the form is already on screen
 * (no nagging) and stays dismissed for the rest of the browser session.
 */
export function FloatingCTA({
  targetId = "early-access",
  delayMs = 8000,
  label = "Get early access",
}: Props) {
  const [elapsed, setElapsed] = useState(false);
  const [dismissed, setDismissed] = useState(true); // assume dismissed until we read storage
  const [loggedOut, setLoggedOut] = useState(false); // only true once we confirm no session
  const [targetInView, setTargetInView] = useState(false);
  // Which way the CTA sits relative to the (bottom-anchored) button.
  const [direction, setDirection] = useState<"down" | "up">("down");

  // Honor a prior dismissal, confirm the visitor is logged out, then arm the
  // timer. Logged-in users already have access, so the pill never shows for them.
  useEffect(() => {
    const wasDismissed =
      typeof window !== "undefined" &&
      window.sessionStorage.getItem(DISMISS_KEY) === "1";
    setDismissed(wasDismissed);
    if (wasDismissed) return;

    let cancelled = false;
    let timer: number | undefined;
    createClient()
      .auth.getSession()
      .then(({ data: { session } }) => {
        if (cancelled || session) return;
        setLoggedOut(true);
        timer = window.setTimeout(() => setElapsed(true), delayMs);
      });
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [delayMs]);

  // Hide the pill whenever the early-access form itself is visible.
  useEffect(() => {
    const el = document.getElementById(targetId);
    if (!el) return;
    const obs = new IntersectionObserver(
      ([entry]) => {
        setTargetInView(entry.isIntersecting);
        // When the CTA is off-screen it sits wholly on one side: a positive
        // top means it's below the viewport (scroll down → arrow down), a
        // negative top means it's above (scroll up → arrow up).
        if (!entry.isIntersecting) {
          setDirection(entry.boundingClientRect.top > 0 ? "down" : "up");
        }
      },
      { threshold: 0.25 },
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [targetId]);

  const visible = elapsed && loggedOut && !dismissed && !targetInView;

  function handleScrollToForm() {
    const el = document.getElementById(targetId);
    if (!el) return;
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    // Focus the email field once the smooth scroll has settled.
    window.setTimeout(() => {
      el.querySelector<HTMLInputElement>('input[type="email"]')?.focus({
        preventScroll: true,
      });
    }, 600);
  }

  function handleDismiss() {
    setDismissed(true);
    try {
      window.sessionStorage.setItem(DISMISS_KEY, "1");
    } catch {
      // sessionStorage may be unavailable (private mode) — ignore.
    }
  }

  return (
    <div
      aria-hidden={!visible}
      className={`fixed inset-x-0 bottom-5 z-50 flex justify-center px-4 transition-all duration-500 ease-out ${
        visible
          ? "pointer-events-auto translate-y-0 opacity-100"
          : "pointer-events-none translate-y-4 opacity-0"
      }`}
    >
      <div className="flex items-center gap-1">
        <button
          type="button"
          onClick={handleScrollToForm}
          tabIndex={visible ? 0 : -1}
          className="group inline-flex items-center gap-2 rounded-full bg-amber-500 px-4 py-2 text-sm font-semibold text-background shadow-xl shadow-black/30 transition-colors hover:bg-amber-400"
        >
          {direction === "up" ? (
            <ArrowUp
              size={15}
              className="transition-transform duration-200 group-hover:-translate-y-0.5"
            />
          ) : (
            <ArrowDown
              size={15}
              className="transition-transform duration-200 group-hover:translate-y-0.5"
            />
          )}
          {label}
        </button>
        <button
          type="button"
          onClick={handleDismiss}
          tabIndex={visible ? 0 : -1}
          aria-label="Dismiss"
          className="inline-flex h-8 w-8 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-muted/60 hover:text-foreground"
        >
          <X size={15} />
        </button>
      </div>
    </div>
  );
}
