import Link from "next/link";
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { ArrowUpRight, Clock, FileText, TrendingDown, TrendingUp } from "lucide-react";
import {
  getTopicBySlug,
  getTopicFeed,
  getTopicKeyClaims,
  getTopicRecentClaims,
  getTopicStats,
  listTopics,
} from "@/app/actions/topics";

type Props = { params: Promise<{ slug: string }> };

// Must match the root layout's metadataBase host exactly. The site canonicalises
// on WWW; emitting a bare-host canonical here would split ranking signals
// between two hosts for these pages alone.
const SITE = (process.env.NEXT_PUBLIC_SITE_URL ?? "https://www.newsimpactscreener.com").replace(/\/$/, "");

/**
 * Rendered per request, matching every other public page here — the project runs
 * Next's `cacheComponents`, which rejects route-segment `revalidate` outright.
 * Affordable because the two queries behind the page are cheap by construction:
 * the feed is an indexed view (~30ms) and the arc is pre-materialized, so nothing
 * heavy runs at request time.
 */

export async function generateStaticParams() {
  const topics = await listTopics();
  return topics.map((t) => ({ slug: t.slug }));
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const topic = await getTopicBySlug(slug);
  if (!topic) return { title: "Topic not found" };

  const stats = await getTopicStats(slug);
  const description =
    topic.seo_description ??
    `${topic.title} — ${stats.articleCount} tracked stories and the scored market impact of each, updated as news lands.`;
  const canonical = `${SITE}/topics/${topic.slug}`;

  return {
    title: topic.title,   // root layout appends "· News Impact Screener" via its template
    description,
    keywords: [...topic.theme_tags, ...topic.lens_tickers],
    alternates: { canonical },
    openGraph: {
      type: "article",
      title: topic.title,
      description,
      url: canonical,
      siteName: "News Impact Screener",
      // A tracker's value is that it is current — tell crawlers and social when it
      // last actually changed rather than when the file was deployed.
      modifiedTime: stats.lastSeen ?? undefined,
      publishedTime: stats.firstSeen ?? undefined,
    },
    twitter: { card: "summary_large_image", title: topic.title, description },
  };
}

function fmtDate(iso: string | null | undefined) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

function ImpactPill({ impact }: { impact: number }) {
  const up = impact >= 0;
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1 rounded-md px-1.5 py-0.5 font-mono text-xs tabular-nums ${
        up
          ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
          : "bg-red-500/10 text-red-600 dark:text-red-400"
      }`}
    >
      {up ? <TrendingUp className="size-3" /> : <TrendingDown className="size-3" />}
      {impact >= 0 ? "+" : ""}
      {impact.toFixed(2)}
    </span>
  );
}

export default async function TopicPage({ params }: Props) {
  const { slug } = await params;
  const topic = await getTopicBySlug(slug);
  if (!topic) notFound();

  const [stats, keyClaims, recentClaims, feed] = await Promise.all([
    getTopicStats(slug),
    getTopicKeyClaims(slug, 10),
    getTopicRecentClaims(slug, 8),
    getTopicFeed(slug, 24),
  ]);

  const canonical = `${SITE}/topics/${topic.slug}`;

  // Structured data. A topic hub is a curated collection over dated reporting, so
  // it declares as a CollectionPage whose items are the tracked stories — that is
  // what it actually is, and mismatched schema is worse than none.
  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "CollectionPage",
    "@id": canonical,
    url: canonical,
    name: topic.title,
    description: topic.seo_description ?? topic.subtitle ?? topic.title,
    isPartOf: { "@type": "WebSite", name: "News Impact Screener", url: SITE },
    dateModified: stats.lastSeen ?? undefined,
    datePublished: stats.firstSeen ?? undefined,
    about: topic.lens_tickers.map((t) => ({ "@type": "Corporation", tickerSymbol: t })),
    mainEntity: {
      "@type": "ItemList",
      numberOfItems: feed.length,
      itemListElement: feed.slice(0, 20).map((a, i) => ({
        "@type": "ListItem",
        position: i + 1,
        url: a.article_slug ? `${SITE}/articles/${a.article_slug}` : undefined,
        name: a.title,
      })),
    },
  };

  const breadcrumbLd = {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: [
      { "@type": "ListItem", position: 1, name: "Home", item: SITE },
      { "@type": "ListItem", position: 2, name: "Topics", item: `${SITE}/topics` },
      { "@type": "ListItem", position: 3, name: topic.title, item: canonical },
    ],
  };

  return (
    <main className="mx-auto w-full max-w-4xl px-4 py-10 sm:px-6">
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(breadcrumbLd) }}
      />

      <nav aria-label="Breadcrumb" className="mb-6 text-sm text-muted-foreground">
        <Link href="/topics" className="hover:text-foreground">
          Topics
        </Link>
        <span className="mx-2">/</span>
        <span className="text-foreground">{topic.title}</span>
      </nav>

      <header className="mb-10">
        <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">{topic.title}</h1>
        {topic.subtitle && (
          <p className="mt-3 text-lg text-muted-foreground">{topic.subtitle}</p>
        )}

        <dl className="mt-6 flex flex-wrap gap-x-8 gap-y-3 text-sm">
          <div>
            <dt className="text-muted-foreground">Stories tracked</dt>
            <dd className="font-mono text-base tabular-nums">{stats.articleCount.toLocaleString()}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Scored claims</dt>
            <dd className="font-mono text-base tabular-nums">{stats.claimCount.toLocaleString()}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Covering</dt>
            <dd className="font-mono text-base">
              {fmtDate(stats.firstSeen)} → {fmtDate(stats.lastSeen)}
            </dd>
          </div>
        </dl>

        <div className="mt-5 flex flex-wrap gap-1.5">
          {topic.lens_tickers.map((t) => (
            <Link
              key={t}
              href={`/quote/${t}`}
              className="rounded-md border px-2 py-0.5 font-mono text-xs hover:bg-accent"
            >
              ${t}
            </Link>
          ))}
        </div>
      </header>

      {/* The arc — what actually defined this story, ranked by scored impact. */}
      <section className="mb-12" aria-labelledby="key-developments">
        <h2 id="key-developments" className="mb-1 text-xl font-semibold tracking-tight">
          The developments that moved this
        </h2>
        <p className="mb-5 text-sm text-muted-foreground">
          The highest-impact scored claims across the whole story, newest wording kept
          when a development was reported many times. Each is dated — an old number is
          not a current one.
        </p>
        <ol className="space-y-4">
          {keyClaims.map((c, i) => (
            <li key={`${c.article_slug}-${i}`} className="border-l-2 pl-4">
              <div className="flex items-start gap-2">
                <ImpactPill impact={c.impact} />
                <p className="text-[15px] leading-relaxed">{c.claim}</p>
              </div>
              <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                <time dateTime={c.article_ts}>{fmtDate(c.article_ts)}</time>
                {c.tickers?.slice(0, 4).map((t) => (
                  <span key={t} className="font-mono">
                    ${t}
                  </span>
                ))}
                {c.article_slug && (
                  <Link
                    href={`/articles/${c.article_slug}`}
                    className="inline-flex items-center gap-0.5 hover:text-foreground"
                  >
                    source <ArrowUpRight className="size-3" />
                  </Link>
                )}
              </div>
            </li>
          ))}
        </ol>
      </section>

      {/* Explicitly separated from the arc so recency is never implied by ranking. */}
      <section className="mb-12" aria-labelledby="latest-claims">
        <h2 id="latest-claims" className="mb-1 flex items-center gap-2 text-xl font-semibold tracking-tight">
          <Clock className="size-4" /> Latest
        </h2>
        <p className="mb-5 text-sm text-muted-foreground">
          The most recent scored claims on this story.
        </p>
        <ol className="space-y-3">
          {recentClaims.map((c, i) => (
            <li key={`recent-${i}`} className="flex items-start gap-2 text-sm">
              <ImpactPill impact={c.impact} />
              <div>
                <p className="leading-relaxed">{c.claim}</p>
                <time dateTime={c.article_ts} className="text-xs text-muted-foreground">
                  {fmtDate(c.article_ts)}
                </time>
              </div>
            </li>
          ))}
        </ol>
      </section>

      {/* The live edge: straight off the membership view, no materialization. */}
      <section aria-labelledby="feed">
        <h2 id="feed" className="mb-1 flex items-center gap-2 text-xl font-semibold tracking-tight">
          <FileText className="size-4" /> Every story we&apos;re tracking
        </h2>
        <p className="mb-5 text-sm text-muted-foreground">
          New coverage joins automatically as it is scored.
        </p>
        <ul className="divide-y">
          {feed.map((a) => (
            <li key={a.article_id} className="py-3">
              <Link
                href={a.article_slug ? `/articles/${a.article_slug}` : "#"}
                className="group flex items-baseline justify-between gap-4"
              >
                <span className="text-[15px] leading-snug group-hover:underline">{a.title}</span>
                <time
                  dateTime={a.published_at}
                  className="shrink-0 font-mono text-xs text-muted-foreground"
                >
                  {fmtDate(a.published_at)}
                </time>
              </Link>
              {a.matched_tickers && a.matched_tickers.length > 0 && (
                <div className="mt-1 flex gap-1.5">
                  {a.matched_tickers.map((t) => (
                    <span key={t} className="font-mono text-xs text-muted-foreground">
                      ${t}
                    </span>
                  ))}
                </div>
              )}
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}
