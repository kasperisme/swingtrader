import { connection } from "next/server";
import { isSanityConfigured, sanityFetch } from "@/lib/sanity/client";
import { docPagePreviewsQuery, blogPostPreviewsQuery } from "@/lib/sanity/queries";

// /llms.txt — a curated, human-readable map of the site for inference-time LLM
// consumption (the llmstxt.org convention). Complements robots.ts / sitemap.ts,
// which target search crawlers. Generated at request time so the docs + blog
// sections stay in sync with Sanity, exactly like sitemap.ts.

const baseUrl =
  process.env.NEXT_PUBLIC_SITE_URL ?? "https://newsimpactscreener.com";

// Cap the per-post list so the file stays a concise index, not a full dump.
const BLOG_LLMS_LIMIT = 25;

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

function line(name: string, url: string, note?: string): string {
  const n = clean(note);
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

  // --- Core pages (curated, stable) ---
  out.push("## Core pages");
  out.push("");
  out.push(line("Home", `${baseUrl}/`, "Product overview, features, and pricing."));
  out.push(line("Pricing", `${baseUrl}/pricing`, "Plans and what each tier includes."));
  out.push(
    line(
      "Market screenings",
      `${baseUrl}/marketscreenings`,
      "Gallery of curated screeners; individual screeners at /marketscreenings/{slug}.",
    ),
  );
  out.push(
    line(
      "News articles",
      `${baseUrl}/articles`,
      "Live news feed with impact scores; individual stories at /articles/{slug}.",
    ),
  );
  out.push(
    line(
      "Stock quotes",
      `${baseUrl}/quote`,
      "Per-ticker news-impact analysis. Each US ticker lives at /quote/{SYMBOL}, e.g. /quote/NVDA.",
    ),
  );
  out.push(line("Changelog", `${baseUrl}/changelog`, "Product updates and releases."));
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
