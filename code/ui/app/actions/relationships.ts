"use server";

import { createClient } from "@/lib/supabase/server";

type RelationshipActionError = { ok: false; error: string };
type RelationshipActionSuccess<T> = { ok: true; data: T };

export type RelationshipEdge = {
  from_ticker: string;
  to_ticker: string;
  rel_type: string;
  strength_avg: number;
  strength_max: number;
  mention_count: number;
  article_count: number;
  first_seen_at: string | null;
  last_seen_at: string | null;
};

export type EdgeEvidence = {
  edge_id: number;
  from_ticker: string;
  to_ticker: string;
  rel_type: string;
  strength_avg: number;
  mention_count: number;
  article_id: number;
  article_title: string | null;
  article_url: string | null;
  published_at: string | null;
  pair_strength: number | null;
  head_confidence: number | null;
  reasoning_text: string | null;
  top_dimensions_snapshot: Record<string, number> | null;
  impact_json_snapshot: Record<string, number> | null;
};

export type AliasRow = {
  alias_kind: string;
  alias_value: string;
  canonical_ticker: string;
  confidence: number;
  verified: boolean;
  source: string;
};

export type AliasMap = Record<string, string[]>;

export type NodeNewsRow = {
  article_id: number;
  title: string | null;
  url: string | null;
  source: string | null;
  publisher: string | null;
  published_at: string | null;
  matched_ticker: string;
};

export type NodeSentimentRow = {
  head_id: number;
  article_id: number;
  ticker: string;
  sentiment_score: number;
  reasoning_text: string | null;
  confidence: number | null;
  article_ts: string | null;
  published_at: string | null;
  article_source: string | null;
  article_publisher: string | null;
  article_title: string | null;
  article_url: string | null;
};

export type NodeSentimentWindow = {
  days: 10 | 21 | 50 | 200;
  avg_sentiment: number | null;
  weighted_sentiment: number | null;
  mention_count: number;
};

export type NeighborhoodParams = {
  seedTicker: string;
  hops?: number;
  minStrength?: number;
  minMentions?: number;
  relTypes?: string[];
  limitNodes?: number;
  limitEdges?: number;
  daysLookback?: number;
};

function toRecordNumberMap(v: unknown): Record<string, number> | null {
  if (!v || typeof v !== "object" || Array.isArray(v)) return null;
  const out: Record<string, number> = {};
  for (const [k, raw] of Object.entries(v as Record<string, unknown>)) {
    const n = Number(raw);
    if (Number.isFinite(n)) out[k] = n;
  }
  return out;
}

function normalizeTicker(value: string): string {
  return value.trim().toUpperCase();
}

export async function relationshipsResolveTicker(
  input: string,
): Promise<RelationshipActionSuccess<{ canonicalTicker: string }> | RelationshipActionError> {
  if (!input?.trim()) return { ok: false, error: "Ticker or company name is required" };
  const supabase = await createClient();
  const { data, error } = await supabase
    .schema("swingtrader")
    .rpc("resolve_canonical_ticker", { p_alias_value: input, p_alias_kind: "ticker" });
  if (error) return { ok: false, error: error.message };
  const canonicalTicker = normalizeTicker(String(data ?? ""));
  if (!canonicalTicker) return { ok: false, error: "Could not resolve ticker" };
  return { ok: true, data: { canonicalTicker } };
}

export async function relationshipsGetNeighborhood(
  params: NeighborhoodParams,
): Promise<
  RelationshipActionSuccess<{ seedTicker: string; nodes: string[]; edges: RelationshipEdge[]; truncated: boolean }> | RelationshipActionError
> {
  if (!params.seedTicker?.trim()) return { ok: false, error: "seedTicker is required" };

  const hops = Math.max(1, Math.min(2, Math.floor(params.hops ?? 2)));
  const minStrength = Math.max(0, Math.min(1, params.minStrength ?? 0.25));
  const minMentions = Math.max(1, params.minMentions ?? 1);
  const limitNodes = Math.max(20, params.limitNodes ?? 120);
  const limitEdges = Math.max(50, params.limitEdges ?? 300);
  const relTypes = params.relTypes?.map((t) => t.trim().toLowerCase()).filter(Boolean) ?? [];
  const supabase = await createClient();
  const { data, error } = await supabase.schema("swingtrader").rpc("get_relationship_neighborhood", {
    p_seed: params.seedTicker,
    p_hops: hops,
    p_min_strength: minStrength,
    p_min_mentions: minMentions,
    p_rel_types: relTypes.length > 0 ? relTypes : null,
    p_limit_nodes: limitNodes,
    p_limit_edges: limitEdges,
    p_days_lookback: params.daysLookback && params.daysLookback > 0 ? params.daysLookback : null,
  });
  if (error) return { ok: false, error: error.message };
  const rows = Array.isArray(data) ? data : [];
  const nodes = new Set<string>();
  const edges: RelationshipEdge[] = [];
  let seedTicker = normalizeTicker(params.seedTicker);
  let truncated = false;

  for (const row of rows) {
    const rowType = String((row as { row_type?: unknown }).row_type ?? "");
    const rowSeed = normalizeTicker(String((row as { seed_ticker?: unknown }).seed_ticker ?? ""));
    if (rowSeed) seedTicker = rowSeed;
    truncated = truncated || Boolean((row as { truncated?: unknown }).truncated);

    if (rowType === "node") {
      const nodeTicker = normalizeTicker(String((row as { node_ticker?: unknown }).node_ticker ?? ""));
      if (nodeTicker) nodes.add(nodeTicker);
      continue;
    }
    if (rowType !== "edge") continue;

    const fromTicker = normalizeTicker(String((row as { from_ticker?: unknown }).from_ticker ?? ""));
    const toTicker = normalizeTicker(String((row as { to_ticker?: unknown }).to_ticker ?? ""));
    const relType = String((row as { rel_type?: unknown }).rel_type ?? "").toLowerCase();
    if (!fromTicker || !toTicker || !relType || fromTicker === toTicker) continue;
    nodes.add(fromTicker);
    nodes.add(toTicker);
    edges.push({
      from_ticker: fromTicker,
      to_ticker: toTicker,
      rel_type: relType,
      strength_avg: Number((row as { strength_avg?: unknown }).strength_avg ?? 0),
      strength_max: Number((row as { strength_max?: unknown }).strength_max ?? 0),
      mention_count: Number((row as { mention_count?: unknown }).mention_count ?? 0),
      article_count: Number((row as { article_count?: unknown }).article_count ?? 0),
      first_seen_at: (row as { first_seen_at?: unknown }).first_seen_at
        ? String((row as { first_seen_at?: unknown }).first_seen_at)
        : null,
      last_seen_at: (row as { last_seen_at?: unknown }).last_seen_at
        ? String((row as { last_seen_at?: unknown }).last_seen_at)
        : null,
    });
  }
  if (seedTicker) nodes.add(seedTicker);

  return {
    ok: true,
    data: {
      seedTicker,
      nodes: Array.from(nodes).sort(),
      edges,
      truncated,
    },
  };
}

export async function relationshipsGetEdgeEvidence(input: {
  fromTicker: string;
  toTicker: string;
  relType?: string;
  page?: number;
  pageSize?: number;
}): Promise<
  RelationshipActionSuccess<{ rows: EdgeEvidence[]; page: number; pageSize: number }> | RelationshipActionError
> {
  const fromTicker = normalizeTicker(input.fromTicker ?? "");
  const toTicker = normalizeTicker(input.toTicker ?? "");
  if (!fromTicker || !toTicker) return { ok: false, error: "fromTicker and toTicker are required" };

  const page = Math.max(1, input.page ?? 1);
  const pageSize = Math.min(50, Math.max(5, input.pageSize ?? 12));
  const from = (page - 1) * pageSize;
  const to = from + pageSize - 1;

  const supabase = await createClient();
  let query = supabase
    .schema("swingtrader")
    .from("ticker_relationship_edge_traceability_v")
    .select(
      "edge_id,from_ticker,to_ticker,rel_type,strength_avg,mention_count,article_id,article_title,article_url,published_at,pair_strength,head_confidence,reasoning_text,top_dimensions_snapshot,impact_json_snapshot",
    )
    .eq("from_ticker", fromTicker)
    .eq("to_ticker", toTicker)
    .order("published_at", { ascending: false })
    .range(from, to);

  if (input.relType?.trim()) query = query.eq("rel_type", input.relType.trim().toLowerCase());

  const { data, error } = await query;
  if (error) return { ok: false, error: error.message };

  const rows: EdgeEvidence[] = (data ?? []).map((row) => ({
    edge_id: Number(row.edge_id ?? 0),
    from_ticker: normalizeTicker(String(row.from_ticker ?? "")),
    to_ticker: normalizeTicker(String(row.to_ticker ?? "")),
    rel_type: String(row.rel_type ?? "").toLowerCase(),
    strength_avg: Number(row.strength_avg ?? 0),
    mention_count: Number(row.mention_count ?? 0),
    article_id: Number(row.article_id ?? 0),
    article_title: row.article_title ? String(row.article_title) : null,
    article_url: row.article_url ? String(row.article_url) : null,
    published_at: row.published_at ? String(row.published_at) : null,
    pair_strength: row.pair_strength == null ? null : Number(row.pair_strength),
    head_confidence: row.head_confidence == null ? null : Number(row.head_confidence),
    reasoning_text: row.reasoning_text ? String(row.reasoning_text) : null,
    top_dimensions_snapshot: toRecordNumberMap(row.top_dimensions_snapshot),
    impact_json_snapshot: toRecordNumberMap(row.impact_json_snapshot),
  }));

  return { ok: true, data: { rows, page, pageSize } };
}

export async function relationshipsGetAliases(
  canonicalTicker: string,
): Promise<RelationshipActionSuccess<AliasRow[]> | RelationshipActionError> {
  const ticker = normalizeTicker(canonicalTicker ?? "");
  if (!ticker) return { ok: false, error: "canonicalTicker is required" };
  const supabase = await createClient();

  const { data, error } = await supabase
    .schema("swingtrader")
    .from("security_identity_map")
    .select("alias_kind,alias_value,canonical_ticker,confidence,verified,source")
    .eq("canonical_ticker", ticker)
    .order("verified", { ascending: false })
    .order("confidence", { ascending: false })
    .limit(100);

  if (error) return { ok: false, error: error.message };

  const rows: AliasRow[] = (data ?? []).map((row) => ({
    alias_kind: String(row.alias_kind ?? ""),
    alias_value: String(row.alias_value ?? ""),
    canonical_ticker: normalizeTicker(String(row.canonical_ticker ?? "")),
    confidence: Number(row.confidence ?? 0),
    verified: Boolean(row.verified),
    source: String(row.source ?? ""),
  }));

  return { ok: true, data: rows };
}

export async function relationshipsGetAliasesBulk(
  canonicalTickers: string[],
): Promise<RelationshipActionSuccess<AliasMap> | RelationshipActionError> {
  const tickers = Array.from(
    new Set(canonicalTickers.map((t) => normalizeTicker(t)).filter(Boolean)),
  );
  if (tickers.length === 0) return { ok: true, data: {} };
  const supabase = await createClient();
  const { data, error } = await supabase
    .schema("swingtrader")
    .from("security_identity_map")
    .select("canonical_ticker,alias_kind,alias_value,verified,confidence")
    .in("canonical_ticker", tickers)
    .order("verified", { ascending: false })
    .order("confidence", { ascending: false })
    .limit(5000);

  if (error) return { ok: false, error: error.message };
  const out: AliasMap = {};
  for (const ticker of tickers) out[ticker] = [];
  for (const row of data ?? []) {
    const canonical = normalizeTicker(String(row.canonical_ticker ?? ""));
    const aliasKind = String(row.alias_kind ?? "");
    const aliasValue = String(row.alias_value ?? "").trim();
    if (!canonical || !aliasValue || aliasKind !== "ticker") continue;
    if (aliasValue.toUpperCase() === canonical) continue;
    const list = out[canonical] ?? [];
    if (!list.includes(aliasValue.toUpperCase())) list.push(aliasValue.toUpperCase());
    out[canonical] = list;
  }
  return { ok: true, data: out };
}

export async function relationshipsGetNodeNews(input: {
  ticker: string;
  page?: number;
  pageSize?: number;
  daysLookback?: number;
}): Promise<
  RelationshipActionSuccess<{ canonicalTicker: string; rows: NodeNewsRow[]; page: number; pageSize: number }>
  | RelationshipActionError
> {
  const ticker = normalizeTicker(input.ticker ?? "");
  if (!ticker) return { ok: false, error: "ticker is required" };
  const page = Math.max(1, input.page ?? 1);
  const pageSize = Math.min(30, Math.max(5, input.pageSize ?? 12));
  const daysLookback =
    typeof input.daysLookback === "number" && input.daysLookback > 0
      ? Math.max(1, input.daysLookback)
      : null;

  const supabase = await createClient();
  const { data, error } = await supabase.schema("swingtrader").rpc("get_relationship_node_news", {
    p_ticker: ticker,
    p_page: page,
    p_page_size: pageSize,
    p_days_lookback: daysLookback,
  });
  if (error) return { ok: false, error: error.message };

  const rpcRows = Array.isArray(data) ? data : [];
  const canonicalTicker = normalizeTicker(
    String((rpcRows[0] as { canonical_ticker?: unknown } | undefined)?.canonical_ticker ?? ticker),
  );
  const rows: NodeNewsRow[] = rpcRows.map((row) => ({
    article_id: Number((row as { article_id?: unknown }).article_id ?? 0),
    title: (row as { title?: unknown }).title ? String((row as { title?: unknown }).title) : null,
    url: (row as { url?: unknown }).url ? String((row as { url?: unknown }).url) : null,
    source: (row as { source?: unknown }).source ? String((row as { source?: unknown }).source) : null,
    publisher: (row as { publisher?: unknown }).publisher
      ? String((row as { publisher?: unknown }).publisher)
      : null,
    published_at: (row as { published_at?: unknown }).published_at
      ? String((row as { published_at?: unknown }).published_at)
      : null,
    matched_ticker: normalizeTicker(
      String((row as { matched_ticker?: unknown }).matched_ticker ?? canonicalTicker),
    ),
  }));

  return { ok: true, data: { canonicalTicker, rows, page, pageSize } };
}

export async function relationshipsGetNodeSentiment(input: {
  ticker: string;
  page?: number;
  pageSize?: number;
}): Promise<
  RelationshipActionSuccess<{
    canonicalTicker: string;
    rows: NodeSentimentRow[];
    windows: NodeSentimentWindow[];
    page: number;
    pageSize: number;
  }>
  | RelationshipActionError
> {
  const ticker = normalizeTicker(input.ticker ?? "");
  if (!ticker) return { ok: false, error: "ticker is required" };
  const page = Math.max(1, input.page ?? 1);
  const pageSize = Math.min(50, Math.max(5, input.pageSize ?? 12));

  const supabase = await createClient();
  const { data, error } = await supabase.schema("swingtrader").rpc("get_relationship_node_sentiment", {
    p_ticker: ticker,
    p_page: page,
    p_page_size: pageSize,
  });
  if (error) return { ok: false, error: error.message };
  const rpcRows = Array.isArray(data) ? data : [];
  const canonicalTicker = normalizeTicker(
    String((rpcRows[0] as { canonical_ticker?: unknown } | undefined)?.canonical_ticker ?? ticker),
  );
  const rows: NodeSentimentRow[] = rpcRows.map((row) => ({
    head_id: Number((row as { head_id?: unknown }).head_id ?? 0),
    article_id: Number((row as { article_id?: unknown }).article_id ?? 0),
    ticker: normalizeTicker(String((row as { ticker?: unknown }).ticker ?? "")),
    sentiment_score: Number((row as { sentiment_score?: unknown }).sentiment_score ?? 0),
    reasoning_text: (row as { reasoning_text?: unknown }).reasoning_text
      ? String((row as { reasoning_text?: unknown }).reasoning_text)
      : null,
    confidence: (row as { confidence?: unknown }).confidence == null
      ? null
      : Number((row as { confidence?: unknown }).confidence),
    article_ts: (row as { article_ts?: unknown }).article_ts
      ? String((row as { article_ts?: unknown }).article_ts)
      : null,
    published_at: (row as { published_at?: unknown }).published_at
      ? String((row as { published_at?: unknown }).published_at)
      : null,
    article_source: (row as { article_source?: unknown }).article_source
      ? String((row as { article_source?: unknown }).article_source)
      : null,
    article_publisher: (row as { article_publisher?: unknown }).article_publisher
      ? String((row as { article_publisher?: unknown }).article_publisher)
      : null,
    article_title: (row as { article_title?: unknown }).article_title
      ? String((row as { article_title?: unknown }).article_title)
      : null,
    article_url: (row as { article_url?: unknown }).article_url
      ? String((row as { article_url?: unknown }).article_url)
      : null,
  }));
  const { data: windowsData, error: windowsError } = await supabase
    .schema("swingtrader")
    .rpc("get_relationship_node_sentiment_windows", { p_ticker: ticker });
  if (windowsError) return { ok: false, error: windowsError.message };
  const windows: NodeSentimentWindow[] = (Array.isArray(windowsData) ? windowsData : [])
    .map((row) => {
      const days = Number((row as { days?: unknown }).days ?? 0);
      if (days !== 10 && days !== 21 && days !== 50 && days !== 200) return null;
      return {
        days,
        avg_sentiment: (row as { avg_sentiment?: unknown }).avg_sentiment == null
          ? null
          : Number((row as { avg_sentiment?: unknown }).avg_sentiment),
        weighted_sentiment: (row as { weighted_sentiment?: unknown }).weighted_sentiment == null
          ? null
          : Number((row as { weighted_sentiment?: unknown }).weighted_sentiment),
        mention_count: Number((row as { mention_count?: unknown }).mention_count ?? 0),
      };
    })
    .filter((row): row is NodeSentimentWindow => row !== null);

  return { ok: true, data: { canonicalTicker, rows, windows, page, pageSize } };
}
