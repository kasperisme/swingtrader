import { Suspense } from "react";
import Link from "next/link";
import type { Metadata } from "next";
import { ArrowUpRight } from "lucide-react";
import { listTopicStats, listTopics, type TopicStats } from "@/app/actions/topics";
import { TickerLogo } from "@/components/ticker-logo";
import { accentFor } from "./_components/accent";

// Must match the root layout's metadataBase host exactly. The site canonicalises
// on WWW; emitting a bare-host canonical here would split ranking signals
// between two hosts for these pages alone.
const SITE = (
  process.env.NEXT_PUBLIC_SITE_URL ?? "https://www.newsimpactscreener.com"
).replace(/\/$/, "");

export const metadata: Metadata = {
  title: "Topics", // root layout template supplies the site suffix
  description:
    "Live trackers for the stories that keep moving markets — every development scored for market impact, updated as news lands.",
  alternates: { canonical: `${SITE}/topics` },
};

/** Unknown is rendered as "—"; only a real count prints a number. A failed
 *  count used to arrive here as 0, which reads as "this tracker has nothing". */
function fmtCount(n: number | null): string {
  return n == null ? "—" : n.toLocaleString();
}

function fmtDate(iso: string | null | undefined) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

function TrackersSkeleton() {
  return (
    <div className="grid gap-3" aria-hidden>
      {Array.from({ length: 2 }, (_, i) => (
        <div key={i} className="h-40 animate-pulse rounded-r-lg border-l-2 bg-muted/40" />
      ))}
    </div>
  );
}

async function Trackers() {
  // Fired together: neither depends on the other, and a round trip costs far
  // more than either query. Awaiting them in sequence doubled the page's latency.
  const [topics, statsBySlug] = await Promise.all([listTopics(), listTopicStats()]);
  const UNKNOWN: TopicStats = {
    articleCount: null, claimCount: null, firstSeen: null, lastSeen: null,
  };

  if (topics.length === 0) {
    return (
      <div className="border-l-2 border-amber-500/60 py-6 pl-5 text-sm text-muted-foreground">
        No trackers are published yet.
      </div>
    );
  }

  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "ItemList",
    name: "Story trackers",
    numberOfItems: topics.length,
    itemListElement: topics.map((t, i) => ({
      "@type": "ListItem",
      position: i + 1,
      url: `${SITE}/topics/${t.slug}`,
      name: t.title,
    })),
  };

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />

      <p className="mb-5 font-mono text-xs tabular-nums text-muted-foreground">
        <span className="text-foreground">{topics.length}</span> tracker
        {topics.length === 1 ? "" : "s"} · updated as new coverage is scored
      </p>

      <ul className="grid gap-3">
        {topics.map((t, i) => {
          const a = accentFor(t.accent);
          const s = statsBySlug[t.slug] ?? UNKNOWN;
          // hero_tickers is the curated face of a topic; lens_tickers is the
          // full query behind it, so fall back rather than showing nothing.
          const faces = (t.hero_tickers?.length ? t.hero_tickers : t.lens_tickers).slice(0, 4);

          return (
            <li
              key={t.slug}
              className="animate-screening-row-in"
              style={{ animationDelay: `${Math.min(i, 12) * 40}ms` }}
            >
              <Link
                href={`/topics/${t.slug}`}
                // A left rail in the topic's own accent rather than a uniform
                // boxed card — the trackers stay one system and still read apart.
                className={`group block rounded-r-lg border-y border-r border-l-2 ${a.rail} border-y-border/60 border-r-border/60 p-5 transition-colors hover:bg-muted/60 focus-visible:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500/60 sm:p-6`}
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0">
                    <h2
                      className={`text-xl font-semibold leading-snug tracking-tight transition-colors sm:text-2xl ${a.hoverText}`}
                    >
                      {t.title}
                    </h2>
                    {t.subtitle && (
                      <p className="mt-1.5 max-w-[60ch] text-sm leading-relaxed text-muted-foreground">
                        {t.subtitle}
                      </p>
                    )}
                  </div>
                  <ArrowUpRight
                    className="mt-1 size-4 shrink-0 text-muted-foreground transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5"
                    aria-hidden
                  />
                </div>

                <dl className="mt-5 flex flex-wrap gap-x-8 gap-y-3">
                  <div>
                    <dt className="font-mono text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
                      Stories
                    </dt>
                    <dd className="mt-1 font-mono text-sm tabular-nums">
                      {fmtCount(s.articleCount)}
                    </dd>
                  </div>
                  <div>
                    <dt className="font-mono text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
                      Scored claims
                    </dt>
                    <dd className="mt-1 font-mono text-sm tabular-nums">
                      {fmtCount(s.claimCount)}
                    </dd>
                  </div>
                  <div>
                    <dt className="font-mono text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
                      Latest
                    </dt>
                    <dd className="mt-1 font-mono text-sm tabular-nums">
                      {fmtDate(s.lastSeen)}
                    </dd>
                  </div>
                </dl>

                {/* Laid out, not stacked: an overlapping avatar cluster crops
                    square company marks into unreadable slivers. */}
                {faces.length > 0 && (
                  <div className="mt-5 flex flex-wrap items-center gap-2">
                    {faces.map((sym) => (
                      <span
                        key={sym}
                        className="inline-flex items-center gap-1.5 rounded-lg border border-border py-1 pl-1 pr-2"
                      >
                        <TickerLogo symbol={sym} className="h-6 w-6" />
                        <span className="font-mono text-xs text-muted-foreground">
                          {sym}
                        </span>
                      </span>
                    ))}
                  </div>
                )}
              </Link>
            </li>
          );
        })}
      </ul>
    </>
  );
}

export default async function TopicsIndex() {
  return (
    <main className="mx-auto w-full max-w-4xl px-4 py-10 sm:px-6">
      <header className="mb-10 border-b border-border/60 pb-8">
        <div className="mb-3 flex items-center justify-between gap-4">
          <p className="inline-flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.2em] text-amber-500/80">
            <span className="h-px w-6 bg-amber-500/60" />
            The Trackers
          </p>
          <span className="shrink-0 rounded-full border border-border px-2.5 py-1 font-mono text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
            Always on
          </span>
        </div>
        <h1 className="text-4xl font-bold leading-[1.05] tracking-tighter sm:text-5xl">
          Topics
        </h1>
        <p className="mt-4 max-w-[58ch] text-sm leading-relaxed text-muted-foreground">
          Long-running stories, tracked continuously. Every development is scored
          for market impact and dated, and new coverage joins automatically —
          there is nothing to re-run and nothing to go stale.
        </p>
      </header>

      <Suspense fallback={<TrackersSkeleton />}>
        <Trackers />
      </Suspense>

      <p className="mt-12 border-t border-border/60 pt-6 text-sm text-muted-foreground">
        Want the per-ticker view instead?{" "}
        <Link
          href="/quote"
          className="underline decoration-amber-500/50 underline-offset-4 transition-colors hover:text-foreground hover:decoration-amber-500"
        >
          Browse quotes
        </Link>{" "}
        or read the{" "}
        <Link
          href="/articles"
          className="underline decoration-amber-500/50 underline-offset-4 transition-colors hover:text-foreground hover:decoration-amber-500"
        >
          scored article feed
        </Link>
        .
      </p>
    </main>
  );
}
