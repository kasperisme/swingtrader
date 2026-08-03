import Link from "next/link";
import type { Metadata } from "next";
import { getTopicStats, listTopics } from "@/app/actions/topics";

// Must match the root layout's metadataBase host exactly. The site canonicalises
// on WWW; emitting a bare-host canonical here would split ranking signals
// between two hosts for these pages alone.
const SITE = (process.env.NEXT_PUBLIC_SITE_URL ?? "https://www.newsimpactscreener.com").replace(/\/$/, "");

export const metadata: Metadata = {
  title: "Topics",   // root layout template supplies the site suffix
  description:
    "Live trackers for the stories that keep moving markets — every development scored for market impact, updated as news lands.",
  alternates: { canonical: `${SITE}/topics` },
};

export default async function TopicsIndex() {
  const topics = await listTopics();
  const stats = await Promise.all(topics.map((t) => getTopicStats(t.slug)));

  return (
    <main className="mx-auto w-full max-w-4xl px-4 py-10 sm:px-6">
      <header className="mb-10">
        <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">Topics</h1>
        <p className="mt-3 text-lg text-muted-foreground">
          Long-running stories, tracked continuously. Every development is scored for
          market impact and dated, and new coverage joins automatically.
        </p>
      </header>

      <ul className="grid gap-4 sm:grid-cols-2">
        {topics.map((t, i) => (
          <li key={t.slug}>
            <Link
              href={`/topics/${t.slug}`}
              className="group block h-full rounded-lg border p-5 transition-colors hover:bg-accent/50"
            >
              <h2 className="text-lg font-semibold leading-snug group-hover:underline">
                {t.title}
              </h2>
              {t.subtitle && (
                <p className="mt-1.5 text-sm text-muted-foreground">{t.subtitle}</p>
              )}
              <p className="mt-4 font-mono text-xs text-muted-foreground tabular-nums">
                {stats[i].articleCount.toLocaleString()} stories ·{" "}
                {stats[i].claimCount.toLocaleString()} scored claims
              </p>
              <div className="mt-3 flex flex-wrap gap-1">
                {t.lens_tickers.slice(0, 6).map((s) => (
                  <span key={s} className="rounded border px-1.5 py-0.5 font-mono text-xs">
                    ${s}
                  </span>
                ))}
              </div>
            </Link>
          </li>
        ))}
      </ul>
    </main>
  );
}
