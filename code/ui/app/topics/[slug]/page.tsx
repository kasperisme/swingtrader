import { cache } from "react";
import Link from "next/link";
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Activity, ArrowUpRight, BarChart3, Clock, FileText } from "lucide-react";
import {
  getTopicBySlug,
  getTopicFeed,
  getTopicKeyClaims,
  getTopicRecentClaims,
  getTopicStats,
  getTopicVisuals,
  listTopics,
  type TopicClaim,
} from "@/app/actions/topics";
import { TickerLogo } from "@/components/ticker-logo";
import { accentFor } from "../_components/accent";
import { ClaimTimeline, TickerImpactBars } from "../_components/topic-visuals";
import { SITE_URL } from "@/lib/site";

type Props = { params: Promise<{ slug: string }> };

/**
 * generateMetadata and the page body both need the topic and its stats, and
 * these are direct Supabase calls — Next's fetch-level dedupe does not touch
 * them, so every request was running both queries twice. React's cache() makes
 * the second call within the same request a hit.
 */
const loadTopic = cache(getTopicBySlug);
const loadStats = cache(getTopicStats);

/** Unknown is rendered as "—"; only a real count prints a number. */
function fmtCount(n: number | null): string {
  return n == null ? "—" : n.toLocaleString();
}

const SITE = SITE_URL;

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
  const [topic, stats] = await Promise.all([loadTopic(slug), loadStats(slug)]);
  if (!topic) return { title: "Topic not found" };
  const description =
    topic.seo_description ??
    `${topic.title} — ${fmtCount(stats.articleCount)} tracked stories and the scored market impact of each, updated as news lands.`;
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

/**
 * Impact is signed on the same -1..+1 scale the /quote board plots sentiment on,
 * so it reads the same way here: sign, colour and number together, never colour
 * alone. Solid text on a tinted chip rather than the old 10%-opacity fill, which
 * could not clear 4.5:1 in light mode.
 */
function ImpactPill({ impact }: { impact: number }) {
  const up = impact >= 0;
  return (
    <span
      className={`inline-flex shrink-0 items-center rounded px-1.5 py-0.5 font-mono text-xs font-medium tabular-nums ${
        up
          ? "bg-emerald-500/15 text-emerald-800 dark:text-emerald-300"
          : "bg-rose-500/15 text-rose-800 dark:text-rose-300"
      }`}
      title={`Scored market impact ${impact.toFixed(2)} on a scale of -1 to 1`}
    >
      {up ? "+" : ""}
      {impact.toFixed(2)}
    </span>
  );
}

/**
 * One scored claim, as a card that opens the article it came from.
 *
 * The whole card is the target, but it is NOT wrapped in a link: the row also
 * carries per-ticker links, and an anchor inside an anchor is invalid and gets
 * re-parented by the browser. Instead the source link is stretched over the card
 * with `after:absolute after:inset-0`, and the ticker links sit above it on
 * `z-10` — so there is still exactly one real link per destination, keyboard
 * order is unchanged, and each stretched link is named by the article it opens
 * rather than ten identical "read the story"s.
 */
function ClaimRow({
  claim,
  variant,
  railClass,
  index,
}: {
  claim: TopicClaim;
  variant: "arc" | "recent";
  railClass: string;
  index: number;
}) {
  const href = claim.article_slug ? `/articles/${claim.article_slug}` : null;
  const interactive = href
    ? "transition-colors hover:bg-muted/60 focus-within:bg-muted/60"
    : "";

  return (
    <li
      className={
        variant === "arc"
          ? `group animate-screening-row-in relative rounded-r border-l-2 py-2 pl-5 pr-3 ${railClass} ${interactive}`
          : `group relative rounded py-3.5 pl-1 pr-3 ${interactive}`
      }
      style={variant === "arc" ? { animationDelay: `${Math.min(index, 12) * 30}ms` } : undefined}
    >
      <div className="flex items-start gap-2.5">
        <ImpactPill impact={claim.impact} />
        <p className={variant === "arc" ? "text-[15px] leading-relaxed" : "text-sm leading-relaxed"}>
          {claim.claim}
        </p>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-xs text-muted-foreground">
        <time dateTime={claim.article_ts}>{fmtDate(claim.article_ts)}</time>
        {claim.tickers?.slice(0, 4).map((t) => (
          <Link
            key={t}
            href={`/quote/${t}`}
            className="relative z-10 transition-colors hover:text-foreground"
          >
            ${t}
          </Link>
        ))}
        {href && (
          <Link
            href={href}
            className="inline-flex items-center gap-0.5 rounded transition-colors after:absolute after:inset-0 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500/60"
          >
            read the story <ArrowUpRight className="size-3" aria-hidden />
            {claim.article_title && (
              <span className="sr-only">: {claim.article_title}</span>
            )}
          </Link>
        )}
      </div>
    </li>
  );
}

function SectionHeading({
  id,
  icon,
  title,
  blurb,
}: {
  id: string;
  icon?: React.ReactNode;
  title: string;
  blurb: string;
}) {
  return (
    <>
      <h2
        id={id}
        className="flex items-center gap-2 text-xl font-semibold tracking-tight sm:text-2xl"
      >
        {icon}
        {title}
      </h2>
      <p className="mb-6 mt-1.5 max-w-[62ch] text-sm leading-relaxed text-muted-foreground">
        {blurb}
      </p>
    </>
  );
}

export default async function TopicPage({ params }: Props) {
  const { slug } = await params;
  // All five start together — only notFound() depends on the topic row, and the
  // slug that the other four need came in on the URL.
  const [topic, stats, visuals, keyClaims, recentClaims, feed] = await Promise.all([
    loadTopic(slug),
    loadStats(slug),
    getTopicVisuals(slug),
    getTopicKeyClaims(slug, 10),
    getTopicRecentClaims(slug, 8),
    getTopicFeed(slug, 24),
  ]);
  if (!topic) notFound();

  const accent = accentFor(topic.accent);
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

      <nav aria-label="Breadcrumb" className="mb-6 font-mono text-xs text-muted-foreground">
        <Link
          href="/topics"
          className="underline decoration-border underline-offset-4 transition-colors hover:text-foreground"
        >
          Topics
        </Link>
        <span className="mx-2 text-muted-foreground" aria-hidden>
          /
        </span>
        <span className="text-foreground">{topic.title}</span>
      </nav>

      <header className="mb-12 border-b border-border/60 pb-8">
        {/* The eyebrow carries the topic's own accent — same rule and rhythm as
            every other board, only the hue changes. */}
        <div className="mb-3 flex items-center justify-between gap-4">
          <p
            className={`inline-flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.2em] ${accent.label}`}
          >
            <span className={`h-px w-6 ${accent.rule}`} />
            Live tracker
          </p>
          <span className="shrink-0 rounded-full border border-border px-2.5 py-1 font-mono text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
            Updated {fmtDate(stats.lastSeen)}
          </span>
        </div>

        <h1 className="text-4xl font-bold leading-[1.05] tracking-tighter sm:text-5xl">
          {topic.title}
        </h1>
        {topic.subtitle && (
          <p className="mt-4 max-w-[58ch] text-sm leading-relaxed text-muted-foreground">
            {topic.subtitle}
          </p>
        )}

        <dl className="mt-7 flex flex-wrap gap-x-10 gap-y-4">
          <div>
            <dt className="font-mono text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
              Stories tracked
            </dt>
            <dd className="mt-1 font-mono text-lg tabular-nums">
              {fmtCount(stats.articleCount)}
            </dd>
          </div>
          <div>
            <dt className="font-mono text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
              Scored claims
            </dt>
            <dd className="mt-1 font-mono text-lg tabular-nums">
              {fmtCount(stats.claimCount)}
            </dd>
          </div>
          <div>
            <dt className="font-mono text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
              Covering
            </dt>
            <dd className="mt-1 font-mono text-lg tabular-nums">
              {fmtDate(stats.firstSeen)} → {fmtDate(stats.lastSeen)}
            </dd>
          </div>
        </dl>

        {/* The lens: which tickers this story is actually read through. Each is a
            way into that ticker's own board, so the two hubs interlink. */}
        {topic.lens_tickers.length > 0 && (
          <div className="mt-7">
            <p className="mb-2.5 font-mono text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
              Read through
            </p>
            <ul className="flex flex-wrap gap-2">
              {topic.lens_tickers.map((t) => (
                <li key={t}>
                  <Link
                    href={`/quote/${t}`}
                    className="group inline-flex items-center gap-2 rounded-lg border border-border py-1 pl-1 pr-2.5 transition-colors hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500/60"
                  >
                    <TickerLogo symbol={t} className="h-7 w-7" />
                    <span
                      className={`font-mono text-xs font-semibold transition-colors ${accent.hoverText}`}
                    >
                      {t}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        )}
      </header>

      {/* Who the story actually moves. Placed before the arc because the arc is
          a list of individual claims — this is the shape of all 400+ at once. */}
      {visuals.byTicker.length > 0 && (
        <section className="mb-14" aria-labelledby="by-ticker">
          <SectionHeading
            id="by-ticker"
            icon={<BarChart3 className="size-4 shrink-0 text-muted-foreground" aria-hidden />}
            title="Which names it moves"
            blurb="Mean scored impact per ticker across every claim in this story, next to how many claims mention it. Open a ticker for its own board."
          />
          <TickerImpactBars rows={visuals.byTicker} accent={accent} />
        </section>
      )}

      {visuals.byMonth.length > 1 && (
        <section className="mb-14" aria-labelledby="timeline">
          <SectionHeading
            id="timeline"
            icon={<Activity className="size-4 shrink-0 text-muted-foreground" aria-hidden />}
            title="How it built"
            blurb="Scored claims per month over the life of the story — the shape of the escalation, not a snapshot of it."
          />
          <ClaimTimeline months={visuals.byMonth} accent={accent} />
        </section>
      )}

      {/* The arc — what actually defined this story, ranked by scored impact. */}
      <section className="mb-14" aria-labelledby="key-developments">
        <SectionHeading
          id="key-developments"
          title="The developments that moved this"
          blurb="The highest-impact scored claims across the whole story, newest wording kept when a development was reported many times. Each is dated — an old number is not a current one."
        />
        <ol className="space-y-3">
          {keyClaims.map((c, i) => (
            <ClaimRow
              key={`${c.article_slug}-${i}`}
              claim={c}
              variant="arc"
              railClass={accent.rail}
              index={i}
            />
          ))}
        </ol>
      </section>

      {/* Explicitly separated from the arc so recency is never implied by ranking. */}
      <section className="mb-14" aria-labelledby="latest-claims">
        <SectionHeading
          id="latest-claims"
          icon={<Clock className="size-4 shrink-0 text-muted-foreground" aria-hidden />}
          title="Latest"
          blurb="The most recent scored claims on this story, in the order they landed."
        />
        <ol className="divide-y divide-border/60">
          {recentClaims.map((c, i) => (
            <ClaimRow
              key={`recent-${i}`}
              claim={c}
              variant="recent"
              railClass={accent.rail}
              index={i}
            />
          ))}
        </ol>
      </section>

      {/* The live edge: straight off the membership view, no materialization. */}
      <section aria-labelledby="feed">
        <SectionHeading
          id="feed"
          icon={<FileText className="size-4 shrink-0 text-muted-foreground" aria-hidden />}
          title="Every story we're tracking"
          blurb="New coverage joins automatically as it is scored — this list is the live membership of the topic, not a snapshot."
        />
        <ul className="divide-y divide-border/60">
          {feed.map((a) => (
            <li key={a.article_id}>
              <Link
                href={a.article_slug ? `/articles/${a.article_slug}` : "#"}
                className="group block py-3.5 transition-colors hover:bg-muted/60 focus-visible:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500/60"
              >
                <span className="flex items-baseline justify-between gap-4">
                  <span
                    className={`text-[15px] leading-snug transition-colors ${accent.hoverText}`}
                  >
                    {a.title}
                  </span>
                  <time
                    dateTime={a.published_at}
                    className="shrink-0 font-mono text-xs text-muted-foreground"
                  >
                    {fmtDate(a.published_at)}
                  </time>
                </span>
                {a.matched_tickers && a.matched_tickers.length > 0 && (
                  <span className="mt-1.5 flex flex-wrap gap-2">
                    {a.matched_tickers.map((t) => (
                      <span key={t} className="font-mono text-xs text-muted-foreground">
                        ${t}
                      </span>
                    ))}
                  </span>
                )}
              </Link>
            </li>
          ))}
        </ul>
      </section>

      <p className="mt-12 border-t border-border/60 pt-6 text-sm text-muted-foreground">
        <Link
          href="/topics"
          className={`underline underline-offset-4 transition-colors hover:text-foreground ${accent.underline}`}
        >
          All trackers
        </Link>{" "}
        ·{" "}
        <Link
          href="/quote"
          className={`underline underline-offset-4 transition-colors hover:text-foreground ${accent.underline}`}
        >
          Browse quotes
        </Link>
      </p>
    </main>
  );
}
