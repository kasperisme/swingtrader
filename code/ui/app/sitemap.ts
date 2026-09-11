import type { MetadataRoute } from "next";
import { connection } from "next/server";
import { isSanityConfigured, sanityFetch } from "@/lib/sanity/client";
import {
  docPageSlugListQuery,
  blogPostSlugListQuery,
  traderSlugListQuery,
} from "@/lib/sanity/queries";
import { listMarketScreenings } from "@/app/actions/market-screenings";
import { listCoveredTickers } from "@/app/actions/quotes";
import { createServiceClient } from "@/lib/supabase/service";
import { SITE_URL } from "@/lib/site";

// Was defaulting to the apex host while every page canonicalised to `www`,
// so all ~6.5k sitemap URLs were redirects (GSC: 1,600 submitted / 0 indexed).
const baseUrl = SITE_URL;

// Cap article URLs. This was 5,000 unfiltered — the newest slugs in
// news_articles, whatever they were about — and that made 74% of everything
// offered to a crawler a wrapper around a third-party headline: law-firm
// class-action notices, an ASICS retail partnership, a construction contract in
// Fort Nelson BC. Search Console's verdict on the whole domain matched: every
// hub page sat at "Crawled - currently not indexed" and the /quote tree had
// never been fetched at all. Crawl budget is finite; it was being spent there.
//
// The set now comes from swingtrader.sitemap_article_urls, which keeps only
// articles naming a real, actively-covered ticker and drops the
// securities-litigation wire genre (10% of the corpus on its own). See
// migration 20260907140000 for why each gate is shaped the way it is.
const ARTICLE_SITEMAP_LIMIT = 1500;

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

/**
 * `<lastmod>` is only worth emitting when it is true.
 *
 * Every static page and several dynamic ones used to be stamped with the
 * request time, so each fetch told Google that /terms, /privacy and every
 * trader profile had changed since the last one. Google's documented response
 * is to stop trusting the site's lastmod altogether — which also discards the
 * accurate values on the article and topic URLs, the only signal that says
 * "this one is new, crawl it first". So: a real timestamp, or none at all.
 */
function toDate(v: string | null | undefined): Date | undefined {
  if (!v) return undefined;
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? undefined : d;
}

/** A hub changes when its newest child does. */
function newest(...sets: MetadataRoute.Sitemap[]): Date | undefined {
  let best: number | undefined;
  for (const routes of sets) {
    for (const r of routes) {
      const t = r.lastModified ? new Date(r.lastModified).getTime() : NaN;
      if (Number.isFinite(t) && (best === undefined || t > best)) best = t;
    }
  }
  return best === undefined ? undefined : new Date(best);
}

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  // Built from live DB + Sanity data, so generate at request time rather than
  // during the static prerender (which tears down the in-flight fetches).
  await connection();

  // Per-screening pages — independent of Sanity config.
  let screeningRoutes: MetadataRoute.Sitemap = [];
  try {
    const screenings = await listMarketScreenings();
    screeningRoutes = screenings.map((s) => ({
      url: `${baseUrl}/marketscreenings/${s.slug}`,
      lastModified: toDate(s.last_run_at),
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
          lastModified: toDate(latest?.article_ts as string | undefined),
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
      lastModified: toDate(r.updated_at as string | undefined),
      changeFrequency: "monthly" as const,
      priority: 0.6,
    }));
  } catch (e) {
    console.warn("[sitemap] failed to list research", e);
  }

  // One page per competing arena agent. Reads the public view, so an agent that
  // is still being tuned (is_published = false) never reaches the sitemap.
  // An agent page changes when its book is marked, so lastmod is the agent's
  // newest NAV session — the window covers ~50 sessions of the whole roster.
  let arenaRoutes: MetadataRoute.Sitemap = [];
  try {
    const supabase = createServiceClient();
    const [{ data, error }, { data: navRows }] = await Promise.all([
      supabase.schema("swingtrader").from("arena_agents_public_v").select("slug"),
      supabase
        .schema("swingtrader")
        .from("arena_nav_history_public_v")
        .select("agent_slug, as_of")
        .order("as_of", { ascending: false })
        .limit(500),
    ]);
    if (error) throw error;
    const lastMarked = new Map<string, string>();
    for (const r of navRows ?? []) {
      const slug = r.agent_slug as string;
      if (!lastMarked.has(slug)) lastMarked.set(slug, r.as_of as string);
    }
    arenaRoutes = (data ?? []).map((a) => ({
      url: `${baseUrl}/agent/${a.slug as string}`,
      lastModified: toDate(lastMarked.get(a.slug as string)),
      changeFrequency: "daily" as const,
      priority: 0.6,
    }));
  } catch (e) {
    console.warn("[sitemap] failed to list arena agents", e);
  }

  // Famous-trader reference pages, from Sanity.
  let traderRoutes: MetadataRoute.Sitemap = [];
  try {
    const rows = isSanityConfigured
      ? await sanityFetch<{ slug: string; updatedAt?: string }[]>(traderSlugListQuery)
      : [];
    traderRoutes = rows.map((r) => ({
      url: `${baseUrl}/traders/${r.slug}`,
      lastModified: toDate(r.updatedAt),
      changeFrequency: "monthly" as const,
      priority: 0.6,
    }));
  } catch (e) {
    console.warn("[sitemap] failed to list traders", e);
  }

  // Per-article pages, freshest first — read from the pre-gated rollup rather
  // than scanning news_articles.
  //
  // Computing the gates live measured 622ms-1.6s server-side and up to 8.9s on
  // a cold cache, against the REST role's 8s statement timeout. The sitemap is
  // the one endpoint guaranteed to be cold (Google's last two fetches were 13
  // days apart) and the failure here is SILENT — the catch below warns and
  // ships zero article URLs, which has already happened once on this file for
  // the /quote block. Reading the rollup is an index-only scan: 0.6ms.
  let articleRoutes: MetadataRoute.Sitemap = [];
  try {
    const supabase = createServiceClient();
    const data = await fetchAllRows<{ slug: string; published_at: string }>(
      (from, to) =>
        supabase
          .schema("swingtrader")
          .from("sitemap_article_urls")
          .select("slug, published_at")
          .order("published_at", { ascending: false })
          .range(from, to),
      ARTICLE_SITEMAP_LIMIT,
    );
    articleRoutes = data
      .filter((r) => typeof r.slug === "string" && r.slug.length > 0)
      .map((r) => ({
        url: `${baseUrl}/articles/${r.slug}`,
        lastModified: toDate(r.published_at),
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
  const quoteIndexRoutes: MetadataRoute.Sitemap = [];
  try {
    const seen = new Map<string, Date | undefined>();
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
        seen.set(ticker, toDate(item.lastDay));
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
    const quotesUpdated = newest(quoteRoutes);
    for (let page = 2; page <= lastPage; page++) {
      quoteIndexRoutes.push({
        url: `${baseUrl}/quote?page=${page}`,
        lastModified: quotesUpdated,
        changeFrequency: "daily" as const,
        priority: 0.5,
      });
    }
  } catch (e) {
    console.warn("[sitemap] failed to list quote tickers", e);
  }

  // Docs + blog, from Sanity. This used to early-return the whole sitemap when
  // Sanity was unconfigured, which also dropped the topic, research, arena and
  // trader URLs — none of which depend on Sanity.
  let docRoutes: MetadataRoute.Sitemap = [];
  let blogRoutes: MetadataRoute.Sitemap = [];
  if (isSanityConfigured) {
    const [docSlugs, blogSlugs] = await Promise.all([
      sanityFetch<{ slug: string; updatedAt?: string }[]>(docPageSlugListQuery),
      sanityFetch<{ slug: string; updatedAt?: string }[]>(blogPostSlugListQuery),
    ]);
    docRoutes = docSlugs.map(({ slug, updatedAt }) => ({
      url: `${baseUrl}/docs/${slug}`,
      lastModified: toDate(updatedAt),
      changeFrequency: "monthly",
      priority: 0.7,
    }));
    blogRoutes = blogSlugs.map(({ slug, updatedAt }) => ({
      url: `${baseUrl}/blog/${slug}`,
      lastModified: toDate(updatedAt),
      changeFrequency: "monthly",
      priority: 0.6,
    }));
  }

  // Hubs take their lastmod from their newest child. Pages with no content
  // clock of their own (about, pricing, legal, the briefing sign-up) carry
  // none rather than a fabricated one.
  const gettingStarted = `${baseUrl}/docs/getting-started`;
  const staticRoutes: MetadataRoute.Sitemap = [
    { url: baseUrl, lastModified: newest(screeningRoutes), changeFrequency: "weekly", priority: 1 },
    { url: `${baseUrl}/marketscreenings`, lastModified: newest(screeningRoutes), changeFrequency: "daily", priority: 0.9 },
    { url: `${baseUrl}/articles`, lastModified: newest(articleRoutes), changeFrequency: "hourly", priority: 0.9 },
    { url: `${baseUrl}/topics`, lastModified: newest(topicRoutes), changeFrequency: "daily", priority: 0.9 },
    { url: `${baseUrl}/quote`, lastModified: newest(quoteRoutes), changeFrequency: "daily", priority: 0.8 },
    { url: `${baseUrl}/blog`, lastModified: newest(blogRoutes), changeFrequency: "weekly", priority: 0.8 },
    // The free lead magnet, and the highest-intent page on the site — it was
    // indexable, canonicalised and taking real traffic, but had never been
    // listed here, so the sitemap offered no path to it at all.
    { url: `${baseUrl}/briefings`, changeFrequency: "weekly", priority: 0.8 },
    { url: `${baseUrl}/about`, changeFrequency: "monthly", priority: 0.7 },
    { url: `${baseUrl}/research`, lastModified: newest(researchRoutes), changeFrequency: "weekly", priority: 0.7 },
    { url: `${baseUrl}/arena`, lastModified: newest(arenaRoutes), changeFrequency: "daily", priority: 0.8 },
    { url: `${baseUrl}/traders`, lastModified: newest(traderRoutes), changeFrequency: "weekly", priority: 0.7 },
    // /docs redirects to the first page — list the destination, not the hop.
    // It is also a Sanity docPage, so drop that duplicate from docRoutes.
    {
      url: gettingStarted,
      lastModified: newest(docRoutes.filter((r) => r.url === gettingStarted)),
      changeFrequency: "weekly",
      priority: 0.8,
    },
    { url: `${baseUrl}/pricing`, changeFrequency: "monthly", priority: 0.7 },
    { url: `${baseUrl}/terms`, changeFrequency: "yearly", priority: 0.3 },
    { url: `${baseUrl}/privacy`, changeFrequency: "yearly", priority: 0.3 },
  ];
  docRoutes = docRoutes.filter((r) => r.url !== gettingStarted);

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
    ...arenaRoutes,
    ...traderRoutes,
  ];
}
