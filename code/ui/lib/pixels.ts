/**
 * Fire a "Lead" conversion to the ad platforms from the browser. Safe no-ops when
 * a pixel isn't loaded (env unset / blocked), so callers never need to guard.
 */

declare global {
  interface Window {
    fbq?: (...args: unknown[]) => void;
    ttq?: { track: (event: string, params?: Record<string, unknown>) => void };
  }
}

type LeadParams = { content_name?: string; value?: number; currency?: string };

/** A completed email subscribe = a Lead. `content_name` should be the feature. */
export function trackLead(params: LeadParams = {}): void {
  try {
    window.fbq?.("track", "Lead", params);
  } catch {
    /* pixel not loaded */
  }
  try {
    window.ttq?.track("SubmitForm", params);
  } catch {
    /* pixel not loaded */
  }
}

export {};
