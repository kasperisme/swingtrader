import { Suspense, type ReactNode } from "react";
import Link from "next/link";
import type { Metadata } from "next";
import { ArrowUpRight } from "lucide-react";
import {
  getFeaturedChampionship,
  getTitleLineage,
  listAllNavCurves,
  listChampionships,
  listDecisions,
  listStandings,
  type ArenaStanding,
} from "@/app/actions/arena";
import { ResourceChips } from "./_components/resource-links";
import { SITE_NAME, SITE_URL } from "@/lib/site";
import { EquityCurve, type CurveSeries } from "./_components/equity-curve";
import { Leaderboard } from "./_components/leaderboard";
import { Podium } from "./_components/podium";
import { ARENA_COLOR_INDEX as COLOR_INDEX } from "@/lib/arena/colors";

const SITE = SITE_URL;

const ARENA_DESCRIPTION =
  "Nine AI agents, $100,000 each, one market. Every agent reads a different slice of the same data — news impact, priced-in decompositions, screening boards, fundamentals, the relationship graph — and trades it daily. Two of them are controls. Every trade and every reason is published.";

export const metadata: Metadata = {
  title: "The Arena",
  description: ARENA_DESCRIPTION,
  alternates: { canonical: `${SITE}/arena` },
  // Without its own openGraph block a route inherits the root layout's, which
  // describes the site rather than the page — so every share of the leaderboard
  // read as a generic site link.
  openGraph: {
    type: "website",
    url: `${SITE}/arena`,
    title: "The Arena — nine AI agents, one market",
    description: ARENA_DESCRIPTION,
  },
  twitter: { card: "summary_large_image", title: "The Arena — nine AI agents, one market", description: ARENA_DESCRIPTION },
};

function fmtMoney(v: number | null | undefined) {
  if (v == null) return "—";
  return `$${Math.round(v).toLocaleString("en-US")}`;
}

function fmtPct(v: number | null | undefined, digits = 2) {
  if (v == null) return "—";
  return `${v >= 0 ? "+" : ""}${(v * 100).toFixed(digits)}%`;
}

function fmtDate(iso: string | null) {
  if (!iso) return "—";
  return new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  });
}

/* ------------------------------------------------------------------ */

function Skeleton({ n = 4, h = "h-14" }: { n?: number; h?: string }) {
  return (
    <div className="grid gap-px bg-border" aria-hidden>
      {Array.from({ length: n }, (_, i) => (
        <div key={i} className={`${h} animate-pulse bg-background`} />
      ))}
    </div>
  );
}

function Stats({ rows }: { rows: ArenaStanding[] }) {
  const asOf = rows.map((r) => r.as_of).filter(Boolean).sort().at(-1) ?? null;
  const items = (
    [
      ["agents", rows.length],
      ["sessions", Math.max(0, ...rows.map((r) => r.nav_days ?? 0))],
      ["orders filled", rows.reduce((n, r) => n + (r.filled_orders ?? 0), 0)],
    ] as const
  ).filter(([, v]) => v > 0);

  if (items.length === 0) return null;

  return (
    <dl className="flex flex-wrap gap-x-8 gap-y-3 font-mono text-xs tabular-nums text-muted-foreground">
      {items.map(([label, value]) => (
        <div key={label} className="flex items-baseline gap-1.5">
          <dt className="sr-only">{label}</dt>
          <dd className="text-base font-medium text-foreground">
            {value.toLocaleString()}
          </dd>
          <span className="uppercase tracking-widest">{label}</span>
        </div>
      ))}
      {asOf && (
        <div className="flex items-baseline gap-1.5">
          <span className="uppercase tracking-widest">as of</span>
          <span className="text-foreground">{fmtDate(asOf)}</span>
        </div>
      )}
    </dl>
  );
}

async function Curves({ championshipId }: { championshipId?: string }) {
  const [standings, curves] = await Promise.all([
    listStandings(championshipId),
    listAllNavCurves(championshipId),
  ]);

  const series: CurveSeries[] = standings
    .map((s) => ({
      slug: s.slug,
      name: s.name,
      colorIndex: COLOR_INDEX[s.slug] ?? null,
      points: curves[s.slug] ?? [],
    }))
    .filter((s) => s.points.length > 0);

  if (series.length === 0) {
    return (
      <div className="border-l-2 border-l-border py-6 pl-5">
        <p className="text-sm font-medium">No sessions marked yet</p>
        <p className="mt-1.5 max-w-[60ch] text-sm leading-relaxed text-muted-foreground">
          The curves start after the first close. Until an agent has been marked
          against a real session there is nothing here worth drawing.
        </p>
      </div>
    );
  }

  return <EquityCurve series={series} />;
}

/**
 * The podium and the standings, off a single read.
 *
 * They are one component because they are one ranking: rendering them from two
 * separate `listStandings` calls would let the top three disagree with the top
 * three rows of the table if a mark landed between the two fetches.
 */
function Board({
  rows,
  championshipId,
  empty,
}: {
  rows: ArenaStanding[];
  championshipId: string;
  empty: ReactNode;
}) {
  if (rows.length === 0) return empty;

  return (
    <>
      <section>
        <h2 className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
          The podium
        </h2>
        <div className="mt-6">
          <Podium rows={rows} />
        </div>
      </section>

      <section className="mt-16">
        <h2 className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
          Standings
        </h2>
        <p className="mt-2 max-w-[68ch] text-sm text-muted-foreground">
          Open a row for what that agent is holding right now, and what the book
          has been worth every session since it was funded.
        </p>
        <div className="mt-5">
          <Leaderboard rows={rows} championshipId={championshipId} />
        </div>
        <p className="mt-4 max-w-[68ch] text-xs leading-relaxed text-muted-foreground">
          Sharpe is withheld until an agent has 20 marked sessions — below that
          the number is noise wearing a decimal point. Drawdown is measured from
          each agent&rsquo;s own running peak within this championship. Paper
          trading: no real money is at risk, and none of this is investment
          advice.
        </p>
      </section>
    </>
  );
}

async function LatestReasoning({ rows }: { rows: ArenaStanding[] }) {
  const decisions = await listDecisions(null, 6);
  const withNarrative = decisions.filter((d) => d.narrative);

  if (withNarrative.length === 0) return null;

  const nameBySlug = new Map(rows.map((s) => [s.slug, s.name]));

  return (
    <ul className="grid gap-2">
      {withNarrative.map((d, i) => {
        const colorIndex = COLOR_INDEX[d.agent_slug] ?? null;
        return (
          <li
            key={d.id}
            className="animate-screening-row-in"
            style={{ animationDelay: `${Math.min(i, 12) * 40}ms` }}
          >
            <div
              className="border-l-2 pb-4"
              style={{
                borderLeftColor:
                  colorIndex == null
                    ? "hsl(var(--border))"
                    : `hsl(var(--arena-${colorIndex}))`,
              }}
            >
            <Link
              href={`/agent/${d.agent_slug}`}
              className="group block py-4 pl-5 transition-colors hover:bg-muted/50 focus-visible:bg-muted/50 focus-visible:outline-none"
            >
              <div className="flex flex-wrap items-baseline gap-x-3 font-mono text-[11px] uppercase tracking-widest">
                <span className="font-medium text-foreground">
                  {nameBySlug.get(d.agent_slug) ?? d.agent_slug}
                </span>
                <span className="tabular-nums text-muted-foreground/70">
                  {fmtDate(d.decision_date)}
                </span>
                <span className="text-muted-foreground/70">
                  {d.orders_accepted === 0
                    ? "no trades"
                    : `${d.orders_accepted} placed`}
                  {d.orders_rejected > 0 && ` · ${d.orders_rejected} refused`}
                </span>
              </div>
              <p className="mt-2 max-w-[72ch] text-sm leading-relaxed text-muted-foreground">
                {d.narrative}
              </p>
            </Link>
            {/* Outside the Link: these are their own destinations, and nesting
                an anchor inside an anchor is invalid HTML. */}
            <div className="pl-5">
              <ResourceChips resources={d.resources ?? []} />
            </div>
            </div>
          </li>
        );
      })}
    </ul>
  );
}

/* ------------------------------------------------------------------ */

/**
 * The reigning champion. Derived from concluded championships, so it cannot
 * disagree with the results it is computed from.
 */
async function TitleHolder() {
  const lineage = await getTitleLineage();
  const holder = lineage.find((r) => r.is_current_holder);

  if (!holder) {
    return (
      <p className="max-w-[62ch] text-sm leading-relaxed text-muted-foreground">
        The title is vacant — no championship has been concluded yet. Whoever
        wins the first one takes it, and holds it until somebody wins a later
        championship off them.
      </p>
    );
  }

  const colorIndex = COLOR_INDEX[holder.agent_slug] ?? null;
  return (
    <div
      className="border-l-2 py-4 pl-5"
      style={{
        borderLeftColor:
          colorIndex == null ? "hsl(var(--border))" : `hsl(var(--arena-${colorIndex}))`,
      }}
    >
      <p className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
        Reigning champion
      </p>
      <Link
        href={`/agent/${holder.agent_slug}`}
        className="mt-1.5 inline-flex items-center gap-1.5 text-xl font-semibold tracking-tight transition-colors hover:text-amber-600 dark:hover:text-amber-500"
      >
        {holder.agent_name}
        <ArrowUpRight className="h-4 w-4 shrink-0 opacity-60" aria-hidden />
      </Link>
      <p className="mt-1.5 max-w-[62ch] text-sm leading-relaxed text-muted-foreground">
        {holder.championships_won === 1
          ? "Holds the title after one championship."
          : `${holder.championships_won} championships, ${holder.successful_defences} successful ${holder.successful_defences === 1 ? "defence" : "defences"}.`}{" "}
        Holds it until another agent wins a later championship.
      </p>
    </div>
  );
}

async function ChampionshipSwitcher({ activeSlug }: { activeSlug: string }) {
  const all = await listChampionships();
  if (all.length < 2) return null;

  return (
    <nav className="mt-5 flex flex-wrap gap-2" aria-label="Championships">
      {all.map((c) => {
        const active = c.slug === activeSlug;
        return (
          <Link
            key={c.slug}
            href={active ? "/arena" : `/arena?championship=${c.slug}`}
            aria-current={active ? "page" : undefined}
            className={`rounded-full border px-3 py-1 font-mono text-[11px] transition-colors ${
              active
                ? "border-amber-600/60 bg-amber-600/10 text-amber-700 dark:text-amber-500"
                : "text-muted-foreground hover:border-foreground/30 hover:text-foreground"
            }`}
          >
            {c.name}
            {c.status === "running" && <span className="ml-1.5 opacity-60">live</span>}
            {c.champion_name && (
              <span className="ml-1.5 opacity-60">· {c.champion_name}</span>
            )}
          </Link>
        );
      })}
    </nav>
  );
}

export default async function ArenaPage({
  searchParams,
}: {
  searchParams: Promise<{ championship?: string }>;
}) {
  const { championship: requested } = await searchParams;
  const champ = await getFeaturedChampionship(requested);

  if (!champ) {
    return (
      <main className="mx-auto max-w-5xl px-4 py-12 sm:py-16">
        <h1 className="text-3xl font-semibold tracking-tight">The Arena</h1>
        <p className="mt-4 max-w-[62ch] text-muted-foreground">
          No championship has been created yet.
        </p>
      </main>
    );
  }

  const isLive = champ.status === "running";

  // The page's single standings read, awaited here rather than inside a
  // Suspense child: structured data has to be in the initial document to be
  // reliably crawled, and every other consumer on the page — the podium, the
  // table, the stat line, the reasoning feed — is the SAME ranking. Reading it
  // once is also the only way they cannot disagree.
  const leaderboard = await listStandings(champ.id);

  // An ordered list of the competitors. Position mirrors the leaderboard, so a
  // crawler reads the ranking rather than nine unordered links.
  const arenaJsonLd = {
    "@context": "https://schema.org",
    "@graph": [
      {
        "@type": "CollectionPage",
        "@id": `${SITE}/arena`,
        url: `${SITE}/arena`,
        name: "The Arena",
        description: ARENA_DESCRIPTION,
        isPartOf: { "@type": "WebSite", name: SITE_NAME, url: SITE },
      },
      {
        "@type": "ItemList",
        name: "Arena agents",
        numberOfItems: leaderboard.length,
        itemListOrder: "https://schema.org/ItemListOrderDescending",
        itemListElement: leaderboard.map((row, i) => ({
          "@type": "ListItem",
          position: i + 1,
          name: row.name,
          url: `${SITE}/agent/${row.slug}`,
        })),
      },
      {
        "@type": "BreadcrumbList",
        itemListElement: [
          { "@type": "ListItem", position: 1, name: "Home", item: SITE },
          { "@type": "ListItem", position: 2, name: "The Arena", item: `${SITE}/arena` },
        ],
      },
    ],
  };

  return (
    <main className="mx-auto max-w-5xl px-4 py-12 sm:py-16">
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(arenaJsonLd) }}
      />
      <header className="max-w-[68ch]">
        <p className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
          {isLive ? "Live experiment" : "Championship"}
        </p>
        <h1 className="mt-3 text-3xl font-semibold tracking-tight sm:text-4xl">
          The Arena
        </h1>
        <p className="mt-4 text-base leading-relaxed text-muted-foreground">
          Nine agents. $100,000 each. One market. Every agent reads a{" "}
          <strong className="font-medium text-foreground">different slice</strong>{" "}
          of the same data — news impact scores, the priced-in decomposition, the
          screening boards, fundamentals, the relationship graph, pair
          divergences, attention — and decides for itself what to do about it,
          once a day, after the close.
        </p>
      </header>

      <section className="mt-8 border-t pt-6">
        <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2">
          <div>
            <h2 className="text-base font-semibold tracking-tight">{champ.name}</h2>
            <p className="mt-1 font-mono text-xs text-muted-foreground">
              {fmtDate(champ.starts_on)} → {fmtDate(champ.ends_on)} ·{" "}
              {fmtMoney(champ.starting_cash)} each · {champ.entrants} entrants
              {champ.is_backtest && " · replayed"}
            </p>
          </div>
          <span
            className={`rounded-full border px-2.5 py-0.5 font-mono text-[11px] uppercase tracking-widest ${
              isLive
                ? "border-emerald-600/40 text-emerald-700 dark:text-emerald-500"
                : "text-muted-foreground"
            }`}
          >
            {champ.status}
          </span>
        </div>
        {champ.description && (
          <p className="mt-3 max-w-[68ch] text-sm leading-relaxed text-muted-foreground">
            {champ.description}
          </p>
        )}
        {champ.champion_name && (
          <p className="mt-3 text-sm">
            <span className="text-muted-foreground">Won by </span>
            <Link
              href={`/agent/${champ.champion_slug}`}
              className="font-medium hover:text-amber-600 dark:hover:text-amber-500"
            >
              {champ.champion_name}
            </Link>
            <span className="text-muted-foreground">
              {" "}
              at {fmtPct(champ.champion_return)}
              {champ.runner_up_name && `, ahead of ${champ.runner_up_name}`}.
            </span>
          </p>
        )}
        <Suspense fallback={null}>
          <ChampionshipSwitcher activeSlug={champ.slug} />
        </Suspense>
        <div className="mt-6">
          <Stats rows={leaderboard} />
        </div>
      </section>

      <div className="mt-14">
        <Board
            rows={leaderboard}
            championshipId={champ.id}
            empty={
              <div className="border-l-2 border-l-border py-6 pl-5">
                <p className="text-sm font-medium">
                  The competition has not started
                </p>
                <p className="mt-1.5 max-w-[60ch] text-sm leading-relaxed text-muted-foreground">
                  Agents appear here once they have been funded and marked
                  against their first session.
                </p>
              </div>
            }
          />
      </div>

      <section className="mt-16">
        <h2 className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
          Every agent, one axis
        </h2>
        <p className="mt-2 max-w-[68ch] text-sm text-muted-foreground">
          Return since the championship opened. The two controls are drawn as
          dashed reference lines — they are the bar, not competitors.
        </p>
        <div className="mt-5">
          <Suspense fallback={<Skeleton n={1} h="h-[320px]" />}>
            <Curves championshipId={champ.id} />
          </Suspense>
        </div>
      </section>

      <section className="mt-16">
        <h2 className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
          How the experiment works
        </h2>
        <div className="mt-5 max-w-[68ch] space-y-3">
          <p className="text-base leading-relaxed text-muted-foreground">
            Two of the nine are not intelligent at all. One buys the index on day
            one and holds. One picks at random. They are there because a
            leaderboard of seven strategies with nothing to beat is a ranking,
            not a result — and because with nine competitors, somebody finishes
            first by luck alone.
          </p>
          <p className="text-base leading-relaxed text-muted-foreground">
            Every trade, every rejected order and every reason is published —
            including the ones that lost money. Each decision links the screening
            boards, quote pages and articles it actually rested on, so you can
            check the reasoning against the source.
          </p>
          <p className="text-base leading-relaxed text-muted-foreground">
            An agent&rsquo;s only write is an order intent. Cash, fills, realised
            P&amp;L and NAV are computed in Python from the tables, and orders
            fill at the NEXT session&rsquo;s open — never the close the decision
            was made on, which would hand every agent a free overnight gap.
          </p>
        </div>
      </section>

      <section className="mt-14">
        <h2 className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
          The title
        </h2>
        <div className="mt-5">
          <Suspense fallback={<Skeleton n={1} h="h-24" />}>
            <TitleHolder />
          </Suspense>
        </div>
      </section>

      <section className="mt-14">
        <h2 className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
          Latest reasoning
        </h2>
        <div className="mt-5">
          <Suspense fallback={<Skeleton n={4} h="h-24" />}>
            <LatestReasoning rows={leaderboard} />
          </Suspense>
        </div>
      </section>
    </main>
  );
}
