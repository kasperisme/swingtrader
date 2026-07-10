/**
 * Client-side ad attribution — capture UTM + click-id params on the landing URL
 * so they can ride along with a subscribe. First-touch wins (a 90-day cookie), so
 * a visitor who lands from an ad and subscribes later still attributes correctly.
 */

const KEY = "nis_attr";
const CAPTURE = [
  "utm_source",
  "utm_medium",
  "utm_campaign",
  "utm_content",
  "utm_term",
  "fbclid",
  "ttclid",
  "gclid",
] as const;

export type Attribution = Record<string, string>;

function readCookie(): Attribution | null {
  if (typeof document === "undefined") return null;
  const hit = document.cookie
    .split("; ")
    .find((c) => c.startsWith(`${KEY}=`));
  if (!hit) return null;
  try {
    return JSON.parse(decodeURIComponent(hit.slice(KEY.length + 1)));
  } catch {
    return null;
  }
}

/** Capture first-touch attribution from the current URL. Call once on mount. */
export function captureAttribution(): void {
  if (typeof window === "undefined") return;
  if (readCookie()) return; // first touch already recorded — keep it
  const p = new URLSearchParams(window.location.search);
  const out: Attribution = {};
  for (const k of CAPTURE) {
    const v = p.get(k);
    if (v) out[k] = v.slice(0, 200);
  }
  if (Object.keys(out).length === 0) return; // organic visit — nothing to store
  out.landing = window.location.pathname.slice(0, 200);
  const maxAge = 60 * 60 * 24 * 90;
  document.cookie = `${KEY}=${encodeURIComponent(JSON.stringify(out))}; path=/; max-age=${maxAge}; SameSite=Lax`;
}

/** The stored first-touch attribution (empty for organic visitors). */
export function getAttribution(): Attribution {
  return readCookie() ?? {};
}
