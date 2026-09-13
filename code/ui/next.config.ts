import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  cacheComponents: true,
  skipTrailingSlashRedirect: true,
  // Bots matching this get <title>, description, canonical and robots in <head>
  // instead of streamed in after it. Next's default list (html-bots.js) catches
  // Google-InspectionTool but NOT plain Googlebot, so Search Console's live test
  // saw the metadata while the real crawler got a head with none of it — the
  // thin-article noindex and every canonical existed only in the RSC payload.
  // This setting REPLACES the default, so it is the default plus Googlebot.
  //
  // Googlebot must NOT be the first (or last) alternative. The same string is
  // the Vercel edge's cache-bypass rule, which anchors the pattern: as the first
  // alternative it matched only a UA that STARTS with "Googlebot", so the real
  // "Mozilla/5.0 (compatible; Googlebot/2.1 …)" got the cached streamed page.
  htmlLimitedBots:
    /[\w-]+-Google|Google-[\w-]+|Chrome-Lighthouse|Slurp|DuckDuckBot|baiduspider|yandex|sogou|bitlybot|tumblr|vkShare|quora link preview|redditbot|ia_archiver|Googlebot|Bingbot|BingPreview|applebot|facebookexternalhit|facebookcatalog|Twitterbot|LinkedInBot|Slackbot|Discordbot|WhatsApp|SkypeUriPreview|Yeti|googleweblight/i,
  images: {
    // next/image refuses any host not listed here, so without this a portrait
    // uploaded in the Studio 500s rather than rendering — the failure looks
    // like the upload did not work.
    remotePatterns: [
      { protocol: "https", hostname: "cdn.sanity.io", pathname: "/images/**" },
    ],
  },

  async redirects() {
    return [
      // Agents moved out of /arena and onto their own entity route. An agent
      // persists across championships; the arena is a season it appears in, so
      // nesting the agent under it made the URL claim otherwise. These URLs are
      // in the sitemap and carry structured data, so the move is a 308 rather
      // than a fresh set of 404s.
      // An agent renamed in place keeps its row, so its old URL points at the
      // same entity — a 308, not a 404. Listed BEFORE the /arena/:slug rule so
      // the old /arena path lands on the new slug in one hop.
      { source: "/agent/chris-cameo", destination: "/agent/jim-chaos", permanent: true },
      { source: "/arena/chris-cameo", destination: "/agent/jim-chaos", permanent: true },
      {
        source: "/arena/:slug",
        destination: "/agent/:slug",
        permanent: true,
      },
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
