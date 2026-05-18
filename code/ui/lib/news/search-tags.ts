/** Theme/event slug (lowercase snake_case). */
export function slugifyThemeTag(raw: string): string {
  return raw
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 48);
}

/** Normalize a tag for GIN overlap search (uppercase tickers, slugified themes). */
export function normalizeSearchTag(raw: string): string {
  const t = String(raw ?? "").trim();
  if (!t) return "";
  if (/^[A-Z]{1,6}$/.test(t)) return t;
  if (/^[a-z]{1,6}$/.test(t) && !t.includes("_")) return t.toUpperCase();
  return slugifyThemeTag(t);
}

export function tagsFromQuery(query: string): string[] {
  const tokens = query
    .split(/[\s,]+/)
    .map(normalizeSearchTag)
    .filter((t) => t.length >= 2);
  return [...new Set(tokens)];
}
