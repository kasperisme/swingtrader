"use client";

import { useEffect } from "react";

import { track } from "@/lib/analytics/events";
import { readValuePropVariantId } from "./value-prop-variants";

/**
 * Per-article engagement telemetry for ALL visitors (not just converters).
 *
 * Self-contained and SPA-safe: dwell is measured from this component's mount and
 * scroll depth is tracked locally, so client-side navigation between articles
 * gives accurate per-article numbers (unlike the global engagement.ts snapshot,
 * which is page-load-relative and shared across articles).
 *
 * Emits exactly one `article_engagement` event per article view, on the first
 * of: tab hidden, page hide (hard nav / close), or unmount (SPA route change).
 * Also fires the structured `article_opened` event on mount so analyses can key
 * off article_id rather than just the $pageview pathname.
 *
 *   article_opened → cta_exposed → waitlist_joined   (funnel)
 *   article_engagement                                (dwell / scroll / reached_cta)
 *
 * Plus `article_heartbeat` at 15/30/60/120s of VISIBLE time. The final event only
 * fires on tab-hide/pagehide, which most mobile exits never deliver (81% of real
 * article sessions in Nov 2026 had no article_engagement), so the milestones are
 * what separates "read, then left" from "left at once". At most four per view.
 *
 * PostHog only — no Supabase write. If you later want SQL joins on engagement,
 * add a thin insert here behind a small /api/article-engagement route.
 */
export function ArticleEngagementTracker({
  articleId,
  slug,
}: {
  articleId: number;
  slug: string;
}) {
  useEffect(() => {
    const mountedAt =
      typeof performance !== "undefined" ? performance.now() : 0;
    let maxScrollPct = 0;
    let reachedCta = false;
    let sent = false;

    // Structured open event — complements the $pageview pathname with article_id.
    track("article_opened", { article_id: String(articleId) });

    const updateScroll = () => {
      const doc = document.documentElement;
      const scrollable = doc.scrollHeight - window.innerHeight;
      const pct =
        scrollable > 0
          ? Math.min(100, Math.round((window.scrollY / scrollable) * 100))
          : 100;
      if (pct > maxScrollPct) maxScrollPct = pct;
    };
    updateScroll();
    window.addEventListener("scroll", updateScroll, { passive: true });

    // reached_cta: did the Tier-2 "go deeper" block (#early-access) come into
    // view? Observed independently so it works for members too (no email form).
    let ctaObserver: IntersectionObserver | null = null;
    const ctaEl = document.getElementById("early-access");
    if (ctaEl) {
      ctaObserver = new IntersectionObserver(
        (entries) => {
          if (entries.some((e) => e.isIntersecting)) {
            reachedCta = true;
            ctaObserver?.disconnect();
          }
        },
        { threshold: 0.4 },
      );
      ctaObserver.observe(ctaEl);
    }

    // Visible-time milestones. Time in a background tab does not count.
    const MILESTONES = [15, 30, 60, 120];
    let visibleMs = 0;
    let lastTick = mountedAt;
    let nextMilestone = 0;
    const tick = () => {
      const now = typeof performance !== "undefined" ? performance.now() : 0;
      if (document.visibilityState === "visible") visibleMs += now - lastTick;
      lastTick = now;
      while (nextMilestone < MILESTONES.length && visibleMs >= MILESTONES[nextMilestone] * 1000) {
        track("article_heartbeat", {
          article_id: articleId,
          slug,
          seconds: MILESTONES[nextMilestone],
          max_scroll_pct: maxScrollPct,
          reached_cta: reachedCta,
        });
        nextMilestone += 1;
      }
      if (nextMilestone >= MILESTONES.length) window.clearInterval(timer);
    };
    const timer = window.setInterval(tick, 5000);

    const flush = () => {
      if (sent) return;
      sent = true;
      const now = typeof performance !== "undefined" ? performance.now() : 0;
      track(
        "article_engagement",
        {
          article_id: articleId,
          slug,
          dwell_ms: Math.max(0, Math.round(now - mountedAt)),
          max_scroll_pct: maxScrollPct,
          reached_cta: reachedCta,
          value_prop_variant: readValuePropVariantId(),
        },
        { beacon: true },
      );
    };

    const onVisibility = () => {
      tick(); // bank the visible time before the tab goes to the background
      if (document.visibilityState === "hidden") flush();
    };
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("pagehide", flush);

    return () => {
      // SPA route change away from this article — capture the final state.
      flush();
      window.clearInterval(timer);
      window.removeEventListener("scroll", updateScroll);
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("pagehide", flush);
      ctaObserver?.disconnect();
    };
  }, [articleId, slug]);

  return null;
}
