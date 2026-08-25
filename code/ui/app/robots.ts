import type { MetadataRoute } from "next";

import { SITE_URL } from "@/lib/site";

const baseUrl = SITE_URL;

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
          "/about",
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
