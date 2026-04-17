import { createServiceClient } from "@/lib/supabase/service";
import { parseSort } from "@/lib/api-v1/collection-params";

const EDGE_DEFAULT_LIMIT = 100;
const EDGE_MAX_LIMIT = 500;
const EVIDENCE_DEFAULT_LIMIT = 50;
const EVIDENCE_MAX_LIMIT = 200;

const EDGE_SORTABLE = [
  "last_seen_at",
  "first_seen_at",
  "strength_avg",
  "strength_max",
  "mention_count",
  "article_count",
] as const;

function parseEdgePagination(
  sp: URLSearchParams,
): { ok: true; value: { limit: number; offset: number } } | { ok: false; message: string } {
  const rawLimit = sp.get("limit");
  const rawOffset = sp.get("offset");
  let limit = EDGE_DEFAULT_LIMIT;
  if (rawLimit !== null && rawLimit !== "") {
    const n = parseInt(rawLimit, 10);
    if (Number.isNaN(n) || n < 1) return { ok: false, message: "'limit' must be a positive integer" };
    limit = Math.min(n, EDGE_MAX_LIMIT);
  }
  let offset = 0;
  if (rawOffset !== null && rawOffset !== "") {
    const n = parseInt(rawOffset, 10);
    if (Number.isNaN(n) || n < 0) return { ok: false, message: "'offset' must be a non-negative integer" };
    offset = n;
  }
  return { ok: true, value: { limit, offset } };
}

function parseEvidencePagination(
  sp: URLSearchParams,
): { ok: true; value: { limit: number; offset: number } } | { ok: false; message: string } {
  const rawLimit = sp.get("limit");
  const rawOffset = sp.get("offset");
  let limit = EVIDENCE_DEFAULT_LIMIT;
  if (rawLimit !== null && rawLimit !== "") {
    const n = parseInt(rawLimit, 10);
    if (Number.isNaN(n) || n < 1) return { ok: false, message: "'limit' must be a positive integer" };
    limit = Math.min(n, EVIDENCE_MAX_LIMIT);
  }
  let offset = 0;
  if (rawOffset !== null && rawOffset !== "") {
    const n = parseInt(rawOffset, 10);
    if (Number.isNaN(n) || n < 0) return { ok: false, message: "'offset' must be a non-negative integer" };
    offset = n;
  }
  return { ok: true, value: { limit, offset } };
}

function normalizeTicker(raw: string | null, maxLen = 16): string | null {
  if (raw === null || raw === "") return null;
  const t = raw.toUpperCase().replace(/\s+/g, "").slice(0, maxLen);
  return t === "" ? null : t;
}

function parseResolved(sp: URLSearchParams): boolean {
  const v = (sp.get("resolved") ?? "true").toLowerCase();
  return v !== "false" && v !== "0";
}

/**
 * Graph edges from `ticker_relationship_network_resolved_v` (canonical tickers, merged)
 * or `ticker_relationship_network_v` (raw stored endpoints).
 */
export async function listRelationshipNetworkEdgesFromSearchParams(sp: URLSearchParams) {
  const pag = parseEdgePagination(sp);
  if (!pag.ok) return { ok: false, status: 400, message: pag.message } as const;

  const sort = parseSort(sp, [...EDGE_SORTABLE], "last_seen_at", false);
  if (!sort.ok) return { ok: false, status: 400, message: sort.message } as const;

  const resolved = parseResolved(sp);
  const table = resolved
    ? "ticker_relationship_network_resolved_v"
    : "ticker_relationship_network_v";

  const touching = normalizeTicker(sp.get("touching"), 16);
  const relType = sp.get("rel_type")?.trim().toLowerCase() ?? null;
  if (relType !== null && relType.length > 64) {
    return { ok: false, status: 400, message: "'rel_type' too long" } as const;
  }

  const minS = sp.get("min_strength_avg");
  let minStrength: number | null = null;
  if (minS !== null && minS !== "") {
    const n = Number(minS);
    if (Number.isNaN(n) || n < 0 || n > 1) {
      return { ok: false, status: 400, message: "'min_strength_avg' must be between 0 and 1" } as const;
    }
    minStrength = n;
  }

  const selectCols =
    "from_ticker, to_ticker, rel_type, strength_avg, strength_max, mention_count, article_count, first_seen_at, last_seen_at";

  const supabase = createServiceClient();
  let q = supabase
    .schema("swingtrader")
    .from(table)
    .select(selectCols, { count: "exact" })
    .order(sort.value.column, { ascending: sort.value.ascending })
    .range(pag.value.offset, pag.value.offset + pag.value.limit - 1);

  if (touching) {
    q = q.or(`from_ticker.eq.${touching},to_ticker.eq.${touching}`);
  }
  if (relType) q = q.eq("rel_type", relType);
  if (minStrength !== null) q = q.gte("strength_avg", minStrength);

  const { data, error, count } = await q;
  if (error) return { ok: false, status: 500, message: "Internal error" } as const;

  return {
    ok: true as const,
    body: {
      resolved,
      data: data ?? [],
      pagination: { limit: pag.value.limit, offset: pag.value.offset, total: count ?? 0 },
    },
  };
}

/** Per-article evidence rows from `ticker_relationship_edge_traceability_v`. */
export async function listRelationshipEdgeEvidenceFromSearchParams(sp: URLSearchParams) {
  const fromT = normalizeTicker(sp.get("from_ticker"), 16);
  const toT = normalizeTicker(sp.get("to_ticker"), 16);
  if (!fromT || !toT) {
    return {
      ok: false,
      status: 400,
      message: "'from_ticker' and 'to_ticker' are required (uppercase symbols)",
    } as const;
  }

  const pag = parseEvidencePagination(sp);
  if (!pag.ok) return { ok: false, status: 400, message: pag.message } as const;

  const relType = sp.get("rel_type")?.trim().toLowerCase() ?? null;
  if (relType !== null && relType.length > 64) {
    return { ok: false, status: 400, message: "'rel_type' too long" } as const;
  }

  const supabase = createServiceClient();
  let q = supabase
    .schema("swingtrader")
    .from("ticker_relationship_edge_traceability_v")
    .select(
      "edge_id, from_ticker, to_ticker, rel_type, strength_avg, mention_count, article_id, article_title, article_url, published_at, pair_strength, head_confidence, reasoning_text, top_dimensions_snapshot, impact_json_snapshot",
      { count: "exact" },
    )
    .eq("from_ticker", fromT)
    .eq("to_ticker", toT)
    .order("published_at", { ascending: false, nullsFirst: false })
    .range(pag.value.offset, pag.value.offset + pag.value.limit - 1);

  if (relType) q = q.eq("rel_type", relType);

  const { data, error, count } = await q;
  if (error) return { ok: false, status: 500, message: "Internal error" } as const;

  return {
    ok: true as const,
    body: {
      data: data ?? [],
      pagination: { limit: pag.value.limit, offset: pag.value.offset, total: count ?? 0 },
    },
  };
}
