/**
 * schema.org markup for /articles/[slug].
 *
 * Lives outside page.tsx so the gate constants below can be imported by both
 * the server page and the client-side ClusterScoreCard — a value exported from
 * a "use client" module arrives on the server as a client reference, not the
 * number, so the card cannot be the one that owns them.
 */

import { SITE_URL, SITE_NAME, AUTHOR } from "@/lib/site";

/**
 * Class on every blurred, sign-up-gated block on the page. The paywall markup
 * points Google at it: those rows are in the HTML Googlebot reads but
 * unreadable to a visitor, which without `isAccessibleForFree` + `hasPart` is
 * indistinguishable from cloaking.
 */
export const GATED_CLASS = "nis-gated";

/** Cluster rows shown before the ClusterScoreCard's gate. */
export const CLUSTER_FREE_ROWS = 4;
/** |score| below which a cluster row counts as zero and is hidden by default. */
export const CLUSTER_NONZERO_EPS = 0.03;

/** Shown when a story carries no image of its own — the site's OG card. */
const FALLBACK_IMAGE = `${SITE_URL}/opengraph-image.png`;

export type AboutCompany = {
  ticker: string;
  name: string | null;
  exchange: string | null;
};

/**
 * `tickers.exchange` holds FMP's long listing names ("NEW YORK STOCK
 * EXCHANGE", "NASDAQ GLOBAL SELECT", …); schema.org's tickerSymbol wants the
 * short exchange code. Anything unrecognised falls back to the bare ticker.
 */
function exchangeCode(exchange: string | null): string | null {
  const e = (exchange ?? "").toUpperCase();
  if (e.includes("NASDAQ")) return "NASDAQ";
  if (e.includes("ARCA")) return "NYSEARCA";
  if (e.includes("NEW YORK STOCK EXCHANGE") || e === "NYSE") return "NYSE";
  return null;
}

export function buildArticleJsonLd(input: {
  canonicalUrl: string;
  headline: string;
  description: string;
  datePublished: string;
  /** When our analysis row was written — never earlier than datePublished. */
  dateModified: string;
  imageUrl: string | null;
  companies: AboutCompany[];
  /** Theme tags, human-formatted. */
  keywords: string[];
  /** The ongoing stories (topic hubs) this article belongs to. */
  sections: string[];
  sourceUrl: string | null;
  sourceName: string | null;
  hasGatedContent: boolean;
}) {
  const org = { "@id": `${SITE_URL}/#organization` };
  const published = Date.parse(input.datePublished);
  const modified = Date.parse(input.dateModified);
  const dateModified =
    Number.isFinite(modified) && (!Number.isFinite(published) || modified >= published)
      ? input.dateModified
      : input.datePublished;

  const article = {
    "@type": "NewsArticle",
    "@id": `${input.canonicalUrl}#article`,
    headline: input.headline,
    description: input.description,
    datePublished: input.datePublished,
    dateModified,
    inLanguage: "en",
    image: [input.imageUrl || FALLBACK_IMAGE],
    url: input.canonicalUrl,
    mainEntityOfPage: { "@id": input.canonicalUrl },
    isPartOf: { "@id": `${SITE_URL}/#website` },
    author: {
      "@type": "Person",
      "@id": `${SITE_URL}/#author`,
      name: AUTHOR.name,
      url: AUTHOR.url,
    },
    // Full node rather than a bare @id: Google does not reliably merge nodes
    // across separate ld+json blocks, and publisher.logo is what it reads.
    publisher: {
      "@type": "Organization",
      ...org,
      name: SITE_NAME,
      url: SITE_URL,
      logo: { "@type": "ImageObject", url: `${SITE_URL}/icon.png` },
    },
    // Exchange-qualified ticker ("NASDAQ AAPL") is the form schema.org
    // specifies; the company name is what lets the entity resolve at all.
    about: input.companies.length
      ? input.companies.map((c) => {
          const code = exchangeCode(c.exchange);
          return {
            "@type": "Corporation",
            ...(c.name ? { name: c.name } : {}),
            tickerSymbol: code ? `${code} ${c.ticker}` : c.ticker,
          };
        })
      : undefined,
    keywords: input.keywords.length ? input.keywords.join(", ") : undefined,
    articleSection: input.sections.length ? input.sections : undefined,
    // The analysis is ours; the reporting is the source's. Credit it as such.
    isBasedOn: input.sourceUrl
      ? {
          "@type": "NewsArticle",
          url: input.sourceUrl,
          ...(input.sourceName
            ? { publisher: { "@type": "Organization", name: input.sourceName } }
            : {}),
        }
      : undefined,
    ...(input.hasGatedContent
      ? {
          isAccessibleForFree: false,
          hasPart: {
            "@type": "WebPageElement",
            isAccessibleForFree: false,
            cssSelector: `.${GATED_CLASS}`,
          },
        }
      : { isAccessibleForFree: true }),
  };

  const breadcrumbs = {
    "@type": "BreadcrumbList",
    "@id": `${input.canonicalUrl}#breadcrumb`,
    itemListElement: [
      { "@type": "ListItem", position: 1, name: "Home", item: SITE_URL },
      { "@type": "ListItem", position: 2, name: "The Tape", item: `${SITE_URL}/articles` },
      { "@type": "ListItem", position: 3, name: input.headline, item: input.canonicalUrl },
    ],
  };

  return { "@context": "https://schema.org", "@graph": [article, breadcrumbs] };
}
