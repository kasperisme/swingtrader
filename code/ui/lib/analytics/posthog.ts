"use client";

import posthog, { type PostHog } from "posthog-js";

let initialized = false;

/**
 * Obvious browser automation, refused before PostHog initialises.
 *
 * Be clear about what this does and does not catch. It catches automation that
 * does not bother to hide: `navigator.webdriver`, and self-identifying user
 * agents. It does NOT catch the traffic that currently dominates this site's
 * article pages — roughly 84% of article pageviews arrive from Singapore and
 * China datacenter ranges, running real headless Chrome with the webdriver flag
 * patched out, and they are indistinguishable from a browser at this layer.
 *
 * The durable fix for those is upstream of the client, where the IP is
 * visible: a PostHog ingestion filter, or blocking at the edge. Anything
 * geo-based belongs there and not here, because real readers live in Singapore
 * too and dropping them in client code would be silent and wrong.
 *
 * This guard is worth having anyway: it is free, it cannot produce a false
 * positive on a human, and it keeps scripted checks out of the funnel.
 */
function isLikelyAutomation(): boolean {
  const nav = window.navigator;
  if (nav.webdriver) return true;
  return /headless|puppeteer|playwright|phantomjs|selenium|crawler|spider|\bbot\b/i.test(
    nav.userAgent ?? "",
  );
}

export function getPosthog(): PostHog | null {
  if (typeof window === "undefined") return null;
  if (isLikelyAutomation()) return null;
  if (!initialized) {
    const key = process.env.NEXT_PUBLIC_POSTHOG_KEY;
    if (!key) return null;
    posthog.init(key, {
      api_host: process.env.NEXT_PUBLIC_POSTHOG_HOST ?? "/ingest",
      ui_host: "https://eu.posthog.com",
      person_profiles: "identified_only",
      capture_pageview: false,
      capture_pageleave: true,
      autocapture: {
        dom_event_allowlist: ["click", "change", "submit"],
      },
      enable_heatmaps: true,
      rageclick: true,
      session_recording: {
        maskAllInputs: true,
        maskTextSelector: "[data-private]",
      },
      loaded: (ph) => {
        if (process.env.NODE_ENV === "development") ph.debug(false);
      },
    });
    initialized = true;
  }
  return posthog;
}
