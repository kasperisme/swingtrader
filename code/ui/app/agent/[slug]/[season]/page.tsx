import Link from "next/link";
import { notFound } from "next/navigation";
import type { Metadata } from "next";
import { ArrowLeft, Trophy } from "lucide-react";
import {
  getAgent,
  getAgentAppearance,
  listAgentAppearances,
  listNavCurve,
  listPositions,
  listStandings,
  type ArenaSession,
} from "@/app/actions/arena";
import { SITE_NAME, SITE_URL } from "@/lib/site";
import { EquityCurve } from "@/app/arena/_components/equity-curve";
import { PortfolioPanel } from "@/app/arena/_components/portfolio-panel";
import { ResourceChips } from "@/app/arena/_components/resource-links";
import { ARENA_COLOR_INDEX as COLOR_INDEX } from "@/lib/arena/colors";
import { StatGrid, type Stat } from "../../_components/stat-grid";
import { OrderLine } from "../../_components/order-line";
import {
  fmtDate,
  fmtMoney,
  fmtPct,
  fmtRate,
  fmtSignedMoney,
  toneFor,
} from "../../_components/format";

/**
 * One agent's appearance in one championship, in full.
 *
 * The profile answers "how good is this agent"; this page answers "what did it
 * actually do, and why". Its spine is the session log: each day's reasoning
 * with the orders THAT decision produced filed underneath it — joined on
 * `decision_id`, so a trade sits under the thinking that caused it rather than
 * next to it by date.
 */

// No `revalidate` and no `generateStaticParams`: this project runs with
// `cacheComponents: true`, which rejects the route-segment revalidate config,
// and the arena's numbers change every session anyway.

type Params = Promise<{ slug: string; season: string }>;

async function resolve(slug: string, seasonSlug: string) {
  const [agent, appearances] = await Promise.all([
    getAgent(slug),
    listAgentAppearances(slug),
  ]);
  const appearance =
    appearances.find((a) => a.championship_slug === seasonSlug) ?? null;
  return { agent, appearance };
}

export async function generateMetadata({
  params,
}: {
  params: Params;
}): Promise<Metadata> {
  const { slug, season } = await params;
  const { agent, appearance } = await resolve(slug, season);
  if (!agent || !appearance) return { title: "Appearance not found" };

  const url = `${SITE_URL}/agent/${slug}/${season}`;
  const title = `${agent.name} — ${appearance.championship_name}`;
  const description = `Every trade ${agent.name} made in ${appearance.championship_name}, and the reasoning behind each one. Finished at ${fmtPct(appearance.total_return)}.`;
  return {
    title,
    description,
    alternates: { canonical: url },
    openGraph: { type: "article", url, title, description },
    twitter: { card: "summary_large_image", title, description },
  };
}

/** One session: what it decided, then what that decision produced. */
function Session({
  session,
  accent,
}: {
  session: ArenaSession;
  accent: string;
}) {
  const { decision: d, orders } = session;
  const tools = Object.entries(d.tools_called ?? {}).sort((a, b) => b[1] - a[1]);

  return (
    <li className="border-l-2 pl-5" style={{ borderLeftColor: accent }}>
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
        <span className="text-sm font-medium tracking-normal text-foreground">
          {fmtDate(d.decision_date)}
        </span>
        <span>
          {d.orders_accepted === 0 ? "no trades" : `${d.orders_accepted} placed`}
          {d.orders_rejected > 0 && ` · ${d.orders_rejected} refused`}
        </span>
        {d.nav_at_decision != null && (
          <span className="tabular-nums">NAV {fmtMoney(d.nav_at_decision)}</span>
        )}
        {d.cash_at_decision != null && (
          <span className="tabular-nums">cash {fmtMoney(d.cash_at_decision)}</span>
        )}
      </div>

      {d.narrative ? (
        <p className="mt-2.5 max-w-[72ch] text-sm leading-relaxed">{d.narrative}</p>
      ) : (
        <p className="mt-2.5 text-sm text-muted-foreground">
          No reasoning published for this session.
        </p>
      )}

      <ResourceChips resources={d.resources ?? []} />

      {/* What the reasoning above actually became. Refused orders included — an
          agent's intent is part of the record even when the broker says no. */}
      {orders.length > 0 && (
        <div className="mt-3 border-t border-border/60 pt-1">
          {orders.map((o) => (
            <OrderLine key={o.id} order={o} showDate={false} />
          ))}
        </div>
      )}

      {tools.length > 0 && (
        <p className="mt-2 font-mono text-[10px] uppercase tracking-widest text-muted-foreground/60">
          {tools.map(([name, n]) => `${name}${n > 1 ? `×${n}` : ""}`).join(" · ")}
          {d.rounds_used != null && ` · ${d.rounds_used} rounds`}
        </p>
      )}
    </li>
  );
}

export default async function AgentSeasonPage({ params }: { params: Params }) {
  const { slug, season } = await params;
  const { agent, appearance } = await resolve(slug, season);
  // An agent that never entered this championship has no appearance to show,
  // and inventing an empty one would read as "it traded and did nothing".
  if (!agent || !appearance) notFound();

  const champId = appearance.championship_id;
  const [standings, curve, positions, log] = await Promise.all([
    listStandings(champId),
    listNavCurve(slug, champId),
    listPositions(slug, champId),
    getAgentAppearance(slug, champId),
  ]);

  const idx = standings.findIndex((s) => s.slug === slug);
  const rank = idx === -1 ? null : idx + 1;
  const colorIndex = COLOR_INDEX[slug] ?? null;
  const accent =
    colorIndex == null ? "hsl(var(--muted-foreground))" : `hsl(var(--arena-${colorIndex}))`;
  const isRunning = appearance.championship_status === "running";

  const stats: Stat[] = [
    {
      label: "Finish",
      value: rank == null ? "—" : String(rank),
      note: rank == null ? null : `of ${standings.length}`,
    },
    {
      label: "Return",
      value: fmtPct(appearance.total_return),
      tone: toneFor(appearance.total_return),
    },
    { label: "NAV", value: fmtMoney(appearance.nav), note: `${appearance.nav_days ?? 0} sessions` },
    { label: "Max drawdown", value: fmtPct(appearance.max_drawdown, 1) },
    {
      label: "Sharpe",
      value:
        appearance.sharpe == null
          ? (appearance.nav_days ?? 0) < 20
            ? "too early"
            : "—"
          : appearance.sharpe.toFixed(2),
    },
    {
      label: "Orders filled",
      value: String(appearance.filled_orders ?? 0),
      note: `${log.orders.length} placed in total`,
    },
    {
      label: "Win rate",
      value: appearance.win_rate == null ? "—" : fmtRate(appearance.win_rate),
      note:
        (appearance.closed_trades ?? 0) > 0
          ? `${appearance.winning_trades ?? 0} of ${appearance.closed_trades}`
          : "no closed trades",
    },
    {
      label: "Realised P&L",
      value: fmtSignedMoney(appearance.realized_pnl),
      tone: toneFor(appearance.realized_pnl),
      note:
        appearance.avg_realized_pct == null
          ? null
          : `avg ${fmtPct(appearance.avg_realized_pct)} per trade`,
    },
  ];

  const canonicalUrl = `${SITE_URL}/agent/${slug}/${season}`;
  const jsonLd = {
    "@context": "https://schema.org",
    "@graph": [
      {
        "@type": "Dataset",
        "@id": `${canonicalUrl}#record`,
        name: `${agent.name} — ${appearance.championship_name} trading log`,
        description: `Every order ${agent.name} placed in ${appearance.championship_name}, with the reasoning that produced it.`,
        url: canonicalUrl,
        temporalCoverage: `${appearance.starts_on}/${appearance.ends_on}`,
        creator: { "@type": "Organization", name: SITE_NAME, url: SITE_URL },
        isAccessibleForFree: true,
        variableMeasured: [
          { "@type": "PropertyValue", name: "Total return", value: appearance.total_return },
          { "@type": "PropertyValue", name: "Net asset value", value: appearance.nav },
          ...(rank ? [{ "@type": "PropertyValue", name: "Rank", value: rank }] : []),
        ],
      },
      {
        "@type": "BreadcrumbList",
        itemListElement: [
          { "@type": "ListItem", position: 1, name: "Home", item: SITE_URL },
          { "@type": "ListItem", position: 2, name: "The Arena", item: `${SITE_URL}/arena` },
          { "@type": "ListItem", position: 3, name: agent.name, item: `${SITE_URL}/agent/${slug}` },
          {
            "@type": "ListItem",
            position: 4,
            name: appearance.championship_name,
            item: canonicalUrl,
          },
        ],
      },
    ],
  };

  return (
    <main className="mx-auto max-w-5xl px-4 py-12 sm:py-16">
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />
      <Link
        href={`/agent/${slug}`}
        className="inline-flex items-center gap-1.5 font-mono text-[11px] uppercase tracking-widest text-muted-foreground transition-colors hover:text-foreground"
      >
        <ArrowLeft className="h-3.5 w-3.5" aria-hidden />
        {agent.name}
      </Link>

      <header className="mt-6 border-l-2 pl-5" style={{ borderLeftColor: accent }}>
        <p className="flex flex-wrap items-center gap-2 font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
          <span>Appearance</span>
          {isRunning && (
            <span className="text-emerald-600 dark:text-emerald-500">· in progress</span>
          )}
          {appearance.championship_is_backtest && <span>· replayed</span>}
          {appearance.is_champion && (
            <span className="inline-flex items-center gap-1 text-amber-600 dark:text-amber-500">
              <Trophy className="h-3 w-3" aria-hidden />
              won it
            </span>
          )}
        </p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight sm:text-4xl">
          {appearance.championship_name}
        </h1>
        <p className="mt-2 text-base text-muted-foreground">
          {agent.name}{" "}
          {rank == null
            ? "took part"
            : `${isRunning ? "sits" : "finished"} ${rank} of ${standings.length}`}
          <span className="mx-1.5 opacity-40">·</span>
          <span className="font-mono text-sm">
            {fmtDate(appearance.starts_on)} → {fmtDate(appearance.ends_on)}
          </span>
        </p>
      </header>

      <section className="mt-10">
        <StatGrid stats={stats} />
      </section>

      {curve.length > 0 && (
        <>
          <section className="mt-12">
            <h2 className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
              Return
            </h2>
            <div className="mt-5">
              <EquityCurve
                series={[{ slug, name: agent.name, colorIndex, points: curve }]}
                height={260}
              />
            </div>
          </section>

          <section className="mt-12">
            <h2 className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
              The book
            </h2>
            <p className="mt-2 max-w-[68ch] text-sm leading-relaxed text-muted-foreground">
              The account in dollars, split into holdings and cash — the return
              chart above cannot tell a flat month spent fully invested from one
              spent sitting out.{" "}
              <strong className="font-medium text-foreground">Click any point</strong>{" "}
              to see the book it was holding that day.
            </p>
            <div className="mt-5">
              <PortfolioPanel
                points={curve}
                livePositions={positions}
                startingCash={Number(appearance.starting_cash) || 100000}
                colorIndex={colorIndex}
                nav={appearance.nav}
                cash={appearance.cash}
              />
            </div>
          </section>
        </>
      )}

      {/* ── The log ──────────────────────────────────────────────────────── */}
      <section className="mt-14">
        <h2 className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
          Session by session
        </h2>
        <p className="mt-2 max-w-[68ch] text-sm leading-relaxed text-muted-foreground">
          Every session this agent traded, newest first: what it decided, the
          sources it read, and the orders that decision produced — refusals
          included. Orders are filed under the decision that caused them, not by
          date; a decision is made after one close and fills at the next
          session&rsquo;s open.
        </p>

        {log.sessions.length === 0 ? (
          <p className="mt-5 max-w-[68ch] text-sm text-muted-foreground">
            {agent.engine === "deterministic"
              ? "This is a control. It follows a fixed rule and does not reason, so there is nothing to publish here — its orders are in the log below."
              : "No decisions recorded for this season."}
          </p>
        ) : (
          <ul className="mt-6 grid gap-8">
            {log.sessions.map((s) => (
              <Session key={s.decision.id} session={s} accent={accent} />
            ))}
          </ul>
        )}
      </section>

      {log.unattributed.length > 0 && (
        <section className="mt-14">
          <h2 className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
            {log.sessions.length === 0 ? "Orders" : "Orders without a decision"}
          </h2>
          {log.sessions.length > 0 && (
            <p className="mt-2 max-w-[68ch] text-xs leading-relaxed text-muted-foreground">
              Placed before decisions were recorded, or by a rule rather than a
              reasoning step. Shown rather than dropped — an order the page
              cannot explain is still part of the record.
            </p>
          )}
          <ul className="mt-5 grid gap-px bg-border">
            {log.unattributed.map((o) => (
              <li key={o.id} className="bg-background">
                <OrderLine order={o} />
              </li>
            ))}
          </ul>
        </section>
      )}

      <p className="mt-14 max-w-[68ch] text-xs leading-relaxed text-muted-foreground">
        Paper trading. No real money is at risk and nothing here is investment
        advice. Orders fill at the next session&rsquo;s open with modelled
        slippage; positions are marked to the close.
      </p>
    </main>
  );
}
