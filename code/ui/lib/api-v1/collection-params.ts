const DEFAULT_LIMIT = 20;
const MAX_LIMIT = 100;

export type OffsetPagination = { limit: number; offset: number };

/**
 * Offset pagination: `limit` (default 20, max 100), `offset` (default 0).
 */
export function parseOffsetPagination(
  searchParams: URLSearchParams,
): { ok: true; value: OffsetPagination } | { ok: false; message: string } {
  const rawLimit = searchParams.get("limit");
  const rawOffset = searchParams.get("offset");

  let limit = DEFAULT_LIMIT;
  if (rawLimit !== null && rawLimit !== "") {
    const n = parseInt(rawLimit, 10);
    if (Number.isNaN(n) || n < 1) {
      return { ok: false, message: "'limit' must be a positive integer" };
    }
    limit = Math.min(n, MAX_LIMIT);
  }

  let offset = 0;
  if (rawOffset !== null && rawOffset !== "") {
    const n = parseInt(rawOffset, 10);
    if (Number.isNaN(n) || n < 0) {
      return { ok: false, message: "'offset' must be a non-negative integer" };
    }
    offset = n;
  }

  return { ok: true, value: { limit, offset } };
}

export type SortSpec = { column: string; ascending: boolean };

/**
 * Sort: `sort=created_at` (asc) or `sort=-created_at` (desc). Leading `-` means descending.
 */
export function parseSort(
  searchParams: URLSearchParams,
  allowed: readonly string[],
  defaultColumn: string,
  defaultAscending: boolean,
): { ok: true; value: SortSpec } | { ok: false; message: string } {
  const raw = searchParams.get("sort");
  if (raw === null || raw === "") {
    return { ok: true, value: { column: defaultColumn, ascending: defaultAscending } };
  }
  const descending = raw.startsWith("-");
  const column = descending ? raw.slice(1) : raw;
  if (!allowed.includes(column)) {
    return {
      ok: false,
      message: `'sort' must be one of: ${allowed.map((c) => `${c}, -${c}`).join(", ")}`,
    };
  }
  return { ok: true, value: { column, ascending: !descending } };
}

/**
 * Field selection: `fields=id,cluster,confidence` — unknown fields are rejected.
 */
export function parseFieldsList(
  searchParams: URLSearchParams,
  allowed: ReadonlySet<string>,
): { ok: true; value: string[] | null } | { ok: false; message: string } {
  const raw = searchParams.get("fields");
  if (raw === null || raw === "") {
    return { ok: true, value: null };
  }
  const parts = raw
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  if (parts.length === 0) {
    return { ok: true, value: null };
  }
  for (const p of parts) {
    if (!allowed.has(p)) {
      return { ok: false, message: `Unknown field in 'fields': ${p}` };
    }
  }
  return { ok: true, value: parts };
}

/**
 * Include related data: `include=article` or comma-separated. If the param is omitted, use `defaults`.
 * If present as empty string, no includes.
 */
export function parseIncludeSet(
  searchParams: URLSearchParams,
  allowed: ReadonlySet<string>,
  defaults: ReadonlySet<string>,
): { ok: true; value: Set<string> } | { ok: false; message: string } {
  if (!searchParams.has("include")) {
    return { ok: true, value: new Set(defaults) };
  }
  const raw = searchParams.get("include") ?? "";
  if (raw === "") {
    return { ok: true, value: new Set() };
  }
  const parts = raw
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  for (const p of parts) {
    if (!allowed.has(p)) {
      return { ok: false, message: `Unknown relation in 'include': ${p}` };
    }
  }
  return { ok: true, value: new Set(parts) };
}
