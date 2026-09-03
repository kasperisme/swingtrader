import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { ArrowLeft, ArrowUpRight } from "lucide-react";
import { CavemanContent } from "@/components/caveman-content";
import { isSanityConfigured, sanityFetch } from "@/lib/sanity/client";
import { traderBySlugQuery, traderSlugListQuery } from "@/lib/sanity/queries";
import type { Trader } from "@/lib/sanity/types";
import { getAgent } from "@/app/actions/arena";
import { SITE_URL } from "@/lib/site";

type Props = { params: Promise<{ slug: string }> };

export async function generateStaticParams() {
  // Cache Components requires at least one static param.
  const fallback = [{ slug: "warren-buffett" }];
  if (!isSanityConfigured) return fallback;
  const rows = await sanityFetch<{ slug: string }[]>(traderSlugListQuery);
  const params = rows.map((r) => ({ slug: r.slug }));
  return params.length > 0 ? params : fallback;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const trader = isSanityConfigured
    ? await sanityFetch<Trader | null>(traderBySlugQuery, { slug })
    : null;
  if (!trader) return { title: "Trader not found" };
  return {
    title: trader.name,
    description: trader.summary?.trim() || trader.knownFor || undefined,
    alternates: { canonical: `${SITE_URL}/traders/${slug}` },
    openGraph: {
      type: "profile",
      url: `${SITE_URL}/traders/${slug}`,
      title: trader.name,
      description: trader.summary?.trim() || trader.knownFor || undefined,
    },
  };
}

/**
 * The link out to the Arena.
 *
 * Only rendered when the agent actually exists and is published — the slug on
 * the Sanity document is editorial, so it can drift, and a confident link to a
 * 404 is worse than no link.
 */
async function ArenaCounterpart({ agentSlug }: { agentSlug: string }) {
  const agent = await getAgent(agentSlug);
  if (!agent) return null;

  return (
    <aside className="mt-10 rounded-lg border border-amber-500/30 bg-amber-500/5 p-5">
      <p className="font-mono text-[11px] uppercase tracking-widest text-amber-700 dark:text-amber-500">
        Running in the Arena
      </p>
      <Link
        href={`/arena/${agent.slug}`}
        className="mt-2 inline-flex items-baseline gap-1.5 text-lg font-semibold tracking-tight transition-colors hover:text-amber-600 dark:hover:text-amber-500"
      >
        {agent.name}
        <ArrowUpRight className="h-4 w-4 shrink-0 opacity-60" aria-hidden />
      </Link>
      {agent.tagline && (
        <p className="mt-1 max-w-[62ch] text-sm leading-relaxed text-muted-foreground">
          {agent.tagline}
        </p>
      )}
      <p className="mt-2.5 max-w-[62ch] text-sm leading-relaxed text-muted-foreground">
        An AI agent running this approach against a live $100,000 paper account,
        deciding once a day and publishing every trade and every reason.
      </p>
    </aside>
  );
}

async function TraderDetail({ params }: Props) {
  const { slug } = await params;
  const trader = isSanityConfigured
    ? await sanityFetch<Trader | null>(traderBySlugQuery, { slug })
    : null;
  if (!trader) notFound();

  return (
    <main className="mx-auto max-w-3xl px-4 py-12 sm:py-16">
      <Link
        href="/traders"
        className="inline-flex items-center gap-1.5 font-mono text-[11px] uppercase tracking-widest text-muted-foreground transition-colors hover:text-foreground"
      >
        <ArrowLeft className="h-3.5 w-3.5" aria-hidden />
        Famous traders
      </Link>

      <header className="mt-6">
        <div className="flex flex-wrap items-baseline gap-x-3 font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
          {trader.style && <span>{trader.style}</span>}
          {trader.lifespan && <span className="tabular-nums">{trader.lifespan}</span>}
          {trader.nationality && <span>{trader.nationality}</span>}
        </div>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight sm:text-4xl">
          {trader.name}
        </h1>
        {trader.knownFor && (
          <p className="mt-2 text-base text-muted-foreground">{trader.knownFor}</p>
        )}
      </header>

      {trader.arenaAgentSlug && (
        <Suspense fallback={null}>
          <ArenaCounterpart agentSlug={trader.arenaAgentSlug} />
        </Suspense>
      )}

      {trader.summary && (
        <p className="mt-10 text-lg leading-relaxed">{trader.summary}</p>
      )}

      {/* space-y-5 is what actually separates the paragraphs: this project has
          no typography plugin, so `prose` on its own does nothing. Matches the
          blog article layout. */}
      {trader.body && trader.body.length > 0 && (
        <div className="prose-custom mt-8 space-y-5">
          <CavemanContent body={trader.body} cavemanBody={trader.cavemanBody} />
        </div>
      )}

      {trader.keyIdeas && trader.keyIdeas.length > 0 && (
        <section className="mt-12">
          <h2 className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
            The ideas that survived
          </h2>
          <dl className="mt-5 grid gap-px overflow-hidden rounded-lg border bg-border">
            {trader.keyIdeas.map((idea, i) => (
              <div key={i} className="bg-background p-4">
                <dt className="font-medium">{idea.title}</dt>
                {idea.text && (
                  <dd className="mt-1 max-w-[68ch] text-sm leading-relaxed text-muted-foreground">
                    {idea.text}
                  </dd>
                )}
              </div>
            ))}
          </dl>
        </section>
      )}

      {trader.books && trader.books.length > 0 && (
        <section className="mt-12">
          <h2 className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
            Books
          </h2>
          <ul className="mt-4 grid gap-1.5">
            {trader.books.map((b, i) => (
              <li key={i} className="flex items-baseline gap-2 text-sm">
                <span className="font-medium">{b.title}</span>
                {b.year && (
                  <span className="font-mono text-xs tabular-nums text-muted-foreground">
                    {b.year}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      {trader.links && trader.links.length > 0 && (
        <section className="mt-12">
          <h2 className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
            Elsewhere
          </h2>
          <ul className="mt-4 flex flex-wrap gap-2">
            {trader.links.map((l, i) =>
              l.url ? (
                <li key={i}>
                  <a
                    href={l.url}
                    target="_blank"
                    rel="noopener noreferrer nofollow"
                    className="inline-flex items-center gap-1.5 rounded-full border px-3 py-1 font-mono text-[11px] text-muted-foreground transition-colors hover:border-foreground/30 hover:text-foreground"
                  >
                    {l.label || new URL(l.url).hostname}
                    <ArrowUpRight className="h-3 w-3 opacity-60" aria-hidden />
                  </a>
                </li>
              ) : null,
            )}
          </ul>
        </section>
      )}

      <p className="mt-14 max-w-[68ch] text-xs leading-relaxed text-muted-foreground">
        Biographical reference only. Nothing here is investment advice, and no
        affiliation with or endorsement by the people profiled is implied.
      </p>
    </main>
  );
}

export default function TraderPage(props: Props) {
  return (
    <Suspense
      fallback={
        <main className="mx-auto max-w-3xl px-4 py-12 sm:py-16">
          <div className="h-8 w-56 animate-pulse rounded bg-muted" />
          <div className="mt-6 h-40 animate-pulse rounded bg-muted" />
        </main>
      }
    >
      <TraderDetail {...props} />
    </Suspense>
  );
}
