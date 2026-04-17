import type { SupabaseClient } from "@supabase/supabase-js";
import type { ArticleImpact } from "@/app/protected/news-trends/news-trends-types";
import type { ClusterTrendRow, DimensionTrendRow } from "@/app/protected/news-trends/news-trends-series";

/** Max UI range is 1y; add buffer for timezone / custom brush. */
export const NEWS_TRENDS_LOOKBACK_DAYS = 400;
/** PostgREST `max-rows` cap — requesting more still returns at most this many. */
const PAGE_SIZE = 1000;
/**
 * Half-open UTC windows [gte, lt) so each query touches less of the nested views.
 * Smaller segments avoid statement timeouts on heavy aggregate views.
 */
const SEGMENT_DAYS_DAILY = 55;
const SEGMENT_DAYS_HOURLY = 28;
const SEGMENT_DAYS_ARTICLES = 45;

function utcDayBoundaryPlusDays(fromUtcMidnight: Date, addDays: number): Date {
  const d = new Date(fromUtcMidnight);
  d.setUTCDate(d.getUTCDate() + addDays);
  return d;
}

function utcTomorrowMidnight(): Date {
  const d = new Date();
  d.setUTCHours(0, 0, 0, 0);
  d.setUTCDate(d.getUTCDate() + 1);
  return d;
}

/** Half-open [gte, lt) segments from oldest → newest (merge stays sorted). */
export function buildUtcHalfOpenSegments(
  lookbackDays: number,
  segmentDays: number,
  keyFormat: "day" | "timestamp",
): { gte: string; lt: string }[] {
  const endExclusive = utcTomorrowMidnight();
  const globalStart = utcDayBoundaryPlusDays(endExclusive, -lookbackDays);
  const segments: { gte: string; lt: string }[] = [];
  let segStart = globalStart;

  while (segStart < endExclusive) {
    const segEnd = utcDayBoundaryPlusDays(segStart, segmentDays);
    const cappedEnd = segEnd > endExclusive ? endExclusive : segEnd;
    const gte =
      keyFormat === "day"
        ? segStart.toISOString().slice(0, 10)
        : segStart.toISOString();
    const lt =
      keyFormat === "day"
        ? cappedEnd.toISOString().slice(0, 10)
        : cappedEnd.toISOString();
    segments.push({ gte, lt });
    segStart = cappedEnd;
  }
  return segments;
}

function asImpactMap(raw: unknown): Record<string, number> {
  if (!raw) return {};
  if (typeof raw === "object" && !Array.isArray(raw)) {
    const out: Record<string, number> = {};
    for (const [k, v] of Object.entries(raw as Record<string, unknown>)) {
      const n = Number(v);
      if (Number.isFinite(n)) out[k] = n;
    }
    return out;
  }
  if (typeof raw === "string") {
    try {
      return asImpactMap(JSON.parse(raw));
    } catch {
      return {};
    }
  }
  return {};
}

/** One bounded slice, paginated sequentially (avoids concurrent view scans + timeouts). */
async function fetchPagedInBounds<Row>(
  supabase: SupabaseClient,
  table: string,
  select: string,
  orderCol: string,
  bounds: { gte: string; lt: string },
): Promise<Row[]> {
  let from = 0;
  const out: Row[] = [];

  while (true) {
    const to = from + PAGE_SIZE - 1;
    const { data, error } = await supabase
      .schema("swingtrader")
      .from(table)
      .select(select)
      .gte(orderCol, bounds.gte)
      .lt(orderCol, bounds.lt)
      .order(orderCol, { ascending: true })
      .range(from, to);

    if (error) {
      console.error(`Failed to fetch ${table}:`, error);
      return [];
    }
    const rows = (data ?? []) as Row[];
    if (rows.length === 0) break;
    out.push(...rows);
    if (rows.length < PAGE_SIZE) break;
    from += PAGE_SIZE;
  }
  return out;
}

async function fetchSegmentedTrendTable<Row>(
  supabase: SupabaseClient,
  table: string,
  select: string,
  orderCol: string,
  keyFormat: "day" | "timestamp",
  segmentDays: number,
): Promise<Row[]> {
  const segments = buildUtcHalfOpenSegments(
    NEWS_TRENDS_LOOKBACK_DAYS,
    segmentDays,
    keyFormat,
  );
  const out: Row[] = [];
  for (const bounds of segments) {
    const part = await fetchPagedInBounds<Row>(
      supabase,
      table,
      select,
      orderCol,
      bounds,
    );
    out.push(...part);
  }
  return out;
}

export async function loadClusterDailyTrends(
  supabase: SupabaseClient,
): Promise<ClusterTrendRow[]> {
  return fetchSegmentedTrendTable<ClusterTrendRow>(
    supabase,
    "news_trends_cluster_daily_v",
    "bucket_day, cluster_id, cluster_weighted_avg, cluster_avg, article_count, bucket_article_count",
    "bucket_day",
    "day",
    SEGMENT_DAYS_DAILY,
  );
}

/** Headlines only; dimension aggregates load when user opens cluster drill-down. */
export type NewsTrendsDailySupplementPayload = {
  articles: ArticleImpact[];
};

export type NewsTrendsDimensionDailyPayload = {
  dimensionDaily: DimensionTrendRow[];
};

export type NewsTrendsDimensionHourlyPayload = {
  dimensionHourly: DimensionTrendRow[];
};

/** Cluster-only hourly series (mirrors SSR: single cluster aggregate view). */
export type NewsTrendsHourlySupplementPayload = {
  clusterHourly: ClusterTrendRow[];
};

export async function loadNewsTrendsDailySupplement(
  supabase: SupabaseClient,
): Promise<NewsTrendsDailySupplementPayload> {
  const articles = await loadNewsTrendsArticles(supabase);
  return { articles };
}

export async function loadNewsTrendsDimensionDaily(
  supabase: SupabaseClient,
): Promise<NewsTrendsDimensionDailyPayload> {
  const dimensionDaily = await fetchSegmentedTrendTable<DimensionTrendRow>(
    supabase,
    "news_trends_dimension_daily_v",
    "bucket_day, dimension_key, dimension_weighted_avg, dimension_avg, article_count, bucket_article_count",
    "bucket_day",
    "day",
    SEGMENT_DAYS_DAILY,
  );
  return { dimensionDaily };
}

export async function loadNewsTrendsDimensionHourly(
  supabase: SupabaseClient,
): Promise<NewsTrendsDimensionHourlyPayload> {
  const dimensionHourly = await fetchSegmentedTrendTable<DimensionTrendRow>(
    supabase,
    "news_trends_dimension_hourly_v",
    "bucket_hour, dimension_key, dimension_weighted_avg, dimension_avg, article_count, bucket_article_count",
    "bucket_hour",
    "timestamp",
    SEGMENT_DAYS_HOURLY,
  );
  return { dimensionHourly };
}

export async function loadNewsTrendsHourlySupplement(
  supabase: SupabaseClient,
): Promise<NewsTrendsHourlySupplementPayload> {
  const clusterHourly = await fetchSegmentedTrendTable<ClusterTrendRow>(
    supabase,
    "news_trends_cluster_hourly_v",
    "bucket_hour, cluster_id, cluster_weighted_avg, cluster_avg, article_count, bucket_article_count",
    "bucket_hour",
    "timestamp",
    SEGMENT_DAYS_HOURLY,
  );
  return { clusterHourly };
}

export async function loadNewsTrendsArticles(
  supabase: SupabaseClient,
): Promise<ArticleImpact[]> {
  const segments = buildUtcHalfOpenSegments(
    NEWS_TRENDS_LOOKBACK_DAYS,
    SEGMENT_DAYS_ARTICLES,
    "timestamp",
  );
  const allRows: unknown[] = [];
  for (const { gte, lt } of segments) {
    const part = await fetchPagedInBounds<unknown>(
      supabase,
      "news_trends_article_base_v",
      "article_id, published_at, impact_jsonb, confidence_mean, id, title, url, source, slug, image_url, article_created_at",
      "published_at",
      { gte, lt },
    );
    allRows.push(...part);
  }

  return allRows.map((row: unknown) => {
    const r = row as Record<string, unknown>;
    return {
      impact_json: asImpactMap(r.impact_jsonb),
      confidence: Number.isFinite(Number(r.confidence_mean))
        ? Number(r.confidence_mean)
        : null,
      id: r.id != null ? Number(r.id) : null,
      published_at: String(r.published_at ?? ""),
      title: r.title != null ? String(r.title) : null,
      url: r.url != null ? String(r.url) : null,
      source: r.source != null ? String(r.source) : null,
      slug: r.slug != null ? String(r.slug) : null,
      image_url: r.image_url != null ? String(r.image_url) : null,
      created_at:
        r.article_created_at != null
          ? String(r.article_created_at)
          : String(r.published_at ?? ""),
    };
  });
}
