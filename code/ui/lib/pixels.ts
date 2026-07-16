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

type ScreeningDownloadParams = {
  content_name?: string; // screening name or slug
  format?: "csv" | "json";
  source?: string; // which link/surface triggered it
};

/**
 * Someone grabbed a market screening's results (CSV download or JSON open).
 * Meta has no standard "Download" event, so this fires a **custom** event —
 * build a Custom Audience of downloaders (and lookalikes) from it, or promote
 * it to a Custom Conversion to optimize delivery toward people who download.
 * TikTok does have a standard `Download` event, so use it there.
 */
export function trackScreeningDownload(params: ScreeningDownloadParams = {}): void {
  const data: Record<string, unknown> = { content_type: "market_screening" };
  if (params.content_name) data.content_name = params.content_name;
  if (params.format) data.content_category = params.format;
  if (params.source) data.source = params.source;
  try {
    window.fbq?.("trackCustom", "DownloadScreening", data);
  } catch {
    /* pixel not loaded */
  }
  try {
    window.ttq?.track("Download", data);
  } catch {
    /* pixel not loaded */
  }
}

export {};
