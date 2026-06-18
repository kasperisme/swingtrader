import type { MetadataRoute } from "next";
import { connection } from "next/server";
import { isSanityConfigured, sanityFetch } from "@/lib/sanity/client";
import { docPageSlugListQuery, blogPostSlugListQuery } from "@/lib/sanity/queries";
import { listMarketScreenings } from "@/app/actions/market-screenings";
import { createServiceClient } from "@/lib/supabase/service";

const baseUrl = process.env.NEXT_PUBLIC_SITE_URL ?? "https://newsimpactscreener.com";

// Cap article URLs — protocol limit is 50k/file and the freshest articles
// matter most for indexing. Older pieces remain reachable via internal links.
const ARTICLE_SITEMAP_LIMIT = 5000;

// Cap /quote/[symbol] URLs to the most-covered tickers. Sourced from recent
// sentiment heads so only symbols with real news-impact data get indexed.
const QUOTE_SITEMAP_LIMIT = 1500;

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  // Built from live DB + Sanity data, so generate at request time rather than
  // during the static prerender (which tears down the in-flight fetches).
  await connection();

  const now = new Date();
  const staticRoutes: MetadataRoute.Sitemap = [
    { url: baseUrl, lastModified: now, changeFrequency: "weekly", priority: 1 },
    { url: `${baseUrl}/marketscreenings`, lastModified: now, changeFrequency: "daily", priority: 0.9 },
    { url: `${baseUrl}/articles`, lastModified: now, changeFrequency: "hourly", priority: 0.9 },
    { url: `${baseUrl}/blog`, lastModified: now, changeFrequency: "weekly", priority: 0.8 },
    { url: `${baseUrl}/docs`, lastModified: now, changeFrequency: "weekly", priority: 0.8 },
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

  // Per-article pages — sourced from the news_articles table, freshest first.
  let articleRoutes: MetadataRoute.Sitemap = [];
  try {
    const supabase = createServiceClient();
    const { data, error } = await supabase
      .schema("swingtrader")
      .from("news_articles")
      .select("slug, published_at, created_at")
      .not("slug", "is", null)
      .order("published_at", { ascending: false, nullsFirst: false })
      .order("created_at", { ascending: false })
      .limit(ARTICLE_SITEMAP_LIMIT);
    if (error) throw error;
    articleRoutes = (data ?? [])
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

  // Per-ticker quote pages — distinct symbols with recent scored news, freshest
  // first. Deduped in JS since the heads table has many rows per ticker.
  let quoteRoutes: MetadataRoute.Sitemap = [];
  try {
    const supabase = createServiceClient();
    const { data, error } = await supabase
      .schema("swingtrader")
      .from("ticker_sentiment_heads")
      .select("ticker, article_ts")
      .not("ticker", "is", null)
      .order("article_ts", { ascending: false, nullsFirst: false })
      .limit(QUOTE_SITEMAP_LIMIT * 20);
    if (error) throw error;
    const seen = new Map<string, Date>();
    for (const r of data ?? []) {
      const ticker = typeof r.ticker === "string" ? r.ticker.trim().toUpperCase() : "";
      if (!ticker || !/^[A-Z][A-Z0-9.\-]{0,11}$/.test(ticker) || seen.has(ticker)) continue;
      seen.set(ticker, r.article_ts ? new Date(r.article_ts) : now);
      if (seen.size >= QUOTE_SITEMAP_LIMIT) break;
    }
    quoteRoutes = [...seen.entries()].map(([ticker, lastModified]) => ({
      url: `${baseUrl}/quote/${ticker}`,
      lastModified,
      changeFrequency: "daily" as const,
      priority: 0.6,
    }));
  } catch (e) {
    console.warn("[sitemap] failed to list quote tickers", e);
  }

  if (!isSanityConfigured) {
    return [...staticRoutes, ...screeningRoutes, ...articleRoutes, ...quoteRoutes];
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
    ...screeningRoutes,
    ...articleRoutes,
    ...docRoutes,
    ...blogRoutes,
  ];
}
