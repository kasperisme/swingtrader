import type { MetadataRoute } from "next";
import { connection } from "next/server";
import { isSanityConfigured, sanityFetch } from "@/lib/sanity/client";
import { docPageSlugListQuery, blogPostSlugListQuery } from "@/lib/sanity/queries";
import { listMarketScreenings } from "@/app/actions/market-screenings";
import { listCoveredTickers } from "@/app/actions/quotes";
import { createServiceClient } from "@/lib/supabase/service";
import { SITE_URL } from "@/lib/site";

// Was defaulting to the apex host while every page canonicalised to `www`,
// so all ~6.5k sitemap URLs were redirects (GSC: 1,600 submitted / 0 indexed).
const baseUrl = SITE_URL;

// Cap article URLs — protocol limit is 50k/file and the freshest articles
// matter most for indexing. Older pieces remain reachable via internal links.
const ARTICLE_SITEMAP_LIMIT = 5000;

// Cap /quote/[symbol] URLs to the most-covered tickers. Sourced from recent
// sentiment heads so only symbols with real news-impact data get indexed.
const QUOTE_SITEMAP_LIMIT = 1500;

// Mirror of the /quote hub's own paging so the directory pages we list here
// resolve to real pages (past the last page it 404s, deliberately).
const QUOTE_HUB_PAGE_SIZE = 50;
const QUOTE_HUB_WINDOW_DAYS = 30;
const QUOTE_HUB_PAGE_CAP = 100;

/**
 * PostgREST caps a single response at 1000 rows regardless of `.limit()`, so
 * `limit(5000)` silently returned 1000 and the sitemap shipped a fraction of
 * what it claimed: exactly 1000 articles, and ~450 distinct tickers instead of
 * QUOTE_SITEMAP_LIMIT. Page through with `.range()` until the cap is reached
 * or the source runs dry.
 */
const PAGE_ROWS = 1000;

async function fetchAllRows<T>(
  build: (from: number, to: number) => PromiseLike<{ data: T[] | null; error: unknown }>,
  cap: number,
): Promise<T[]> {
  const out: T[] = [];
  for (let from = 0; from < cap; from += PAGE_ROWS) {
    const to = Math.min(from + PAGE_ROWS, cap) - 1;
    const { data, error } = await build(from, to);
    if (error) throw error;
    const rows = data ?? [];
    out.push(...rows);
    if (rows.length < to - from + 1) break; // source exhausted
  }
  return out;
}

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  // Built from live DB + Sanity data, so generate at request time rather than
  // during the static prerender (which tears down the in-flight fetches).
  await connection();

  const now = new Date();
  const staticRoutes: MetadataRoute.Sitemap = [
    { url: baseUrl, lastModified: now, changeFrequency: "weekly", priority: 1 },
    { url: `${baseUrl}/marketscreenings`, lastModified: now, changeFrequency: "daily", priority: 0.9 },
    { url: `${baseUrl}/articles`, lastModified: now, changeFrequency: "hourly", priority: 0.9 },
    { url: `${baseUrl}/topics`, lastModified: now, changeFrequency: "daily", priority: 0.9 },
    { url: `${baseUrl}/quote`, lastModified: now, changeFrequency: "daily", priority: 0.8 },
    { url: `${baseUrl}/blog`, lastModified: now, changeFrequency: "weekly", priority: 0.8 },
    { url: `${baseUrl}/about`, lastModified: now, changeFrequency: "monthly", priority: 0.7 },
    { url: `${baseUrl}/research`, lastModified: now, changeFrequency: "weekly", priority: 0.7 },
    // /docs redirects to the first page — list the destination, not the hop.
    { url: `${baseUrl}/docs/getting-started`, lastModified: now, changeFrequency: "weekly", priority: 0.8 },
    { url: `${baseUrl}/pricing`, lastModified: now, changeFrequency: "monthly", priority: 0.7 },
    { url: `${baseUrl}/changelog`, lastModified: now, changeFrequency: "weekly", priority: 0.5 },
    { url: `${baseUrl}/terms`, lastModified: now, changeFrequency: "yearly", priority: 0.3 },
    { url: `${baseUrl}/privacy`, lastModified: now, changeFrequency: "yearly", priority: 0.3 },
  ];

  // Per-screening pages — independent of Sanity config.
  let screeningRoutes: MetadataRoute.Sitemap = [];
  try {
    const screenings = await listMarketScreenings();
    screeningRoutes = screenings.map((s) => ({
      url: `${baseUrl}/marketscreenings/${s.slug}`,
      lastModified: s.last_run_at ? new Date(s.last_run_at) : now,
      changeFrequency: "daily",
      priority: 0.7,
    }));
  } catch (e) {
    console.warn("[sitemap] failed to list market screenings", e);
  }

  // Topic hubs — the highest-priority indexable pages after the home page. They
  // consolidate many thin article URLs into one deep, continuously-updated page,
  // so `lastModified` tracks the newest story IN the topic (not deploy time) —
  // that is the signal telling crawlers a tracker is worth re-visiting.
  let topicRoutes: MetadataRoute.Sitemap = [];
  try {
    const supabase = createServiceClient();
    const { data: topics, error } = await supabase
      .schema("swingtrader")
      .from("topics")
      .select("slug")
      .eq("is_published", true);
    if (error) throw error;
    topicRoutes = await Promise.all(
      (topics ?? []).map(async (t: { slug: string }) => {
        const { data: latest } = await supabase
          .schema("swingtrader")
          .from("topic_claim_stats")
          .select("article_ts")
          .eq("topic_slug", t.slug)
          .order("article_ts", { ascending: false })
          .limit(1)
          .maybeSingle();
        return {
          url: `${baseUrl}/topics/${t.slug}`,
          lastModified: latest?.article_ts ? new Date(latest.article_ts as string) : now,
          changeFrequency: "daily" as const,
          priority: 0.9,
        };
      }),
    );
  } catch (e) {
    console.warn("[sitemap] failed to list topics", e);
  }

  // Published research write-ups. Reads the public view, so drafts — which are
  // most of them, deliberately — never reach the sitemap.
  let researchRoutes: MetadataRoute.Sitemap = [];
  try {
    const supabase = createServiceClient();
    const { data, error } = await supabase
      .schema("swingtrader")
      .from("research_public_v")
      .select("slug, updated_at")
      .order("updated_at", { ascending: false });
    if (error) throw error;
    researchRoutes = (data ?? []).map((r) => ({
      url: `${baseUrl}/research/${r.slug as string}`,
      lastModified: r.updated_at ? new Date(r.updated_at as string) : now,
      changeFrequency: "monthly" as const,
      priority: 0.6,
    }));
  } catch (e) {
    console.warn("[sitemap] failed to list research", e);
  }

  // Per-article pages — sourced from the news_articles table, freshest first.
  let articleRoutes: MetadataRoute.Sitemap = [];
  try {
    const supabase = createServiceClient();
    const data = await fetchAllRows<{
      slug: string | null;
      published_at: string | null;
      created_at: string | null;
    }>(
      (from, to) =>
        supabase
          .schema("swingtrader")
          .from("news_articles")
          .select("slug, published_at, created_at")
          .not("slug", "is", null)
          .order("published_at", { ascending: false, nullsFirst: false })
          .order("created_at", { ascending: false })
          .range(from, to),
      ARTICLE_SITEMAP_LIMIT,
    );
    articleRoutes = data
      .filter((r) => typeof r.slug === "string" && r.slug.length > 0)
      .map((r) => ({
        url: `${baseUrl}/articles/${r.slug}`,
        lastModified: r.published_at
          ? new Date(r.published_at)
          : r.created_at
            ? new Date(r.created_at)
            : now,
        changeFrequency: "monthly" as const,
        priority: 0.6,
      }));
  } catch (e) {
    console.warn("[sitemap] failed to list articles", e);
  }

  // Per-ticker quote pages + the directory's own pages, from the same RPC the
  // /quote hub itself pages through.
  //
  // This used to scan `ticker_sentiment_heads` (353k rows) with `.range()`,
  // which worked locally and silently failed in production: the REST role has
  // an 8s statement timeout, and ~30 deep-offset requests over that table blew
  // straight through it. The catch swallowed it and the deployed sitemap
  // shipped with ZERO /quote/<symbol> URLs — the exact pages this was for.
  // `get_top_covered_tickers` reads the materialized `ticker_coverage_daily`
  // rollup that exists for this query, and caps at 200 rows per call, so the
  // full list is 8 cheap calls instead of 30 expensive ones.
  const QUOTE_RPC_PAGE = 200;
  let quoteRoutes: MetadataRoute.Sitemap = [];
  let quoteIndexRoutes: MetadataRoute.Sitemap = [];
  try {
    const seen = new Map<string, Date>();
    let total = 0;
    for (let offset = 0; offset < QUOTE_SITEMAP_LIMIT; offset += QUOTE_RPC_PAGE) {
      const page = await listCoveredTickers({
        days: QUOTE_HUB_WINDOW_DAYS,
        limit: QUOTE_RPC_PAGE,
        offset,
      });
      total = page.total || total;
      if (page.items.length === 0) break;
      for (const item of page.items) {
        const ticker = item.ticker.trim().toUpperCase();
        if (!ticker || !/^[A-Z][A-Z0-9.\-]{0,11}$/.test(ticker) || seen.has(ticker)) continue;
        seen.set(ticker, item.lastDay ? new Date(item.lastDay) : now);
        if (seen.size >= QUOTE_SITEMAP_LIMIT) break;
      }
      if (seen.size >= QUOTE_SITEMAP_LIMIT) break;
    }

    quoteRoutes = [...seen.entries()].map(([ticker, lastModified]) => ({
      url: `${baseUrl}/quote/${ticker}`,
      lastModified,
      changeFrequency: "daily" as const,
      priority: 0.6,
    }));

    // The hub runs to ~74 pages and its pager renders only a 5-page window, so
    // reaching the tail means walking the whole chain — which never happens on
    // a small crawl budget. Listing the pages gives every ticker beyond
    // QUOTE_SITEMAP_LIMIT a one-hop path.
    const lastPage = Math.min(
      QUOTE_HUB_PAGE_CAP,
      Math.max(1, Math.ceil(total / QUOTE_HUB_PAGE_SIZE)),
    );
    for (let page = 2; page <= lastPage; page++) {
      quoteIndexRoutes.push({
        url: `${baseUrl}/quote?page=${page}`,
        lastModified: now,
        changeFrequency: "daily" as const,
        priority: 0.5,
      });
    }
  } catch (e) {
    console.warn("[sitemap] failed to list quote tickers", e);
  }


  if (!isSanityConfigured) {
    return [
    ...staticRoutes,
    ...screeningRoutes,
    ...articleRoutes,
    ...quoteRoutes,
    ...quoteIndexRoutes,
  ];
  }

  const [docSlugs, blogSlugs] = await Promise.all([
    sanityFetch<{ slug: string }[]>(docPageSlugListQuery),
    sanityFetch<{ slug: string }[]>(blogPostSlugListQuery),
  ]);

  const docRoutes: MetadataRoute.Sitemap = docSlugs.map(({ slug }) => ({
    url: `${baseUrl}/docs/${slug}`,
    lastModified: now,
    changeFrequency: "monthly",
    priority: 0.7,
  }));

  const blogRoutes: MetadataRoute.Sitemap = blogSlugs.map(({ slug }) => ({
    url: `${baseUrl}/blog/${slug}`,
    lastModified: now,
    changeFrequency: "monthly",
    priority: 0.6,
  }));

  return [
    ...staticRoutes,
    ...topicRoutes,
    ...screeningRoutes,
    ...articleRoutes,
    ...quoteRoutes,
    ...quoteIndexRoutes,
    ...docRoutes,
    ...blogRoutes,
    ...researchRoutes,
  ];
}
