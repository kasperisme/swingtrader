/**
 * Sanitise the client-supplied attribution blob before it's persisted. Never
 * trust the client: whitelist known keys, coerce to strings, truncate, cap size.
 */

const ALLOWED = new Set([
  "utm_source",
  "utm_medium",
  "utm_campaign",
  "utm_content",
  "utm_term",
  "fbclid",
  "ttclid",
  "gclid",
  "landing",
]);

export function cleanAttribution(v: unknown): Record<string, string> {
  if (!v || typeof v !== "object") return {};
  const out: Record<string, string> = {};
  for (const [k, val] of Object.entries(v as Record<string, unknown>)) {
    if (!ALLOWED.has(k) || typeof val !== "string" || !val) continue;
    out[k] = val.slice(0, 200);
    if (Object.keys(out).length >= 12) break;
  }
  return out;
}
