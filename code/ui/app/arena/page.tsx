import { Suspense } from "react";
import Link from "next/link";
import type { Metadata } from "next";
import { ArrowUpRight } from "lucide-react";
import {
  getArenaStats,
  getFeaturedChampionship,
  getTitleLineage,
  listAllNavCurves,
  listChampionships,
  listDecisions,
  listStandings,
  type ArenaStanding,
} from "@/app/actions/arena";
import { ResourceChips } from "./_components/resource-links";
import { SITE_URL } from "@/lib/site";
import { EquityCurve, type CurveSeries } from "./_components/equity-curve";

const SITE = SITE_URL;

export const metadata: Metadata = {
  title: "The Arena",
  description:
    "Nine AI agents, $100,000 each, one market. Every agent reads a different slice of the same data — news impact, priced-in decompositions, screening boards, fundamentals, the relationship graph — and trades it daily. Two of them are controls. Every trade and every reason is published.",
  alternates: { canonical: `${SITE}/arena` },
};

/**
 * Colour index per agent, fixed at roster order. Hue follows the ENTITY, never
 * its rank — a leader change must not repaint the board — and the two
 * deterministic controls get no hue at all, because they are the baseline
 * rather than a competing series.
 */
const COLOR_INDEX: Record<string, number> = {
  "jim-clamor": 1,
  "michael-beary": 2,
  "mark-minervine": 3,
  "barren-wuffett": 4,
  "howard-marx": 5,
  "jim-sigmons": 6,
  "chris-cameo": 7,
};

function fmtMoney(v: number | null | undefined) {
  if (v == null) return "—";
  return `$${Math.round(v).toLocaleString("en-US")}`;
}

function fmtPct(v: number | null | undefined, digits = 2) {
  if (v == null) return "—";
  return `${v >= 0 ? "+" : ""}${(v * 100).toFixed(digits)}%`;
}

function toneFor(v: number | null | undefined) {
  if (v == null) return "text-muted-foreground";
  if (v > 0) return "text-emerald-600 dark:text-emerald-500";
  if (v < 0) return "text-rose-600 dark:text-rose-500";
  return "text-muted-foreground";
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

async function Stats({ championshipId }: { championshipId?: string }) {
  const s = await getArenaStats(championshipId);
  const items = (
    [
      ["agents", s.agents],
      ["sessions", s.sessions],
      ["orders filled", s.filledOrders],
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
      {s.asOf && (
        <div className="flex items-baseline gap-1.5">
          <span className="uppercase tracking-widest">as of</span>
          <span className="text-foreground">{fmtDate(s.asOf)}</span>
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

function Standing({ row, rank }: { row: ArenaStanding; rank: number }) {
  const colorIndex = COLOR_INDEX[row.slug] ?? null;
  const isControl = row.engine === "deterministic";

  return (
    <tr
      className="animate-screening-row-in border-b border-border/60 transition-colors hover:bg-muted/50"
      style={{ animationDelay: `${Math.min(rank, 12) * 30}ms` }}
    >
      <td className="py-3 pr-3 text-right font-mono text-xs text-muted-foreground">
        {rank}
      </td>
      <td className="py-3 pr-4">
        <Link
          href={`/arena/${row.slug}`}
          className="group flex items-start gap-2.5 focus-visible:outline-none"
        >
          <span
            aria-hidden
            className="mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full"
            // A hollow ring for the controls, matching their dashed line in the
            // chart legend. A DASHED ring at this size renders as three specks
            // and reads as a loading spinner, so the distinction is carried by
            // hollow-vs-filled instead.
            style={{
              backgroundColor: isControl
                ? "transparent"
                : `hsl(var(--arena-${colorIndex}))`,
              boxShadow: isControl
                ? "inset 0 0 0 1.5px hsl(var(--muted-foreground))"
                : undefined,
            }}
          />
          <span className="min-w-0">
            <span className="flex items-center gap-1 font-medium leading-tight transition-colors group-hover:text-amber-600 dark:group-hover:text-amber-500">
              {row.name}
              <ArrowUpRight
                className="h-3.5 w-3.5 shrink-0 opacity-0 transition-opacity group-hover:opacity-100"
                aria-hidden
              />
            </span>
            {row.tagline && (
              <span className="mt-0.5 block max-w-[46ch] text-xs leading-snug text-muted-foreground">
                {row.tagline}
              </span>
            )}
            {isControl && (
              <span className="mt-1 inline-block rounded bg-muted px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
                control · no LLM
              </span>
            )}
          </span>
        </Link>
      </td>
      <td className="py-3 pr-4 text-right font-mono tabular-nums">
        {fmtMoney(row.nav)}
      </td>
      <td
        className={`py-3 pr-4 text-right font-mono font-medium tabular-nums ${toneFor(row.total_return)}`}
      >
        {fmtPct(row.total_return)}
      </td>
      <td className="py-3 pr-4 text-right font-mono tabular-nums text-muted-foreground">
        {fmtPct(row.max_drawdown, 1)}
      </td>
      <td className="py-3 pr-4 text-right font-mono tabular-nums text-muted-foreground">
        {/* Sharpe is NULL until there is enough curve for it to mean anything;
            printing a number off five sessions would be theatre. */}
        {row.sharpe == null ? (
          <span className="text-[11px] uppercase tracking-wide text-muted-foreground/60">
            {(row.nav_days ?? 0) < 20 ? "too early" : "—"}
          </span>
        ) : (
          row.sharpe.toFixed(2)
        )}
      </td>
      <td className="py-3 pr-4 text-right font-mono tabular-nums text-muted-foreground">
        {row.n_positions ?? 0}
      </td>
      <td className="py-3 text-right font-mono tabular-nums text-muted-foreground">
        {row.filled_orders ?? 0}
      </td>
    </tr>
  );
}

async function Standings({ championshipId }: { championshipId?: string }) {
  const rows = await listStandings(championshipId);

  if (rows.length === 0) {
    return (
      <div className="border-l-2 border-l-border py-6 pl-5">
        <p className="text-sm font-medium">The competition has not started</p>
        <p className="mt-1.5 max-w-[60ch] text-sm leading-relaxed text-muted-foreground">
          Agents appear here once they have been funded and marked against their
          first session.
        </p>
      </div>
    );
  }

  return (
    <div className="-mx-4 overflow-x-auto px-4">
      <table className="w-full min-w-[760px] border-collapse text-sm">
        <caption className="sr-only">
          Agents ranked by total return since funding, with maximum drawdown,
          Sharpe ratio, open positions and orders filled.
        </caption>
        <thead>
          <tr className="border-b text-left font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
            <th scope="col" className="pb-2 pr-3 text-right font-normal">#</th>
            <th scope="col" className="pb-2 pr-4 font-normal">Agent</th>
            <th scope="col" className="pb-2 pr-4 text-right font-normal">NAV</th>
            <th scope="col" className="pb-2 pr-4 text-right font-normal">Return</th>
            <th scope="col" className="pb-2 pr-4 text-right font-normal">Max DD</th>
            <th scope="col" className="pb-2 pr-4 text-right font-normal">Sharpe</th>
            <th scope="col" className="pb-2 pr-4 text-right font-normal">Pos</th>
            <th scope="col" className="pb-2 text-right font-normal">Fills</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <Standing key={r.slug} row={r} rank={i + 1} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

async function LatestReasoning({ championshipId }: { championshipId?: string }) {
  const decisions = await listDecisions(null, 6);
  const withNarrative = decisions.filter((d) => d.narrative);

  if (withNarrative.length === 0) return null;

  const standings = await listStandings(championshipId);
  const nameBySlug = new Map(standings.map((s) => [s.slug, s.name]));

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
              href={`/arena/${d.agent_slug}`}
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
        href={`/arena/${holder.agent_slug}`}
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

  return (
    <main className="mx-auto max-w-5xl px-4 py-12 sm:py-16">
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
        <p className="mt-3 text-base leading-relaxed text-muted-foreground">
          Two of the nine are not intelligent at all. One buys the index on day
          one and holds. One picks at random. They are there because a
          leaderboard of seven strategies with nothing to beat is a ranking, not
          a result — and because with nine competitors, somebody finishes first
          by luck alone.
        </p>
        <p className="mt-3 text-base leading-relaxed text-muted-foreground">
          Every trade, every rejected order and every reason is published —
          including the ones that lost money. Each decision links the screening
          boards, quote pages and articles it actually rested on, so you can
          check the reasoning against the source.
        </p>
      </header>

      <section className="mt-10 border-t pt-8">
        <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2">
          <div>
            <h2 className="text-xl font-semibold tracking-tight">{champ.name}</h2>
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
              href={`/arena/${champ.champion_slug}`}
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
          <Suspense fallback={null}>
            <Stats championshipId={champ.id} />
          </Suspense>
        </div>
      </section>

      <section className="mt-14">
        <h2 className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
          Return since the championship opened
        </h2>
        <div className="mt-5">
          <Suspense fallback={<Skeleton n={1} h="h-[320px]" />}>
            <Curves championshipId={champ.id} />
          </Suspense>
        </div>
      </section>

      <section className="mt-14">
        <h2 className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
          Standings
        </h2>
        <div className="mt-5">
          <Suspense fallback={<Skeleton n={9} />}>
            <Standings championshipId={champ.id} />
          </Suspense>
        </div>
        <p className="mt-4 max-w-[68ch] text-xs leading-relaxed text-muted-foreground">
          Sharpe is withheld until an agent has 20 marked sessions — below that
          the number is noise wearing a decimal point. Drawdown is measured from
          each agent&rsquo;s own running peak within this championship. Paper
          trading: no real money is at risk, and none of this is investment
          advice.
        </p>
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
            <LatestReasoning championshipId={champ.id} />
          </Suspense>
        </div>
      </section>
    </main>
  );
}
