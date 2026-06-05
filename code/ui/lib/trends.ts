import "server-only";
import { unstable_cache } from "next/cache";
import { createServiceClient } from "@/lib/supabase/service";
import type {
  SortMode,
  TrendItem,
  TrendKind,
  TrendingBoard,
} from "@/lib/trends-types";

export type {
  SortMode,
  TrendItem,
  TrendKind,
  TrendingBoard,
} from "@/lib/trends-types";

/**
 * Trending intelligence for ticker mentions + theme tags.
 *
 * Reads the pre-aggregated daily views
 *   - swingtrader.news_trends_ticker_daily_v
 *   - swingtrader.news_trends_tag_daily_v
 * (migration 20260605120000), buckets each into a current vs prior window, then
 * ranks the result three ways — most mentions, most growth, and brand-new — so
 * the scoreboard can switch filters client-side from a single data pull.
 *
 * Wrapped in unstable_cache so every /articles and /articles/[slug] render
 * shares one computation (revalidated every 10 min).
 */

const DEFAULT_WINDOW_DAYS = 7;
const DEFAULT_LIMIT = 6;
const CACHE_REVALIDATE_SECONDS = 600;

// Growth/new filters need a volume floor so a 1→3 blip can't top the board.
const MIN_CURRENT_FOR_GROWTH = 5;
const MIN_CURRENT_FOR_NEW = 3;

// PostgREST caps each response at its server `max-rows` (1000 here), so a
// single .select() over the daily views silently returns only the first slice —
// alphabetically-first tickers, dropping the actual leaders. Page through with a
// stable ORDER BY to rank over the full window.
const PAGE_SIZE = 1000;
const MAX_PAGES = 60;

async function fetchAllRows<T>(
  build: (from: number, to: number) => PromiseLike<{ data: T[] | null; error: unknown }>,
): Promise<T[] | null> {
  const out: T[] = [];
  for (let page = 0; page < MAX_PAGES; page++) {
    const from = page * PAGE_SIZE;
    const { data, error } = await build(from, from + PAGE_SIZE - 1);
    if (error) {
      console.error("[trends] view query failed:", error);
      return out.length ? out : null;
    }
    if (!data || data.length === 0) break;
    out.push(...data);
    if (data.length < PAGE_SIZE) break;
  }
  return out;
}

function dayKey(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function startOfUtcDay(d: Date): Date {
  return new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()));
}

/** Ordered list of `YYYY-MM-DD` day keys for the last `span` days (oldest first). */
function spanDays(span: number): string[] {
  const today = startOfUtcDay(new Date());
  const out: string[] = [];
  for (let i = span - 1; i >= 0; i--) {
    const d = new Date(today);
    d.setUTCDate(d.getUTCDate() - i);
    out.push(dayKey(d));
  }
  return out;
}

function formatTagLabel(tag: string): string {
  if (/^[A-Z]{1,6}$/.test(tag)) return tag;
  return tag.replace(/_/g, " ");
}

type DayCounts = Map<string, number>;
type DaySentiment = Map<string, { sum: number; weight: number }>;

type TrendIndex = {
  kind: TrendKind;
  days: string[];
  windowDays: number;
  byKey: Map<string, DayCounts>;
  sentimentByKey: Map<string, DaySentiment> | null;
};

// ── Index builders (fetch + bucket, no ranking) ──────────────────────────────

async function buildTickerIndex(windowDays: number): Promise<TrendIndex | null> {
  const span = windowDays * 2;
  const since = spanDays(span)[0];
  const supabase = createServiceClient();
  const data = await fetchAllRows<{
    bucket_day: string;
    ticker: string;
    mention_count: number;
    scored_count: number | null;
    avg_sentiment: number | null;
    weighted_sentiment: number | null;
  }>((from, to) =>
    supabase
      .schema("swingtrader")
      .from("news_trends_ticker_daily_v")
      .select("bucket_day, ticker, mention_count, scored_count, avg_sentiment, weighted_sentiment")
      .gte("bucket_day", since)
      .order("bucket_day", { ascending: true })
      .order("ticker", { ascending: true })
      .range(from, to),
  );
  if (!data) return null;

  const byKey = new Map<string, DayCounts>();
  const sentimentByKey = new Map<string, DaySentiment>();
  for (const row of data) {
    const ticker = String(row.ticker || "").toUpperCase();
    if (!ticker) continue;
    const day = String(row.bucket_day).slice(0, 10);

    let counts = byKey.get(ticker);
    if (!counts) byKey.set(ticker, (counts = new Map()));
    counts.set(day, (counts.get(day) ?? 0) + Number(row.mention_count || 0));

    const score = row.weighted_sentiment ?? row.avg_sentiment;
    const scored = Number(row.scored_count || 0);
    if (score != null && scored > 0) {
      let sent = sentimentByKey.get(ticker);
      if (!sent) sentimentByKey.set(ticker, (sent = new Map()));
      sent.set(day, { sum: Number(score) * scored, weight: scored });
    }
  }

  return { kind: "ticker", days: spanDays(span), windowDays, byKey, sentimentByKey };
}

async function buildTagIndex(windowDays: number): Promise<TrendIndex | null> {
  const span = windowDays * 2;
  const since = spanDays(span)[0];
  const supabase = createServiceClient();
  const data = await fetchAllRows<{
    bucket_day: string;
    tag: string;
    article_count: number;
  }>((from, to) =>
    supabase
      .schema("swingtrader")
      .from("news_trends_tag_daily_v")
      .select("bucket_day, tag, article_count")
      .gte("bucket_day", since)
      .order("bucket_day", { ascending: true })
      .order("tag", { ascending: true })
      .range(from, to),
  );
  if (!data) return null;

  const byKey = new Map<string, DayCounts>();
  for (const row of data) {
    const tag = String(row.tag || "").toLowerCase();
    // Drop all-numeric tokens: these are case-less foreign tickers (e.g. Taiwan
    // "2357", Shenzhen "000002") that slip past the view's lowercase theme
    // filter — they're not themes.
    if (!tag || /^\d+$/.test(tag)) continue;
    const day = String(row.bucket_day).slice(0, 10);
    let counts = byKey.get(tag);
    if (!counts) byKey.set(tag, (counts = new Map()));
    counts.set(day, (counts.get(day) ?? 0) + Number(row.article_count || 0));
  }

  return { kind: "tag", days: spanDays(span), windowDays, byKey, sentimentByKey: null };
}

// ── Fold + rank ──────────────────────────────────────────────────────────────

/** Fold an index into per-key TrendItems (current/previous/spark/sentiment). */
function foldItems(index: TrendIndex): TrendItem[] {
  const { days, windowDays, kind, byKey, sentimentByKey } = index;
  const prevDays = new Set(days.slice(0, windowDays));
  const curDays = new Set(days.slice(windowDays));

  const items: TrendItem[] = [];
  for (const [key, counts] of byKey) {
    let current = 0;
    let previous = 0;
    const spark: number[] = days.map((d) => {
      const c = counts.get(d) ?? 0;
      if (curDays.has(d)) current += c;
      else if (prevDays.has(d)) previous += c;
      return c;
    });
    if (current === 0) continue;

    let avgSentiment: number | null = null;
    const sent = sentimentByKey?.get(key);
    if (sent) {
      let sum = 0;
      let weight = 0;
      for (const d of curDays) {
        const s = sent.get(d);
        if (s) {
          sum += s.sum;
          weight += s.weight;
        }
      }
      if (weight > 0) avgSentiment = sum / weight;
    }

    items.push({
      key,
      label: kind === "tag" ? formatTagLabel(key) : key,
      kind,
      current,
      previous,
      deltaPct: previous > 0 ? (current - previous) / previous : null,
      isNew: previous === 0,
      avgSentiment,
      spark,
    });
  }
  return items;
}

/**
 * Rank folded items for one filter mode.
 *  - mentions: established names (had prior activity) by raw current volume
 *  - growth:   established names by % change, with a volume floor
 *  - new:      items absent in the prior window, by current volume
 * "New" is its own mode and excluded from mentions/growth.
 */
function selectByMode(items: TrendItem[], mode: SortMode, limit: number): TrendItem[] {
  if (mode === "new") {
    const fresh = items.filter((it) => it.isNew && it.current >= MIN_CURRENT_FOR_NEW);
    const pool = fresh.length >= limit ? fresh : items.filter((it) => it.isNew);
    pool.sort((a, b) => b.current - a.current);
    return pool.slice(0, limit);
  }

  const established = items.filter((it) => !it.isNew);

  if (mode === "mentions") {
    established.sort((a, b) => b.current - a.current || (b.deltaPct ?? 0) - (a.deltaPct ?? 0));
    return established.slice(0, limit);
  }

  // growth
  const eligible = established.filter((it) => it.current >= MIN_CURRENT_FOR_GROWTH);
  const pool = eligible.length >= limit ? eligible : established;
  pool.sort((a, b) => (b.deltaPct ?? 0) - (a.deltaPct ?? 0) || b.current - a.current);
  return pool.slice(0, limit);
}

const MODES: SortMode[] = ["mentions", "growth", "new"];

function rankAllModes(index: TrendIndex | null, limit: number): TrendItem[] | Record<SortMode, TrendItem[]> {
  const empty = { mentions: [], growth: [], new: [] } as Record<SortMode, TrendItem[]>;
  if (!index) return empty;
  const items = foldItems(index);
  const out = {} as Record<SortMode, TrendItem[]>;
  for (const mode of MODES) out[mode] = selectByMode(items, mode, limit);
  return out;
}

// ── Public API ───────────────────────────────────────────────────────────────

const cachedBoard = unstable_cache(
  async (windowDays: number, limit: number): Promise<TrendingBoard> => {
    const [tickerIndex, tagIndex] = await Promise.all([
      buildTickerIndex(windowDays),
      buildTagIndex(windowDays),
    ]);
    return {
      tickers: rankAllModes(tickerIndex, limit) as Record<SortMode, TrendItem[]>,
      tags: rankAllModes(tagIndex, limit) as Record<SortMode, TrendItem[]>,
    };
  },
  ["trending-board-v1"],
  { revalidate: CACHE_REVALIDATE_SECONDS, tags: ["trends"] },
);

export async function getTrendingBoard(
  opts: { windowDays?: number; limit?: number } = {},
): Promise<TrendingBoard> {
  return cachedBoard(opts.windowDays ?? DEFAULT_WINDOW_DAYS, opts.limit ?? DEFAULT_LIMIT);
}

export type TrendingLookupEntry = {
  kind: TrendKind;
  deltaPct: number | null;
  isNew: boolean;
  current: number;
};

/**
 * Keyed lookup of what's trending right now (union of all filter modes), for
 * highlighting an article's own tags on /articles/[slug]. Keys are the raw tag
 * values (UPPER ticker / lower slug) so they match `news_articles.search_tags`.
 */
export async function getTrendingLookup(
  opts: { windowDays?: number; topN?: number } = {},
): Promise<Record<string, TrendingLookupEntry>> {
  const board = await getTrendingBoard({ windowDays: opts.windowDays, limit: opts.topN ?? 40 });
  const out: Record<string, TrendingLookupEntry> = {};
  const lists = [
    ...Object.values(board.tickers),
    ...Object.values(board.tags),
  ];
  for (const list of lists) {
    for (const it of list) {
      if (out[it.key]) continue;
      out[it.key] = {
        kind: it.kind,
        deltaPct: it.deltaPct,
        isNew: it.isNew,
        current: it.current,
      };
    }
  }
  return out;
}
