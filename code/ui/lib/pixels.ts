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

/**
 * Meta's own first-party cookies, written by the base pixel: `_fbc` is the ad
 * CLICK id (set when a visitor arrives with ?fbclid=…), `_fbp` the browser id.
 *
 * These are the difference between a server event Meta can attribute to a
 * specific ad and one it can only fuzzy-match on a hashed email. The Subscribe
 * event in the Stripe webhook fires long after the browser is gone, so the ids
 * have to be collected here, at checkout, and carried through Stripe metadata.
 */
export function getMetaClickIds(): { fbc?: string; fbp?: string } {
  if (typeof document === "undefined") return {};
  const out: { fbc?: string; fbp?: string } = {};
  for (const c of document.cookie.split("; ")) {
    if (c.startsWith("_fbc=")) out.fbc = decodeURIComponent(c.slice(5)).slice(0, 400);
    else if (c.startsWith("_fbp=")) out.fbp = decodeURIComponent(c.slice(5)).slice(0, 400);
  }
  return out;
}

type CheckoutParams = {
  plan?: string;
  interval?: string;
  value?: number;
  currency?: string;
  trial?: boolean;
};

/**
 * Someone reached Stripe Checkout. This is the mid-funnel signal a paid campaign
 * actually optimizes on: `Subscribe` is the goal, but at a handful of sales a
 * week Meta can never exit the learning phase on it (it wants ~50/week), whereas
 * InitiateCheckout fires often enough to teach delivery who is worth showing the
 * ad to. Fired from the browser, so it carries the pixel's own cookies.
 */
export function trackInitiateCheckout(params: CheckoutParams = {}): void {
  const data: Record<string, unknown> = {
    currency: params.currency ?? "USD",
    content_category: "subscription",
  };
  if (params.plan) data.content_name = params.plan;
  if (params.value != null) data.value = params.value;
  if (params.interval) data.content_type = params.interval;
  try {
    window.fbq?.("track", "InitiateCheckout", data);
  } catch {
    /* pixel not loaded */
  }
  try {
    window.ttq?.track("InitiateCheckout", data);
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
