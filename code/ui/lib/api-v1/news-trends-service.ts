import { createServiceClient } from "@/lib/supabase/service";

const TRENDS_DEFAULT_LIMIT = 500;
const TRENDS_MAX_LIMIT = 5000;

export type Granularity = "daily" | "hourly";

function parseGranularity(sp: URLSearchParams): { ok: true; value: Granularity } | { ok: false; message: string } {
  const raw = (sp.get("granularity") ?? "daily").toLowerCase();
  if (raw === "daily" || raw === "hourly") return { ok: true, value: raw };
  return { ok: false, message: "'granularity' must be 'daily' or 'hourly'" };
}

function parseTrendsPagination(
  sp: URLSearchParams,
): { ok: true; value: { limit: number; offset: number } } | { ok: false; message: string } {
  const rawLimit = sp.get("limit");
  const rawOffset = sp.get("offset");
  let limit = TRENDS_DEFAULT_LIMIT;
  if (rawLimit !== null && rawLimit !== "") {
    const n = parseInt(rawLimit, 10);
    if (Number.isNaN(n) || n < 1) {
      return { ok: false, message: "'limit' must be a positive integer" };
    }
    limit = Math.min(n, TRENDS_MAX_LIMIT);
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

function parseIso(name: string, raw: string | null): { ok: true; value: string | null } | { ok: false; message: string } {
  if (raw === null || raw === "") return { ok: true, value: null };
  const t = Date.parse(raw);
  if (Number.isNaN(t)) return { ok: false, message: `'${name}' must be a valid ISO 8601 date` };
  return { ok: true, value: new Date(t).toISOString() };
}

function normalizeTicker(raw: string | null, maxLen = 16): string | null {
  if (raw === null || raw === "") return null;
  const t = raw.toUpperCase().replace(/\s+/g, "").slice(0, maxLen);
  return t === "" ? null : t;
}

/** GET /api/v1/news/trends/articles — `news_trends_article_base_v` */
export async function listNewsTrendsArticlesFromSearchParams(sp: URLSearchParams) {
  const pag = parseTrendsPagination(sp);
  if (!pag.ok) return { ok: false, status: 400, message: pag.message } as const;

  const fromR = parseIso("from", sp.get("from"));
  if (!fromR.ok) return { ok: false, status: 400, message: fromR.message } as const;
  const toR = parseIso("to", sp.get("to"));
  if (!toR.ok) return { ok: false, status: 400, message: toR.message } as const;

  const supabase = createServiceClient();
  let q = supabase
    .schema("swingtrader")
    .from("news_trends_article_base_v")
    .select(
      "article_id, published_at, bucket_day, bucket_hour, impact_jsonb, confidence_mean, id, title, url, source, slug, image_url, article_created_at",
      { count: "exact" },
    )
    .order("published_at", { ascending: true })
    .range(pag.value.offset, pag.value.offset + pag.value.limit - 1);

  if (fromR.value) q = q.gte("published_at", fromR.value);
  if (toR.value) q = q.lte("published_at", toR.value);

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

/** `news_trends_dimension_daily_v` | `news_trends_dimension_hourly_v` */
export async function listNewsTrendsDimensionsFromSearchParams(sp: URLSearchParams) {
  const g = parseGranularity(sp);
  if (!g.ok) return { ok: false, status: 400, message: g.message } as const;

  const pag = parseTrendsPagination(sp);
  if (!pag.ok) return { ok: false, status: 400, message: pag.message } as const;

  const fromR = parseIso("from", sp.get("from"));
  if (!fromR.ok) return { ok: false, status: 400, message: fromR.message } as const;
  const toR = parseIso("to", sp.get("to"));
  if (!toR.ok) return { ok: false, status: 400, message: toR.message } as const;

  const dimensionKey = sp.get("dimension_key")?.trim() ?? null;
  if (dimensionKey !== null && dimensionKey.length > 96) {
    return { ok: false, status: 400, message: "'dimension_key' too long" } as const;
  }

  const table =
    g.value === "daily" ? "news_trends_dimension_daily_v" : "news_trends_dimension_hourly_v";
  const bucketCol = g.value === "daily" ? "bucket_day" : "bucket_hour";

  const supabase = createServiceClient();
  const selectCols =
    g.value === "daily"
      ? "bucket_day, dimension_key, bucket_article_count, sample_count, article_count, dimension_avg, dimension_weighted_avg"
      : "bucket_hour, dimension_key, bucket_article_count, sample_count, article_count, dimension_avg, dimension_weighted_avg";

  let q = supabase
    .schema("swingtrader")
    .from(table)
    .select(selectCols, { count: "exact" })
    .order(bucketCol, { ascending: true })
    .range(pag.value.offset, pag.value.offset + pag.value.limit - 1);

  if (fromR.value) q = q.gte(bucketCol, fromR.value);
  if (toR.value) q = q.lte(bucketCol, toR.value);
  if (dimensionKey) q = q.eq("dimension_key", dimensionKey);

  const { data, error, count } = await q;
  if (error) return { ok: false, status: 500, message: "Internal error" } as const;

  return {
    ok: true as const,
    body: {
      granularity: g.value,
      data: data ?? [],
      pagination: { limit: pag.value.limit, offset: pag.value.offset, total: count ?? 0 },
    },
  };
}

/** `news_trends_cluster_daily_v` | `news_trends_cluster_hourly_v` */
export async function listNewsTrendsClustersFromSearchParams(sp: URLSearchParams) {
  const g = parseGranularity(sp);
  if (!g.ok) return { ok: false, status: 400, message: g.message } as const;

  const pag = parseTrendsPagination(sp);
  if (!pag.ok) return { ok: false, status: 400, message: pag.message } as const;

  const fromR = parseIso("from", sp.get("from"));
  if (!fromR.ok) return { ok: false, status: 400, message: fromR.message } as const;
  const toR = parseIso("to", sp.get("to"));
  if (!toR.ok) return { ok: false, status: 400, message: toR.message } as const;

  const clusterId = sp.get("cluster_id")?.trim() ?? null;
  if (clusterId !== null && clusterId.length > 64) {
    return { ok: false, status: 400, message: "'cluster_id' too long" } as const;
  }

  const table = g.value === "daily" ? "news_trends_cluster_daily_v" : "news_trends_cluster_hourly_v";
  const bucketCol = g.value === "daily" ? "bucket_day" : "bucket_hour";
  const selectCols =
    g.value === "daily"
      ? "bucket_day, cluster_id, bucket_article_count, article_count, cluster_avg, cluster_weighted_avg"
      : "bucket_hour, cluster_id, bucket_article_count, article_count, cluster_avg, cluster_weighted_avg";

  const supabase = createServiceClient();
  let q = supabase
    .schema("swingtrader")
    .from(table)
    .select(selectCols, { count: "exact" })
    .order(bucketCol, { ascending: true })
    .range(pag.value.offset, pag.value.offset + pag.value.limit - 1);

  if (fromR.value) q = q.gte(bucketCol, fromR.value);
  if (toR.value) q = q.lte(bucketCol, toR.value);
  if (clusterId) q = q.eq("cluster_id", clusterId);

  const { data, error, count } = await q;
  if (error) return { ok: false, status: 500, message: "Internal error" } as const;

  return {
    ok: true as const,
    body: {
      granularity: g.value,
      data: data ?? [],
      pagination: { limit: pag.value.limit, offset: pag.value.offset, total: count ?? 0 },
    },
  };
}

/** `news_trends_heads_daily_v` | `news_trends_heads_hourly_v` */
export async function listNewsTrendsHeadsOverlayFromSearchParams(sp: URLSearchParams) {
  const g = parseGranularity(sp);
  if (!g.ok) return { ok: false, status: 400, message: g.message } as const;

  const pag = parseTrendsPagination(sp);
  if (!pag.ok) return { ok: false, status: 400, message: pag.message } as const;

  const fromR = parseIso("from", sp.get("from"));
  if (!fromR.ok) return { ok: false, status: 400, message: fromR.message } as const;
  const toR = parseIso("to", sp.get("to"));
  if (!toR.ok) return { ok: false, status: 400, message: toR.message } as const;

  const cluster = sp.get("cluster")?.trim() ?? null;
  if (cluster !== null && cluster.length > 64) {
    return { ok: false, status: 400, message: "'cluster' too long" } as const;
  }

  const table = g.value === "daily" ? "news_trends_heads_daily_v" : "news_trends_heads_hourly_v";
  const bucketCol = g.value === "daily" ? "bucket_day" : "bucket_hour";
  const selectCols =
    g.value === "daily"
      ? "bucket_day, cluster, bucket_article_count, head_count, article_count, confidence_avg"
      : "bucket_hour, cluster, bucket_article_count, head_count, article_count, confidence_avg";

  const supabase = createServiceClient();
  let q = supabase
    .schema("swingtrader")
    .from(table)
    .select(selectCols, { count: "exact" })
    .order(bucketCol, { ascending: true })
    .range(pag.value.offset, pag.value.offset + pag.value.limit - 1);

  if (fromR.value) q = q.gte(bucketCol, fromR.value);
  if (toR.value) q = q.lte(bucketCol, toR.value);
  if (cluster) q = q.eq("cluster", cluster);

  const { data, error, count } = await q;
  if (error) return { ok: false, status: 500, message: "Internal error" } as const;

  return {
    ok: true as const,
    body: {
      granularity: g.value,
      data: data ?? [],
      pagination: { limit: pag.value.limit, offset: pag.value.offset, total: count ?? 0 },
    },
  };
}

/** Same pagination caps as unfiltered article list (`parseTrendsPagination`). */
export async function listNewsTrendsArticlesByTicker(
  sp: URLSearchParams,
  tickerUpper: string,
): Promise<Awaited<ReturnType<typeof listNewsTrendsArticlesFromSearchParams>>> {
  const pag = parseTrendsPagination(sp);
  if (!pag.ok) return { ok: false, status: 400, message: pag.message };

  const supabase = createServiceClient();
  const { data: tickerRows, error: tickerErr } = await supabase
    .schema("swingtrader")
    .from("news_article_tickers")
    .select("article_id")
    .eq("ticker", tickerUpper);

  if (tickerErr) return { ok: false, status: 500, message: "Internal error" };

  const articleIds = (tickerRows ?? []).map((r) => Number(r.article_id)).filter(Number.isFinite);
  if (articleIds.length === 0) {
    return {
      ok: true,
      body: { data: [], pagination: { ...pag.value, total: 0 } },
    };
  }

  const fromR = parseIso("from", sp.get("from"));
  if (!fromR.ok) return { ok: false, status: 400, message: fromR.message };
  const toR = parseIso("to", sp.get("to"));
  if (!toR.ok) return { ok: false, status: 400, message: toR.message };

  let q = supabase
    .schema("swingtrader")
    .from("news_trends_article_base_v")
    .select(
      "article_id, published_at, bucket_day, bucket_hour, impact_jsonb, confidence_mean, id, title, url, source, slug, image_url, article_created_at",
      { count: "exact" },
    )
    .in("article_id", articleIds)
    .order("published_at", { ascending: true })
    .range(pag.value.offset, pag.value.offset + pag.value.limit - 1);

  if (fromR.value) q = q.gte("published_at", fromR.value);
  if (toR.value) q = q.lte("published_at", toR.value);

  const { data, error, count } = await q;
  if (error) return { ok: false, status: 500, message: "Internal error" };

  return {
    ok: true,
    body: {
      data: data ?? [],
      pagination: { limit: pag.value.limit, offset: pag.value.offset, total: count ?? 0 },
    },
  };
}

/** Optional `ticker` query routes to article_id filter via `news_article_tickers`. */
export async function listNewsTrendsArticlesFromSearchParamsWithOptionalTicker(sp: URLSearchParams) {
  const ticker = normalizeTicker(sp.get("ticker"), 12);
  if (ticker) return listNewsTrendsArticlesByTicker(sp, ticker);
  return listNewsTrendsArticlesFromSearchParams(sp);
}
