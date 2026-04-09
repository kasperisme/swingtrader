import type { MetadataRoute } from "next";
import { isSanityConfigured, sanityFetch } from "@/lib/sanity/client";
import { docPageSlugListQuery, blogPostSlugListQuery } from "@/lib/sanity/queries";

const baseUrl = process.env.NEXT_PUBLIC_SITE_URL ?? "https://newsimpactscreener.com";

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const staticRoutes: MetadataRoute.Sitemap = [
    { url: baseUrl, lastModified: new Date(), changeFrequency: "weekly", priority: 1 },
    { url: `${baseUrl}/blog`, lastModified: new Date(), changeFrequency: "weekly", priority: 0.8 },
    { url: `${baseUrl}/docs`, lastModified: new Date(), changeFrequency: "weekly", priority: 0.8 },
  ];

  if (!isSanityConfigured) return staticRoutes;

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

  return [...staticRoutes, ...docRoutes, ...blogRoutes];
}
