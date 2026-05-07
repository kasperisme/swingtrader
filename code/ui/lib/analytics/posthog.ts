"use client";

import posthog, { type PostHog } from "posthog-js";

let initialized = false;

export function getPosthog(): PostHog | null {
  if (typeof window === "undefined") return null;
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
