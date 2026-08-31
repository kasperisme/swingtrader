import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  cacheComponents: true,
  skipTrailingSlashRedirect: true,
  async redirects() {
    return [
      // Routes that were folded into other surfaces. Briefing emails already in
      // inboxes carry signed one-click links to these paths, and their tokens
      // stay valid for seven days — a 404 there is a lost sign-in, not just a
      // dead bookmark.
      {
        source: "/protected/screenings",
        destination: "/protected/workspace",
        permanent: true,
      },
      // The chart workspace and the relationship graph now live on each
      // ticker's quote page; the trend heatmap lives inside the workspace.
      { source: "/protected/charts", destination: "/quote", permanent: true },
      { source: "/protected/relations", destination: "/quote", permanent: true },
      {
        source: "/protected/news-trends",
        destination: "/protected/workspace",
        permanent: true,
      },
    ];
  },
  async rewrites() {
    return [
      {
        source: "/ingest/static/:path*",
        destination: "https://eu-assets.i.posthog.com/static/:path*",
      },
      {
        source: "/ingest/array/:path*",
        destination: "https://eu-assets.i.posthog.com/array/:path*",
      },
      {
        source: "/ingest/:path*",
        destination: "https://eu.i.posthog.com/:path*",
      },
    ];
  },
};

export default nextConfig;
