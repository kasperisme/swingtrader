import { connection } from "next/server";
import { isSanityConfigured, sanityFetch } from "@/lib/sanity/client";
import { docPagePreviewsQuery, blogPostPreviewsQuery } from "@/lib/sanity/queries";
import { SITE_URL as baseUrl } from "@/lib/site";

// /llms.txt — a curated, human-readable map of the site for inference-time LLM
// consumption (the llmstxt.org convention). Complements robots.ts / sitemap.ts,
// which target search crawlers. Generated at request time so the docs + blog
// sections stay in sync with Sanity, exactly like sitemap.ts.


// Cap the per-post list so the file stays a concise index, not a full dump.
//
// Was 25, which made the blog 25 of 60 links — 42% of the file — and every one
// of them a dated "Pre-Market News Impact: <date>" entry with no excerpt. That
// is the same mistake the sitemap had: the least distinctive content taking the
// most room. It costs more here than in a sitemap, because llms.txt is read
// into a context window, so those lines crowd out the pages that would actually
// make a model recommend the product. Blog home is still linked for the rest.
const BLOG_LLMS_LIMIT = 6;

type DocPreview = {
  title: string;
  slug: string;
  section?: string;
  description?: string;
};

type BlogPreview = {
  title: string;
  slug: string;
  excerpt?: string;
};

function clean(text: string | undefined, max = 160): string {
  if (!text) return "";
  const flat = text.replace(/\s+/g, " ").trim();
  return flat.length > max ? `${flat.slice(0, max - 1).trimEnd()}…` : flat;
}

// `max` is overridable because a handful of entries stand for a whole surface
// rather than a single page — /quote is one page template covering ~1,500
// tickers and four distinct tools — and the default 160 characters silently
// truncates those into something that undersells what is there.
function line(name: string, url: string, note?: string, max = 160): string {
  const n = clean(note, max);
  return n ? `- [${name}](${url}): ${n}` : `- [${name}](${url})`;
}

export async function GET(): Promise<Response> {
  // Built from live Sanity data — generate at request time rather than during
  // the static prerender (which tears down in-flight fetches).
  await connection();

  const out: string[] = [];

  out.push("# News Impact Screener");
  out.push("");
  out.push(
    "> Swing-trading research platform that maps every breaking story to the tickers and sectors it touches — within minutes, not hours. Built for retail investors who want signal, not noise.",
  );
  out.push("");
  out.push(
    "News Impact Screener scores market-moving news in real time and connects each headline to the stocks it affects, surfacing actionable swing-trade setups. The pages below are the public, crawlable surface of the product. Authenticated areas (`/protected/*`), auth flows (`/auth/*`), the Sanity Studio (`/studio`), and API routes are intentionally excluded.",
  );
  out.push("");

  // --- The public surfaces, grouped the way the site groups them ---
  //
  // These three headings mirror the two dropdowns in the public header
  // (INSIGHTS_LINKS / FREE_SERVICE_LINKS in components/site-header-public-nav)
  // plus the standalone product pages. Keeping the same shape is the point: an
  // LLM reading this gets the site's own information architecture, and when a
  // surface is added to the nav there is one obvious place to add it here.
  //
  // This section previously listed six pages under "Core pages" and had drifted
  // badly — /topics, /arena, /traders and /research were all live and all
  // absent, which is four of the six Insights entries. Individual entity pages
  // are described by their {slug} pattern rather than enumerated, the same way
  // /quote and /articles have always been handled here: this file is a map, not
  // an index, and the sitemap is linked below for the exhaustive list.
  out.push("## Insights");
  out.push("");
  out.push(
    line(
      "News articles",
      `${baseUrl}/articles`,
      "Live news feed with impact scores; individual stories at /articles/{slug}.",
    ),
  );
  out.push(
    line(
      "Topics",
      `${baseUrl}/topics`,
      "Live trackers for stories that keep developing, each new development scored for market impact. Hubs at /topics/{slug}.",
    ),
  );
  // Not "live quotes" — the price is the least of it. This one template carries
  // the charting workspace and the relationship graph (both moved here from
  // /protected/charts and /protected/relations) plus the priced-in
  // reconstruction, and the old one-line description sold none of that.
  out.push(
    line(
      "Ticker research pages",
      `${baseUrl}/quote`,
      "One research workspace per ticker at /quote/{SYMBOL}, e.g. /quote/NVDA: scored news catalysts plotted on the price chart, an interactive charting workspace, a priced-in reconstruction of what the current price already reflects, and a relationship network of connected tickers (suppliers, customers, competitors) — plus sentiment, peers and key statistics.",
      400,
    ),
  );
  // Agents are described here rather than given their own entry: there is no
  // /agent hub route, only /agent/[slug], so linking /agent would be a 404.
  out.push(
    line(
      "The Arena",
      `${baseUrl}/arena`,
      "Nine AI agents, $100,000 each, same model and risk limits — only their data access differs; two are deterministic controls. Agents at /agent/{slug}.",
    ),
  );
  out.push(
    line(
      "Famous traders",
      `${baseUrl}/traders`,
      "Reference profiles of well-known traders and their methods; several are the named influence behind an Arena agent.",
    ),
  );
  out.push(
    line(
      "Research",
      `${baseUrl}/research`,
      "Published research write-ups and methodology; individual pieces at /research/{slug}.",
    ),
  );
  out.push("");

  out.push("## Free services");
  out.push("");
  out.push(
    line(
      "Daily news briefing",
      `${baseUrl}/briefings`,
      "Free daily PDF of the news moving your chosen tickers and tags, delivered before the open. No account required.",
    ),
  );
  out.push(
    line(
      "Market screenings",
      `${baseUrl}/marketscreenings`,
      "Gallery of curated screeners; individual screeners at /marketscreenings/{slug}.",
    ),
  );
  out.push("");

  out.push("## Product");
  out.push("");
  out.push(line("Home", `${baseUrl}/`, "Product overview, features, and pricing."));
  out.push(line("Pricing", `${baseUrl}/pricing`, "Plans and what each tier includes."));
  out.push(line("About", `${baseUrl}/about`, "Methodology, data sources, and disclaimers."));
  out.push("");

  // --- Documentation (live from Sanity) ---
  let docs: DocPreview[] = [];
  let blog: BlogPreview[] = [];
  if (isSanityConfigured) {
    try {
      [docs, blog] = await Promise.all([
        sanityFetch<DocPreview[]>(docPagePreviewsQuery),
        sanityFetch<BlogPreview[]>(blogPostPreviewsQuery),
      ]);
    } catch (e) {
      console.warn("[llms.txt] failed to fetch Sanity content", e);
    }
  }

  if (docs.length > 0) {
    out.push("## Documentation");
    out.push("");
    out.push(line("Docs home", `${baseUrl}/docs`, "Start here for how the screener works."));
    for (const d of docs) {
      if (!d.slug) continue;
      out.push(line(d.title, `${baseUrl}/docs/${d.slug}`, d.description));
    }
    out.push("");
  }

  if (blog.length > 0) {
    out.push("## Blog");
    out.push("");
    out.push(line("Blog home", `${baseUrl}/blog`, "Swing-trading research, market commentary, and product writing."));
    for (const p of blog.slice(0, BLOG_LLMS_LIMIT)) {
      if (!p.slug) continue;
      out.push(line(p.title, `${baseUrl}/blog/${p.slug}`, p.excerpt));
    }
    out.push("");
  }

  // --- Optional (skippable for a shorter context) ---
  out.push("## Optional");
  out.push("");
  out.push(line("Terms of service", `${baseUrl}/terms`));
  out.push(line("Privacy policy", `${baseUrl}/privacy`));
  out.push(line("Podcast feed", `${baseUrl}/podcast/feed.xml`, "RSS feed for the audio briefings."));
  out.push(line("Sitemap", `${baseUrl}/sitemap.xml`, "Full machine-readable URL index."));
  out.push("");

  const body = out.join("\n");

  return new Response(body, {
    headers: {
      "Content-Type": "text/plain; charset=utf-8",
      // Edge/CDN cache: serve stale up to a day while revalidating.
      "Cache-Control": "public, max-age=3600, s-maxage=86400, stale-while-revalidate=86400",
    },
  });
}
