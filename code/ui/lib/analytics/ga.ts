/**
 * Google Analytics 4 (gtag) — fire a GA4 event from the browser. Safe no-op when
 * gtag isn't loaded (blocked / env). The tag itself is configured in app/layout.tsx
 * (measurement id G-FQ87KHKLS5).
 *
 * Why this exists: GA4 was blind to sign-ups — the performance snapshot showed 0
 * conversions against real Supabase leads because no conversion event ever fired.
 * `track("lead_subscribed", …)` now forwards a GA4 `sign_up` event here, so once you
 * mark `sign_up` a **Key event** in GA4 the whole funnel (channels, landing, Meta CPL)
 * becomes measurable.
 */

declare global {
  interface Window {
    gtag?: (...args: unknown[]) => void;
  }
}

export function gaEvent(
  name: string,
  params: Record<string, unknown> = {},
): void {
  try {
    // strip undefined so GA4 doesn't record empty params
    const clean = Object.fromEntries(
      Object.entries(params).filter(([, v]) => v !== undefined && v !== null),
    );
    window.gtag?.("event", name, clean);
  } catch {
    /* gtag not loaded */
  }
}

export {};
