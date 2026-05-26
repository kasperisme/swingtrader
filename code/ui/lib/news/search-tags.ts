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

/**
 * A search token is ambiguous: a short lowercase word like "japan", "iran" or
 * "oil" could be a theme slug (stored lowercase) or a ticker (stored
 * uppercase). `normalizeSearchTag` has to commit to one form and uppercases
 * short words, which then misses lowercase theme tags. For matching against
 * the GIN-indexed `search_tags`, expand each token into every plausible stored
 * form so an overlap matches whichever the article actually carries.
 */
export function expandSearchTagCandidates(raw: string): string[] {
  const t = String(raw ?? "").trim();
  if (!t) return [];
  const out = new Set<string>();
  const slug = slugifyThemeTag(t); // lowercase theme form
  if (slug) out.add(slug);
  if (/^[a-zA-Z]{1,6}$/.test(t)) out.add(t.toUpperCase()); // ticker form
  return [...out];
}

/** Expand every ≥2-char token of a free-text query into tag candidates. */
export function tagCandidatesFromQuery(query: string): string[] {
  const out = new Set<string>();
  for (const tok of query.split(/[\s,]+/)) {
    if (tok.trim().length < 2) continue;
    for (const c of expandSearchTagCandidates(tok)) out.add(c);
  }
  return [...out];
}
