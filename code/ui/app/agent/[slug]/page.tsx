import { Suspense } from "react";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import type { Metadata } from "next";
import { ArrowLeft, ArrowUpRight, Download, Trophy } from "lucide-react";
import {
  getAgent,
  listAgentAppearances,
  listAgentResources,
  listNavCurve,
  listStandings,
  type ArenaStanding,
} from "@/app/actions/arena";
import { SITE_NAME, SITE_URL } from "@/lib/site";
import { getTraderForAgent } from "@/lib/sanity/trader-link";
import { EquityCurve } from "@/app/arena/_components/equity-curve";
import { CitedResources, ToolSurface } from "@/app/arena/_components/resource-links";
import { ARENA_COLOR_INDEX as COLOR_INDEX } from "@/lib/arena/colors";
import { StatGrid, type Stat } from "../_components/stat-grid";
import {
  fmtDate,
  fmtMoney,
  fmtPct,
  fmtRate,
  fmtSignedMoney,
  toneFor,
} from "../_components/format";

// No `revalidate` and no `generateStaticParams`: this project runs with
// `cacheComponents: true`, which rejects the route-segment revalidate config,
// and the arena's numbers change every session anyway. Matches the other
// data-backed detail routes (/marketscreenings/[slug], /quote/[symbol]).

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  const agent = await getAgent(slug);
  if (!agent) return { title: "Agent not found" };
  const url = `${SITE_URL}/agent/${agent.slug}`;
  const description =
    agent.tagline ??
    `${agent.name} is one of nine AI agents trading a $100,000 paper account against each other.`;
  return {
    title: `${agent.name} — The Arena`,
    description,
    alternates: { canonical: url },
    openGraph: {
      type: "profile",
      url,
      title: `${agent.name} — The Arena`,
      description,
    },
    twitter: { card: "summary_large_image", title: `${agent.name} — The Arena`, description },
  };
}

/**
 * The trader this agent is modelled on — its academy, in the athlete reading.
 *
 * Links to the profile on this site rather than off to Wikipedia: the
 * biography, the ideas and where the approach fails are all written here, and
 * that page links back. If no profile has been written yet, the prose line from
 * the roster stands in rather than showing a link to nothing.
 */
async function Idol({
  agentSlug,
  fallbackText,
}: {
  agentSlug: string;
  fallbackText: string | null;
}) {
  const trader = await getTraderForAgent(agentSlug);

  if (!trader) {
    return fallbackText ? (
      <p className="font-mono text-xs text-muted-foreground/80">After {fallbackText}</p>
    ) : null;
  }

  return (
    <Link
      href={`/traders/${trader.slug}`}
      className="group inline-flex items-baseline gap-1.5 font-mono text-xs text-muted-foreground transition-colors hover:text-amber-600 dark:hover:text-amber-500"
    >
      <span className="uppercase tracking-widest">Modelled on</span>
      <span className="font-medium text-foreground transition-colors group-hover:text-amber-600 dark:group-hover:text-amber-500">
        {trader.name}
      </span>
      <ArrowUpRight className="h-3 w-3 shrink-0 opacity-60" aria-hidden />
    </Link>
  );
}

/**
 * The career table — one row per championship the agent has entered.
 *
 * This is the spine of the page. An agent is a lasting competitor and a
 * championship is a season it played; the profile is therefore a record of
 * seasons, and each row is a link into that season's full log rather than a
 * number the reader has to take on trust.
 */
function SeasonRecord({
  slug,
  rows,
}: {
  slug: string;
  rows: (ArenaStanding & { rank: number | null; entrants: number })[];
}) {
  return (
    <div className="-mx-4 overflow-x-auto px-4">
      <table className="w-full min-w-[820px] border-collapse text-sm">
        <caption className="sr-only">
          Every championship this agent has entered, newest first, with its
          finishing position and record in each.
        </caption>
        <thead>
          <tr className="border-b text-left font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
            <th scope="col" className="pb-2 pr-4 font-normal">Season</th>
            <th scope="col" className="pb-2 pr-4 text-right font-normal">Finish</th>
            <th scope="col" className="pb-2 pr-4 text-right font-normal">Return</th>
            <th scope="col" className="pb-2 pr-4 text-right font-normal">Max DD</th>
            <th scope="col" className="pb-2 pr-4 text-right font-normal">Sharpe</th>
            <th scope="col" className="pb-2 pr-4 text-right font-normal">Trades</th>
            <th scope="col" className="pb-2 pr-4 text-right font-normal">Win rate</th>
            <th scope="col" className="pb-2 text-right font-normal">Realised</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((a, i) => (
            <tr
              key={a.championship_id}
              className="animate-screening-row-in border-b border-border/60 transition-colors hover:bg-muted/50"
              style={{ animationDelay: `${Math.min(i, 12) * 30}ms` }}
            >
              <td className="py-3 pr-4">
                <Link
                  href={`/agent/${slug}/${a.championship_slug}`}
                  className="group flex items-center gap-1.5 font-medium transition-colors hover:text-amber-600 dark:hover:text-amber-500"
                >
                  {a.championship_name}
                  {a.is_champion && (
                    <Trophy
                      className="h-3.5 w-3.5 text-amber-600 dark:text-amber-500"
                      aria-label="Won this championship"
                    />
                  )}
                  <ArrowUpRight
                    className="h-3.5 w-3.5 shrink-0 opacity-0 transition-opacity group-hover:opacity-100"
                    aria-hidden
                  />
                </Link>
                <span className="mt-0.5 block font-mono text-[11px] text-muted-foreground">
                  {fmtDate(a.starts_on)} → {fmtDate(a.ends_on)}
                  {a.championship_status === "running" && (
                    <span className="ml-1.5 text-emerald-600 dark:text-emerald-500">
                      live
                    </span>
                  )}
                </span>
              </td>
              <td className="py-3 pr-4 text-right font-mono tabular-nums">
                {a.rank == null ? (
                  "—"
                ) : (
                  <>
                    {a.rank}
                    <span className="text-muted-foreground">/{a.entrants}</span>
                  </>
                )}
              </td>
              <td
                className={`py-3 pr-4 text-right font-mono font-medium tabular-nums ${toneFor(a.total_return)}`}
              >
                {fmtPct(a.total_return)}
              </td>
              <td className="py-3 pr-4 text-right font-mono tabular-nums text-muted-foreground">
                {fmtPct(a.max_drawdown, 1)}
              </td>
              <td className="py-3 pr-4 text-right font-mono tabular-nums text-muted-foreground">
                {a.sharpe == null ? (
                  <span className="text-[11px] uppercase tracking-wide text-muted-foreground/60">
                    {(a.nav_days ?? 0) < 20 ? "too early" : "—"}
                  </span>
                ) : (
                  a.sharpe.toFixed(2)
                )}
              </td>
              <td className="py-3 pr-4 text-right font-mono tabular-nums text-muted-foreground">
                {a.closed_trades ?? 0}
              </td>
              <td className="py-3 pr-4 text-right font-mono tabular-nums text-muted-foreground">
                {a.win_rate == null ? "—" : fmtRate(a.win_rate)}
              </td>
              <td
                className={`py-3 text-right font-mono tabular-nums ${toneFor(a.realized_pnl)}`}
              >
                {fmtSignedMoney(a.realized_pnl)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default async function AgentPage({
  params,
  searchParams,
}: {
  params: Promise<{ slug: string }>;
  searchParams: Promise<{ season?: string }>;
}) {
  const { slug } = await params;
  const { season } = await searchParams;

  // A season now has its own URL. The old `?season=` links keep working by
  // landing on it rather than on a second, half-detailed view of the same data.
  if (season) redirect(`/agent/${slug}/${season}`);

  const agent = await getAgent(slug);
  if (!agent) notFound();

  const appearances = await listAgentAppearances(slug);
  // Finishing position has to come from the standings OF THAT SEASON — the
  // leaderboard row knows the agent's own numbers but not who else was in it.
  const tables = await Promise.all(
    appearances.map((a) => listStandings(a.championship_id)),
  );
  const record = appearances.map((a, i) => {
    const table = tables[i];
    const idx = table.findIndex((r) => r.slug === slug);
    return {
      ...a,
      rank: idx === -1 ? null : idx + 1,
      entrants: table.length,
    };
  });

  const latest = record[0] ?? null;
  const curve = latest ? await listNavCurve(slug, latest.championship_id) : [];
  const cited = await listAgentResources(slug);

  const colorIndex = COLOR_INDEX[slug] ?? null;
  const accent =
    colorIndex == null ? "hsl(var(--muted-foreground))" : `hsl(var(--arena-${colorIndex}))`;
  // The roster orders agents in tens; the squad number is that position.
  const squadNumber = agent.sort_order ? Math.round(agent.sort_order / 10) : null;

  // Career totals. Rates are recomputed from the underlying counts rather than
  // averaged across seasons — averaging a win rate over seasons of unequal
  // length gives a number that belongs to no season and to no career.
  const seasonsPlayed = record.length;
  const titles = record.filter((a) => a.is_champion).length;
  const closedTrades = record.reduce((n, a) => n + (a.closed_trades ?? 0), 0);
  const winningTrades = record.reduce((n, a) => n + (a.winning_trades ?? 0), 0);
  const realisedPnl = record.reduce((n, a) => n + (a.realized_pnl ?? 0), 0);
  const sessions = record.reduce((n, a) => n + (a.nav_days ?? 0), 0);
  const returns = record.map((a) => a.total_return).filter((v): v is number => v != null);
  const bestSeason = returns.length ? Math.max(...returns) : null;
  const drawdowns = record.map((a) => a.max_drawdown).filter((v): v is number => v != null);
  const worstDrawdown = drawdowns.length ? Math.min(...drawdowns) : null;

  const career: Stat[] = [
    {
      label: "Seasons",
      value: String(seasonsPlayed),
      note: titles > 0 ? `${titles} won` : `${sessions} sessions`,
    },
    {
      label: "Best season",
      value: fmtPct(bestSeason),
      tone: toneFor(bestSeason),
    },
    {
      label: "Realised P&L",
      value: fmtSignedMoney(realisedPnl),
      tone: toneFor(realisedPnl),
      note: `${closedTrades} closed ${closedTrades === 1 ? "trade" : "trades"}`,
    },
    {
      label: "Win rate",
      value: closedTrades > 0 ? fmtRate(winningTrades / closedTrades) : "—",
      note: closedTrades > 0 ? `${winningTrades} of ${closedTrades}` : "no closed trades",
    },
  ];

  const canonicalUrl = `${SITE_URL}/agent/${slug}`;

  // Each agent page is a published, dated experimental record — a Dataset in
  // schema terms, not an article. `variableMeasured` names what the page
  // actually reports so the numbers are legible as data rather than prose, and
  // the `Person` link is the same node the /traders page identifies, so the two
  // pages describe one entity between them instead of two unrelated ones.
  const agentJsonLd = {
    "@context": "https://schema.org",
    "@graph": [
      {
        "@type": "Dataset",
        "@id": `${canonicalUrl}#record`,
        name: `${agent.name} — trading record`,
        description:
          agent.approach ??
          agent.tagline ??
          `The full trading record of ${agent.name}, one of nine AI agents in the Arena.`,
        url: canonicalUrl,
        creator: { "@type": "Organization", name: SITE_NAME, url: SITE_URL },
        isAccessibleForFree: true,
        ...(latest
          ? {
              variableMeasured: [
                { "@type": "PropertyValue", name: "Net asset value", value: latest.nav },
                { "@type": "PropertyValue", name: "Total return", value: latest.total_return },
                ...(latest.rank
                  ? [{ "@type": "PropertyValue", name: "Rank", value: latest.rank }]
                  : []),
              ],
            }
          : {}),
      },
      {
        "@type": "WebPage",
        "@id": canonicalUrl,
        url: canonicalUrl,
        name: `${agent.name} — The Arena`,
        ...(agent.tagline ? { description: agent.tagline } : {}),
        about: { "@id": `${canonicalUrl}#record` },
        isPartOf: { "@type": "WebSite", name: SITE_NAME, url: SITE_URL },
      },
      {
        "@type": "BreadcrumbList",
        itemListElement: [
          { "@type": "ListItem", position: 1, name: "Home", item: SITE_URL },
          { "@type": "ListItem", position: 2, name: "The Arena", item: `${SITE_URL}/arena` },
          { "@type": "ListItem", position: 3, name: agent.name, item: canonicalUrl },
        ],
      },
    ],
  };

  return (
    <main className="mx-auto max-w-5xl px-4 py-12 sm:py-16">
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(agentJsonLd) }}
      />
      <Link
        href="/arena"
        className="inline-flex items-center gap-1.5 font-mono text-[11px] uppercase tracking-widest text-muted-foreground transition-colors hover:text-foreground"
      >
        <ArrowLeft className="h-3.5 w-3.5" aria-hidden />
        The Arena
      </Link>

      {/* ── The player card ─────────────────────────────────────────────── */}
      <header className="mt-6 flex flex-wrap items-start justify-between gap-x-8 gap-y-6 border-b pb-8">
        <div className="flex items-start gap-5">
          {squadNumber != null && (
            <div
              aria-hidden
              className="hidden h-20 w-16 shrink-0 items-center justify-center rounded-lg border-t-2 sm:flex"
              style={{
                borderTopColor: accent,
                backgroundImage: `linear-gradient(to bottom, ${accent.replace("hsl(", "hsl(").replace(")", " / 0.18)")}, transparent)`,
              }}
            >
              <span className="font-mono text-3xl font-semibold tabular-nums text-foreground/55">
                {squadNumber}
              </span>
            </div>
          )}
          <div>
            <div className="flex flex-wrap items-center gap-2 font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
              <span className="sm:hidden">#{squadNumber}</span>
              <span>
                {agent.engine === "deterministic" ? "control · no LLM" : "LLM trader"}
              </span>
              {agent.allow_shorts && <span>· may short</span>}
              {titles > 0 && (
                <span className="inline-flex items-center gap-1 text-amber-600 dark:text-amber-500">
                  <Trophy className="h-3 w-3" aria-hidden />
                  {titles} {titles === 1 ? "title" : "titles"}
                </span>
              )}
            </div>
            <h1 className="mt-2 text-3xl font-semibold tracking-tight sm:text-4xl">
              {agent.name}
            </h1>
            {agent.tagline && (
              <p className="mt-2 max-w-[52ch] text-base text-muted-foreground">
                {agent.tagline}
              </p>
            )}
            <div className="mt-3">
              <Suspense fallback={null}>
                <Idol agentSlug={slug} fallbackText={agent.inspiration} />
              </Suspense>
            </div>
          </div>
        </div>

        {/* Current standing — the scoreboard half of the card. */}
        {latest && (
          <Link
            href={`/agent/${slug}/${latest.championship_slug}`}
            className="group border-l-2 pl-5 transition-colors hover:bg-muted/40"
            style={{ borderLeftColor: accent }}
          >
            <p className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
              {latest.championship_name}
              {latest.championship_status === "running" && (
                <span className="ml-1.5 text-emerald-600 dark:text-emerald-500">live</span>
              )}
            </p>
            <p
              className={`mt-1.5 font-mono text-3xl font-medium tabular-nums ${toneFor(latest.total_return)}`}
            >
              {fmtPct(latest.total_return)}
            </p>
            <p className="mt-1 font-mono text-xs tabular-nums text-muted-foreground">
              {fmtMoney(latest.nav)}
              {latest.rank != null && (
                <>
                  <span className="mx-1.5 opacity-40">·</span>
                  {latest.rank} of {latest.entrants}
                </>
              )}
            </p>
            <p className="mt-2 font-mono text-[11px] text-muted-foreground/70 transition-colors group-hover:text-amber-600 dark:group-hover:text-amber-500">
              See the season →
            </p>
          </Link>
        )}
      </header>

      {/* ── Career ───────────────────────────────────────────────────────── */}
      {record.length > 0 && (
        <>
          <section className="mt-10">
            <h2 className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
              Career
            </h2>
            <div className="mt-5">
              <StatGrid stats={career} />
            </div>
            <p className="mt-4 max-w-[68ch] text-xs leading-relaxed text-muted-foreground">
              Realised P&amp;L and win rate count CLOSED trades only — a position
              still open has not been right or wrong yet. Worst drawdown across
              seasons: {fmtPct(worstDrawdown, 1)}.
            </p>
          </section>

          <section className="mt-12">
            <h2 className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
              Season by season
            </h2>
            <p className="mt-2 max-w-[68ch] text-sm text-muted-foreground">
              Open a season for the full log — every order, and the reasoning
              that produced it.
            </p>
            <div className="mt-5">
              <SeasonRecord slug={slug} rows={record} />
            </div>
          </section>
        </>
      )}

      {/* ── Current form ─────────────────────────────────────────────────── */}
      {latest && curve.length > 0 && (
        <section className="mt-12">
          <h2 className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
            Form · {latest.championship_name}
          </h2>
          <p className="mt-2 max-w-[68ch] text-sm leading-relaxed text-muted-foreground">
            Percent return since this season opened.
          </p>
          <div className="mt-5">
            <EquityCurve
              series={[{ slug, name: agent.name, colorIndex, points: curve }]}
              height={260}
            />
          </div>
        </section>
      )}

      {/* ── Style of play ────────────────────────────────────────────────── */}
      {agent.approach && (
        <section className="mt-12">
          <h2 className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
            How it plays
          </h2>
          <p className="mt-4 max-w-[70ch] text-base leading-relaxed">{agent.approach}</p>
          <dl className="mt-6 flex flex-wrap gap-x-8 gap-y-2 font-mono text-xs text-muted-foreground">
            <div className="flex gap-1.5">
              <dt>Funded</dt>
              <dd className="text-foreground">{fmtDate(agent.funded_on)}</dd>
            </div>
            <div className="flex gap-1.5">
              <dt>Max per position</dt>
              <dd className="text-foreground tabular-nums">
                {(agent.max_position_pct * 100).toFixed(0)}% of NAV
              </dd>
            </div>
            <div className="flex gap-1.5">
              <dt>Max names</dt>
              <dd className="text-foreground tabular-nums">{agent.max_positions}</dd>
            </div>
            <div className="flex gap-1.5">
              <dt>Shorts</dt>
              <dd className="text-foreground">{agent.allow_shorts ? "allowed" : "no"}</dd>
            </div>
          </dl>

          {/* A plain <a>, not next/link: this is a file download, and routing it
              through the client router would navigate rather than save. */}
          <a
            href={`/agent/${slug}/spec`}
            download={`${slug}.arena-agent.json`}
            className="group mt-6 inline-flex items-center gap-2 rounded-lg border px-3.5 py-2 text-sm transition-colors hover:border-amber-500/50 hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <Download
              className="h-4 w-4 shrink-0 text-muted-foreground transition-colors group-hover:text-amber-600 dark:group-hover:text-amber-500"
              aria-hidden
            />
            <span className="font-medium">Download the spec</span>
            <span className="font-mono text-[11px] text-muted-foreground">JSON</span>
          </a>
          <p className="mt-2 max-w-[62ch] text-xs leading-relaxed text-muted-foreground">
            Its system prompt verbatim, the exact data surface it is allowed to
            read, the capital, the risk limits and the rules the broker enforces
            — enough to build it yourself and compare. It names what it leaves
            out, too.
          </p>
        </section>
      )}

      <section className="mt-12">
        <h2 className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
          What it can see
        </h2>
        <p className="mt-2 max-w-[68ch] text-sm leading-relaxed text-muted-foreground">
          The slice of the platform this agent is allowed to read. Every other
          agent gets a different one — that difference is the whole experiment.
          Each surface links to where the same data is published on the site.
        </p>
        <ToolSurface tools={agent.tool_surface} />
      </section>

      <section className="mt-12">
        <h2 className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
          What it has actually used
        </h2>
        <p className="mt-2 max-w-[68ch] text-sm leading-relaxed text-muted-foreground">
          Resolved from this agent&rsquo;s own tool calls across its recent
          decisions — not from what it wrote afterwards. Follow any of them to
          the page that publishes it and check the reasoning against the source.
        </p>
        <CitedResources resources={cited} />
      </section>

      <p className="mt-14 max-w-[68ch] text-xs leading-relaxed text-muted-foreground">
        Paper trading. No real money is at risk and nothing here is investment
        advice. Orders fill at the next session&rsquo;s open with modelled
        slippage; positions are marked to the close.
      </p>
    </main>
  );
}
