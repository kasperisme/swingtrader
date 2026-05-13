import type { MetadataRoute } from "next";
import { isSanityConfigured, sanityFetch } from "@/lib/sanity/client";
import { docPageSlugListQuery, blogPostSlugListQuery } from "@/lib/sanity/queries";
import { listPublicScreenings } from "@/app/actions/public-screenings";

const baseUrl = process.env.NEXT_PUBLIC_SITE_URL ?? "https://newsimpactscreener.com";

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const staticRoutes: MetadataRoute.Sitemap = [
    { url: baseUrl, lastModified: new Date(), changeFrequency: "weekly", priority: 1 },
    { url: `${baseUrl}/screenings`, lastModified: new Date(), changeFrequency: "daily", priority: 0.9 },
    { url: `${baseUrl}/blog`, lastModified: new Date(), changeFrequency: "weekly", priority: 0.8 },
    { url: `${baseUrl}/docs`, lastModified: new Date(), changeFrequency: "weekly", priority: 0.8 },
  ];

  // Per-screening pages — independent of Sanity config.
  let screeningRoutes: MetadataRoute.Sitemap = [];
  try {
    const screenings = await listPublicScreenings();
    screeningRoutes = screenings.map((s) => ({
      url: `${baseUrl}/screenings/${s.slug}`,
      lastModified: s.last_run_at ? new Date(s.last_run_at) : new Date(),
      changeFrequency: "daily",
      priority: 0.7,
    }));
  } catch (e) {
    console.warn("[sitemap] failed to list public screenings", e);
  }

  if (!isSanityConfigured) return [...staticRoutes, ...screeningRoutes];

  const [docSlugs, blogSlugs] = await Promise.all([
    sanityFetch<{ slug: string }[]>(docPageSlugListQuery),
    sanityFetch<{ slug: string }[]>(blogPostSlugListQuery),
  ]);

  const docRoutes: MetadataRoute.Sitemap = docSlugs.map(({ slug }) => ({
    url: `${baseUrl}/docs/${slug}`,
    lastModified: new Date(),
    changeFrequency: "monthly",
    priority: 0.7,
  }));

  const blogRoutes: MetadataRoute.Sitemap = blogSlugs.map(({ slug }) => ({
    url: `${baseUrl}/blog/${slug}`,
    lastModified: new Date(),
    changeFrequency: "monthly",
    priority: 0.6,
  }));

  return [...staticRoutes, ...screeningRoutes, ...docRoutes, ...blogRoutes];
}
