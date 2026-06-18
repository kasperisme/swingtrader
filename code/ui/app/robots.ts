import type { MetadataRoute } from "next";

const baseUrl =
  process.env.NEXT_PUBLIC_SITE_URL ?? "https://newsimpactscreener.com";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: [
          "/",
          "/articles",
          "/blog",
          "/docs",
          "/marketscreenings",
          "/quote",
          "/pricing",
          "/changelog",
          "/terms",
          "/privacy",
          "/podcast/feed.xml",
        ],
        disallow: [
          "/protected/",
          "/auth/",
          "/login",
          "/studio/",
          "/api/",
          "/x/",
          "/marketscreenings/*/export",
        ],
      },
    ],
    sitemap: `${baseUrl}/sitemap.xml`,
    host: baseUrl,
  };
}
