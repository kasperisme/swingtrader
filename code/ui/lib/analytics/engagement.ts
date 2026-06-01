"use client";

/**
 * Lightweight, page-scoped engagement signals for the signup flow:
 *  - dwell_ms  : time on page at the moment of signup (since navigation start)
 *  - scroll_pct: deepest scroll the visitor reached (0–100)
 *  - session_article_views: how many article pages they viewed this session
 *
 * One passive scroll listener, started as early as the module is imported.
 * All reads are best-effort and safe on the server (return zeros).
 */

let maxScrollPct = 0;
let tracking = false;

function ensureScrollTracking(): void {
  if (tracking || typeof window === "undefined") return;
  tracking = true;
  const update = () => {
    const doc = document.documentElement;
    const scrollable = doc.scrollHeight - window.innerHeight;
    const pct =
      scrollable > 0
        ? Math.min(100, Math.round((window.scrollY / scrollable) * 100))
        : 100;
    if (pct > maxScrollPct) maxScrollPct = pct;
  };
  window.addEventListener("scroll", update, { passive: true });
  update();
}

export type Engagement = {
  dwell_ms: number;
  scroll_pct: number;
};

export function getEngagement(): Engagement {
  ensureScrollTracking();
  const dwell =
    typeof performance !== "undefined" ? Math.round(performance.now()) : 0;
  return { dwell_ms: dwell, scroll_pct: maxScrollPct };
}

const ARTICLE_VIEWS_KEY = "session_article_views";

/** Increment the per-session article-view counter (call once per article). */
export function bumpSessionArticleView(): void {
  if (typeof window === "undefined") return;
  try {
    const n =
      Number(window.sessionStorage.getItem(ARTICLE_VIEWS_KEY) || "0") + 1;
    window.sessionStorage.setItem(ARTICLE_VIEWS_KEY, String(n));
  } catch {
    // sessionStorage unavailable (private mode) — ignore.
  }
}

export function getSessionArticleViews(): number {
  if (typeof window === "undefined") return 0;
  try {
    return Number(window.sessionStorage.getItem(ARTICLE_VIEWS_KEY) || "0");
  } catch {
    return 0;
  }
}

// Start tracking scroll as soon as this module loads on the client.
ensureScrollTracking();
