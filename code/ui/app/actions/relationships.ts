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

const BLOCKED_NODE_LABELS = new Set(["N/A"]);

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

async function resolveTickerClientSide(input: string): Promise<string> {
  const supabase = await createClient();
  const norm = input.trim().toLowerCase();
  if (!norm) return "";

  const tickerRes = await supabase
    .schema("swingtrader")
    .from("security_identity_map")
    .select("canonical_ticker, verified, confidence, id")
    .eq("alias_kind", "ticker")
    .eq("alias_value_norm", norm)
    .order("verified", { ascending: false })
    .order("confidence", { ascending: false })
    .order("id", { ascending: true })
    .limit(1);

  if (!tickerRes.error && tickerRes.data?.[0]?.canonical_ticker) {
    return normalizeTicker(String(tickerRes.data[0].canonical_ticker));
  }

  const nameRes = await supabase
    .schema("swingtrader")
    .from("security_identity_map")
    .select("canonical_ticker, verified, confidence, id")
    .eq("alias_kind", "company_name")
    .eq("alias_value_norm", norm)
    .order("verified", { ascending: false })
    .order("confidence", { ascending: false })
    .order("id", { ascending: true })
    .limit(1);

  if (!nameRes.error && nameRes.data?.[0]?.canonical_ticker) {
    return normalizeTicker(String(nameRes.data[0].canonical_ticker));
  }

  return normalizeTicker(input);
}

export async function relationshipsResolveTicker(
  input: string,
): Promise<RelationshipActionSuccess<{ canonicalTicker: string }> | RelationshipActionError> {
  if (!input?.trim()) return { ok: false, error: "Ticker or company name is required" };
  const canonicalTicker = await resolveTickerClientSide(input);
  if (!canonicalTicker) return { ok: false, error: "Could not resolve ticker" };
  return { ok: true, data: { canonicalTicker } };
}

export async function relationshipsGetNeighborhood(
  params: NeighborhoodParams,
): Promise<
  RelationshipActionSuccess<{ seedTicker: string; nodes: string[]; edges: RelationshipEdge[]; truncated: boolean }> | RelationshipActionError
> {
  if (!params.seedTicker?.trim()) return { ok: false, error: "seedTicker is required" };

  // Enforce hard cap: network traversal never exceeds 2 hops.
  const hops = Math.max(1, Math.min(2, Math.floor(params.hops ?? 2)));
  const minStrength = Math.max(0, Math.min(1, params.minStrength ?? 0.25));
  const minMentions = Math.max(1, params.minMentions ?? 1);
  const limitNodes = Math.max(20, params.limitNodes ?? 120);
  const limitEdges = Math.max(50, params.limitEdges ?? 300);
  const relTypes =
    params.relTypes?.map((t) => t.trim().toLowerCase()).filter(Boolean) ?? [];

  const seedTicker = await resolveTickerClientSide(params.seedTicker);
  const supabase = await createClient();

  let query = supabase
    .schema("swingtrader")
    .from("ticker_relationship_network_resolved_v")
    .select(
      "from_ticker,to_ticker,rel_type,strength_avg,strength_max,mention_count,article_count,first_seen_at,last_seen_at",
    )
    .gte("strength_avg", minStrength)
    .gte("mention_count", minMentions)
    .order("strength_avg", { ascending: false })
    .limit(5000);

  if (relTypes.length > 0) query = query.in("rel_type", relTypes);
  if (params.daysLookback && params.daysLookback > 0) {
    const cutoff = new Date(Date.now() - params.daysLookback * 24 * 60 * 60 * 1000).toISOString();
    query = query.gte("last_seen_at", cutoff);
  }

  const { data, error } = await query;
  if (error) return { ok: false, error: error.message };

  // Defensive collapse by canonical node key. The resolved view already canonicalizes,
  // but we collapse again here to guarantee alias-merged graph behavior in the UI.
  const mergedByKey = new Map<string, RelationshipEdge>();
  for (const row of data ?? []) {
    const fromTicker = normalizeTicker(String(row.from_ticker ?? ""));
    const toTicker = normalizeTicker(String(row.to_ticker ?? ""));
    const relType = String(row.rel_type ?? "").toLowerCase();
    if (!fromTicker || !toTicker || !relType || fromTicker === toTicker) continue;
    if (BLOCKED_NODE_LABELS.has(fromTicker) || BLOCKED_NODE_LABELS.has(toTicker)) continue;
    const key = `${fromTicker}|${toTicker}|${relType}`;
    const edge: RelationshipEdge = {
      from_ticker: fromTicker,
      to_ticker: toTicker,
      rel_type: relType,
      strength_avg: Number(row.strength_avg ?? 0),
      strength_max: Number(row.strength_max ?? 0),
      mention_count: Number(row.mention_count ?? 0),
      article_count: Number(row.article_count ?? 0),
      first_seen_at: row.first_seen_at ? String(row.first_seen_at) : null,
      last_seen_at: row.last_seen_at ? String(row.last_seen_at) : null,
    };
    const prev = mergedByKey.get(key);
    if (!prev) {
      mergedByKey.set(key, edge);
      continue;
    }
    const prevWeight = Math.max(1, prev.mention_count);
    const nextWeight = Math.max(1, edge.mention_count);
    const totalWeight = prevWeight + nextWeight;
    mergedByKey.set(key, {
      ...prev,
      strength_avg:
        (prev.strength_avg * prevWeight + edge.strength_avg * nextWeight) / totalWeight,
      strength_max: Math.max(prev.strength_max, edge.strength_max),
      mention_count: prev.mention_count + edge.mention_count,
      article_count: prev.article_count + edge.article_count,
      first_seen_at:
        prev.first_seen_at && edge.first_seen_at
          ? (prev.first_seen_at < edge.first_seen_at ? prev.first_seen_at : edge.first_seen_at)
          : prev.first_seen_at ?? edge.first_seen_at,
      last_seen_at:
        prev.last_seen_at && edge.last_seen_at
          ? (prev.last_seen_at > edge.last_seen_at ? prev.last_seen_at : edge.last_seen_at)
          : prev.last_seen_at ?? edge.last_seen_at,
    });
  }
  const allEdges = Array.from(mergedByKey.values());

  const visited = new Set<string>([seedTicker]);
  const depthBy = new Map<string, number>([[seedTicker, 0]]);
  const queue: string[] = [seedTicker];
  const keptEdges: RelationshipEdge[] = [];

  while (queue.length > 0 && visited.size < limitNodes && keptEdges.length < limitEdges) {
    const current = queue.shift()!;
    const currentDepth = depthBy.get(current) ?? 0;
    if (currentDepth >= hops) continue;
    const neighbors = allEdges.filter(
      (e) => e.from_ticker === current || e.to_ticker === current,
    );
    for (const edge of neighbors) {
      if (keptEdges.length >= limitEdges) break;
      keptEdges.push(edge);
      const next = edge.from_ticker === current ? edge.to_ticker : edge.from_ticker;
      if (!visited.has(next) && visited.size < limitNodes) {
        visited.add(next);
        depthBy.set(next, currentDepth + 1);
        queue.push(next);
      }
    }
  }

  return {
    ok: true,
    data: {
      seedTicker,
      nodes: Array.from(visited).sort(),
      edges: keptEdges,
      truncated: visited.size >= limitNodes || keptEdges.length >= limitEdges,
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
  const from = (page - 1) * pageSize;
  const to = from + pageSize - 1;
  const daysLookback =
    typeof input.daysLookback === "number" && input.daysLookback > 0
      ? Math.max(1, input.daysLookback)
      : null;

  const canonicalTicker = await resolveTickerClientSide(ticker);
  const supabase = await createClient();

  const { data: aliasRows, error: aliasError } = await supabase
    .schema("swingtrader")
    .from("security_identity_map")
    .select("alias_kind,alias_value")
    .eq("canonical_ticker", canonicalTicker)
    .eq("alias_kind", "ticker");
  if (aliasError) return { ok: false, error: aliasError.message };

  const tickers = Array.from(
    new Set([
      canonicalTicker,
      ...(aliasRows ?? []).map((r) => normalizeTicker(String(r.alias_value ?? ""))).filter(Boolean),
    ]),
  );
  const cutoff = daysLookback
    ? new Date(Date.now() - daysLookback * 24 * 60 * 60 * 1000).toISOString()
    : null;

  // Primary source: graph traceability evidence (edge -> article).
  // This guarantees returned articles are directly tied to network edges.
  const fromTraceQuery = cutoff
    ? supabase
        .schema("swingtrader")
        .from("ticker_relationship_edge_traceability_v")
        .select("article_id,article_title,article_url,published_at,from_ticker,to_ticker")
        .in("from_ticker", tickers)
        .gte("published_at", cutoff)
        .order("published_at", { ascending: false })
        .range(0, 300)
    : supabase
        .schema("swingtrader")
        .from("ticker_relationship_edge_traceability_v")
        .select("article_id,article_title,article_url,published_at,from_ticker,to_ticker")
        .in("from_ticker", tickers)
        .order("published_at", { ascending: false })
        .range(0, 300);
  const { data: fromTraceRows, error: fromTraceError } = await fromTraceQuery;
  if (fromTraceError) return { ok: false, error: fromTraceError.message };

  const toTraceQuery = cutoff
    ? supabase
        .schema("swingtrader")
        .from("ticker_relationship_edge_traceability_v")
        .select("article_id,article_title,article_url,published_at,from_ticker,to_ticker")
        .in("to_ticker", tickers)
        .gte("published_at", cutoff)
        .order("published_at", { ascending: false })
        .range(0, 300)
    : supabase
        .schema("swingtrader")
        .from("ticker_relationship_edge_traceability_v")
        .select("article_id,article_title,article_url,published_at,from_ticker,to_ticker")
        .in("to_ticker", tickers)
        .order("published_at", { ascending: false })
        .range(0, 300);
  const { data: toTraceRows, error: toTraceError } = await toTraceQuery;
  if (toTraceError) return { ok: false, error: toTraceError.message };

  const dedupByArticle = new Map<number, NodeNewsRow>();
  for (const row of [...(fromTraceRows ?? []), ...(toTraceRows ?? [])]) {
    const articleId = Number(row.article_id ?? 0);
    if (!Number.isFinite(articleId) || articleId <= 0) continue;
    if (dedupByArticle.has(articleId)) continue;
    dedupByArticle.set(articleId, {
      article_id: articleId,
      title: row.article_title ? String(row.article_title) : null,
      url: row.article_url ? String(row.article_url) : null,
      source: "traceability",
      publisher: null,
      published_at: row.published_at ? String(row.published_at) : null,
      matched_ticker:
        normalizeTicker(String(row.from_ticker ?? "")) === canonicalTicker
          ? canonicalTicker
          : normalizeTicker(String(row.to_ticker ?? canonicalTicker)),
    });
  }

  // Fallback source: direct ticker mentions from article tickers.
  const { data: tickerRows, error: tickerError } = await supabase
    .schema("swingtrader")
    .from("news_article_tickers")
    .select("article_id,ticker")
    .in("ticker", tickers)
    .range(0, 800);

  if (tickerError) return { ok: false, error: tickerError.message };

  const tickerByArticleId = new Map<number, string>();
  const articleIds: number[] = [];
  for (const row of tickerRows ?? []) {
    const articleId = Number((row as { article_id?: unknown }).article_id ?? 0);
    if (!Number.isFinite(articleId) || articleId <= 0) continue;
    if (!tickerByArticleId.has(articleId)) {
      tickerByArticleId.set(articleId, normalizeTicker(String((row as { ticker?: unknown }).ticker ?? canonicalTicker)));
      articleIds.push(articleId);
    }
  }

  if (articleIds.length > 0) {
    const articleQuery = cutoff
      ? supabase
          .schema("swingtrader")
          .from("news_articles")
          .select("id,title,url,source,publisher,published_at,created_at")
          .in("id", articleIds)
          .gte("published_at", cutoff)
          .order("published_at", { ascending: false })
          .limit(500)
      : supabase
          .schema("swingtrader")
          .from("news_articles")
          .select("id,title,url,source,publisher,published_at,created_at")
          .in("id", articleIds)
          .order("published_at", { ascending: false })
          .limit(500);
    const { data: articleRows, error: articleError } = await articleQuery;

    if (articleError) return { ok: false, error: articleError.message };

    for (const article of articleRows ?? []) {
      const articleId = Number((article as { id?: unknown }).id ?? 0);
      if (!Number.isFinite(articleId) || articleId <= 0) continue;
      if (dedupByArticle.has(articleId)) continue;
      dedupByArticle.set(articleId, {
        article_id: articleId,
        title: (article as any).title ? String((article as any).title) : null,
        url: (article as any).url ? String((article as any).url) : null,
        source: (article as any).source ? String((article as any).source) : null,
        publisher: (article as any).publisher ? String((article as any).publisher) : null,
        published_at: (article as any).published_at
          ? String((article as any).published_at)
          : (article as any).created_at
            ? String((article as any).created_at)
            : null,
        matched_ticker: tickerByArticleId.get(articleId) ?? canonicalTicker,
      });
    }
  }

  const allRows = Array.from(dedupByArticle.values()).sort((a, b) => {
    const ta = a.published_at ? Date.parse(a.published_at) : 0;
    const tb = b.published_at ? Date.parse(b.published_at) : 0;
    return tb - ta;
  });
  const rows = allRows.slice(from, to + 1);

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
  const from = (page - 1) * pageSize;
  const to = from + pageSize - 1;

  const canonicalTicker = await resolveTickerClientSide(ticker);
  const supabase = await createClient();

  const { data: aliasRows, error: aliasError } = await supabase
    .schema("swingtrader")
    .from("security_identity_map")
    .select("alias_kind,alias_value")
    .eq("canonical_ticker", canonicalTicker)
    .eq("alias_kind", "ticker");
  if (aliasError) return { ok: false, error: aliasError.message };

  const tickers = Array.from(
    new Set([
      canonicalTicker,
      ...(aliasRows ?? []).map((r) => normalizeTicker(String(r.alias_value ?? ""))).filter(Boolean),
    ]),
  );

  const { data, error } = await supabase
    .schema("swingtrader")
    .from("ticker_sentiment_heads_v")
    .select(
      "head_id,article_id,ticker,sentiment_score,reasoning_text,confidence,article_ts,published_at,article_source,article_publisher,article_title,article_url",
    )
    .in("ticker", tickers)
    .order("article_ts", { ascending: false, nullsFirst: false })
    .range(from, to);
  if (error) return { ok: false, error: error.message };

  const rows: NodeSentimentRow[] = (data ?? []).map((row) => ({
    head_id: Number(row.head_id ?? 0),
    article_id: Number(row.article_id ?? 0),
    ticker: normalizeTicker(String(row.ticker ?? "")),
    sentiment_score: Number(row.sentiment_score ?? 0),
    reasoning_text: row.reasoning_text ? String(row.reasoning_text) : null,
    confidence: row.confidence == null ? null : Number(row.confidence),
    article_ts: row.article_ts ? String(row.article_ts) : null,
    published_at: row.published_at ? String(row.published_at) : null,
    article_source: row.article_source ? String(row.article_source) : null,
    article_publisher: row.article_publisher ? String(row.article_publisher) : null,
    article_title: row.article_title ? String(row.article_title) : null,
    article_url: row.article_url ? String(row.article_url) : null,
  }));

  const windowsDef: Array<10 | 21 | 50 | 200> = [10, 21, 50, 200];
  const maxDays = 200;
  const cutoff = new Date(Date.now() - maxDays * 24 * 60 * 60 * 1000).toISOString();
  const { data: aggData, error: aggError } = await supabase
    .schema("swingtrader")
    .from("ticker_sentiment_heads_v")
    .select("sentiment_score,confidence,article_ts")
    .in("ticker", tickers)
    .gte("article_ts", cutoff)
    .order("article_ts", { ascending: false })
    .limit(5000);
  if (aggError) return { ok: false, error: aggError.message };

  const nowMs = Date.now();
  const aggregates = (aggData ?? []).flatMap((row) => {
    const ts = row.article_ts ? Date.parse(String(row.article_ts)) : NaN;
    const sentiment = Number(row.sentiment_score ?? NaN);
    const confidence =
      row.confidence == null ? 1 : Math.max(0, Math.min(1, Number(row.confidence)));
    if (!Number.isFinite(ts) || !Number.isFinite(sentiment)) return [];
    const ageDays = (nowMs - ts) / (24 * 60 * 60 * 1000);
    return [{ ageDays, sentiment, confidence }];
  });

  const windows: NodeSentimentWindow[] = windowsDef.map((days) => {
    const within = aggregates.filter((r) => r.ageDays <= days);
    if (within.length === 0) {
      return { days, avg_sentiment: null, weighted_sentiment: null, mention_count: 0 };
    }
    const avg = within.reduce((sum, r) => sum + r.sentiment, 0) / within.length;
    const weightSum = within.reduce((sum, r) => sum + r.confidence, 0);
    const weighted =
      weightSum > 0
        ? within.reduce((sum, r) => sum + r.sentiment * r.confidence, 0) / weightSum
        : null;
    return {
      days,
      avg_sentiment: avg,
      weighted_sentiment: weighted,
      mention_count: within.length,
    };
  });

  return { ok: true, data: { canonicalTicker, rows, windows, page, pageSize } };
}
