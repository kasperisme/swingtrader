import { Suspense } from "react";
import Link from "next/link";
import { notFound } from "next/navigation";
import type { Metadata } from "next";
import { ArrowLeft, ArrowUpRight } from "lucide-react";
import {
  getAgent,
  getFeaturedChampionship,
  listAgentResources,
  listDecisions,
  listNavCurve,
  listOrders,
  listPositions,
  listStandings,
  type ArenaOrder,
} from "@/app/actions/arena";
import { SITE_URL } from "@/lib/site";
import { getTraderForAgent } from "@/lib/sanity/trader-link";
import { EquityCurve } from "../_components/equity-curve";
import {
  CitedResources,
  ResourceChips,
  ToolSurface,
} from "../_components/resource-links";

const COLOR_INDEX: Record<string, number> = {
  "jim-clamor": 1,
  "michael-beary": 2,
  "mark-minervine": 3,
  "barren-wuffett": 4,
  "howard-marx": 5,
  "jim-sigmons": 6,
  "chris-cameo": 7,
};

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
  return {
    title: `${agent.name} — The Arena`,
    description:
      agent.tagline ??
      `${agent.name} is one of nine AI agents trading a $100,000 paper account against each other.`,
    alternates: { canonical: `${SITE_URL}/arena/${agent.slug}` },
  };
}

function fmtMoney(v: number | null | undefined, digits = 0) {
  if (v == null) return "—";
  return `$${v.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}`;
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
  return new Date(iso.length === 10 ? `${iso}T00:00:00Z` : iso).toLocaleDateString(
    "en-GB",
    { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" },
  );
}

const ORDER_TONE: Record<ArenaOrder["status"], string> = {
  filled: "text-foreground",
  pending: "text-amber-600 dark:text-amber-500",
  rejected: "text-rose-600 dark:text-rose-500",
  cancelled: "text-muted-foreground",
};

/**
 * The trader this agent is modelled on.
 *
 * Links to the profile on this site rather than off to Wikipedia — the
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
      <p className="mt-6 font-mono text-xs text-muted-foreground/80">
        After {fallbackText}
      </p>
    ) : null;
  }

  return (
    <Link
      href={`/traders/${trader.slug}`}
      className="group mt-6 block rounded-lg border p-4 transition-colors hover:border-amber-500/50 hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <p className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
        Modelled on
      </p>
      <p className="mt-1.5 flex items-baseline gap-1.5 text-lg font-semibold tracking-tight transition-colors group-hover:text-amber-600 dark:group-hover:text-amber-500">
        {trader.name}
        <ArrowUpRight
          className="h-4 w-4 shrink-0 opacity-0 transition-opacity group-hover:opacity-100"
          aria-hidden
        />
      </p>
      {(trader.summary || trader.knownFor) && (
        <p className="mt-1 max-w-[64ch] text-sm leading-relaxed text-muted-foreground">
          {trader.summary || trader.knownFor}
        </p>
      )}
      <p className="mt-2 font-mono text-[11px] text-muted-foreground/70">
        Read the method this agent is running →
      </p>
    </Link>
  );
}


export default async function ArenaAgentPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const agent = await getAgent(slug);
  if (!agent) notFound();

  const champ = await getFeaturedChampionship();
  const [standings, curve, positions, orders, decisions, cited] = await Promise.all([
    listStandings(champ?.id),
    listNavCurve(slug, champ?.id),
    listPositions(slug),
    listOrders(slug, 40),
    listDecisions(slug, 12),
    listAgentResources(slug),
  ]);

  const standing = standings.find((s) => s.slug === slug);
  const rank = standings.findIndex((s) => s.slug === slug) + 1;
  const colorIndex = COLOR_INDEX[slug] ?? null;
  const accent =
    colorIndex == null ? "hsl(var(--muted-foreground))" : `hsl(var(--arena-${colorIndex}))`;

  return (
    <main className="mx-auto max-w-5xl px-4 py-12 sm:py-16">
      <Link
        href="/arena"
        className="inline-flex items-center gap-1.5 font-mono text-[11px] uppercase tracking-widest text-muted-foreground transition-colors hover:text-foreground"
      >
        <ArrowLeft className="h-3.5 w-3.5" aria-hidden />
        The Arena
      </Link>

      <header className="mt-6 border-l-2 pl-5" style={{ borderLeftColor: accent }}>
        <div className="flex flex-wrap items-center gap-3 font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
          {rank > 0 && standing?.total_return != null && (
            <span>Rank {rank} of {standings.length}</span>
          )}
          {agent.engine === "deterministic" && (
            <span className="rounded bg-muted px-1.5 py-0.5 text-muted-foreground">
              control · no LLM
            </span>
          )}
          {agent.allow_shorts && <span>may short</span>}
        </div>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight sm:text-4xl">
          {agent.name}
        </h1>
        {agent.tagline && (
          <p className="mt-2 text-base text-muted-foreground">{agent.tagline}</p>
        )}
        {agent.inspiration && (
          <p className="mt-1.5 font-mono text-xs text-muted-foreground/80">
            After {agent.inspiration}
          </p>
        )}
      </header>

      <Suspense fallback={null}>
        <Idol agentSlug={slug} fallbackText={agent.inspiration} />
      </Suspense>

      {/* Headline numbers. NAV and return are the hero pair; everything else is
          the context that stops them being read as a claim. */}
      <section className="mt-10 grid grid-cols-2 gap-x-6 gap-y-6 sm:grid-cols-4">
        {(
          [
            ["NAV", fmtMoney(standing?.nav), null],
            [
              "Return",
              fmtPct(standing?.total_return),
              toneFor(standing?.total_return),
            ],
            ["Max drawdown", fmtPct(standing?.max_drawdown, 1), null],
            [
              "Sharpe",
              standing?.sharpe == null
                ? (standing?.nav_days ?? 0) < 20
                  ? "too early"
                  : "—"
                : standing.sharpe.toFixed(2),
              null,
            ],
          ] as const
        ).map(([label, value, tone]) => (
          <div key={label}>
            <p className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
              {label}
            </p>
            <p
              className={`mt-1.5 font-mono text-2xl font-medium tabular-nums ${tone ?? ""}`}
            >
              {value}
            </p>
          </div>
        ))}
      </section>

      {agent.approach && (
        <section className="mt-12">
          <h2 className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
            The approach
          </h2>
          <p className="mt-4 max-w-[70ch] text-base leading-relaxed">
            {agent.approach}
          </p>
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
          </dl>
        </section>
      )}

      <section className="mt-12">
        <h2 className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
          Equity curve
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
          Open positions
        </h2>
        {positions.length === 0 ? (
          <p className="mt-4 max-w-[60ch] text-sm text-muted-foreground">
            Holding no positions — all cash{" "}
            {standing?.cash != null && `(${fmtMoney(standing.cash)})`}. For this
            agent that may be a decision rather than an absence of one.
          </p>
        ) : (
          <div className="-mx-4 mt-5 overflow-x-auto px-4">
            <table className="w-full min-w-[620px] border-collapse text-sm">
              <caption className="sr-only">
                Open positions with cost basis, current mark and unrealised P&amp;L
              </caption>
              <thead>
                <tr className="border-b text-left font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
                  <th scope="col" className="pb-2 pr-4 font-normal">Ticker</th>
                  <th scope="col" className="pb-2 pr-4 text-right font-normal">Qty</th>
                  <th scope="col" className="pb-2 pr-4 text-right font-normal">Cost</th>
                  <th scope="col" className="pb-2 pr-4 text-right font-normal">Mark</th>
                  <th scope="col" className="pb-2 pr-4 text-right font-normal">Value</th>
                  <th scope="col" className="pb-2 text-right font-normal">Unrealised</th>
                </tr>
              </thead>
              <tbody className="font-mono tabular-nums">
                {positions.map((p, i) => (
                  <tr
                    key={p.ticker}
                    className="animate-screening-row-in border-b border-border/60"
                    style={{ animationDelay: `${Math.min(i, 12) * 30}ms` }}
                  >
                    <td className="py-2.5 pr-4">
                      <Link
                        href={`/quote/${p.ticker}`}
                        className="font-medium hover:text-amber-600 dark:hover:text-amber-500"
                      >
                        {p.ticker}
                      </Link>
                      {p.quantity < 0 && (
                        <span className="ml-2 rounded bg-muted px-1 py-0.5 text-[10px] uppercase tracking-wide text-muted-foreground">
                          short
                        </span>
                      )}
                    </td>
                    <td className="py-2.5 pr-4 text-right">
                      {Math.abs(p.quantity).toLocaleString()}
                    </td>
                    <td className="py-2.5 pr-4 text-right text-muted-foreground">
                      {fmtMoney(p.avg_cost, 2)}
                    </td>
                    <td className="py-2.5 pr-4 text-right">
                      {fmtMoney(p.last_price, 2)}
                    </td>
                    <td className="py-2.5 pr-4 text-right text-muted-foreground">
                      {fmtMoney(Math.abs(p.market_value))}
                    </td>
                    <td
                      className={`py-2.5 text-right font-medium ${toneFor(p.unrealized_pct)}`}
                    >
                      {fmtPct(p.unrealized_pct)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="mt-12">
        <h2 className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
          Daily reasoning
        </h2>
        {decisions.filter((d) => d.narrative).length === 0 ? (
          <p className="mt-4 text-sm text-muted-foreground">
            No published reasoning yet.
          </p>
        ) : (
          <ul className="mt-5 grid gap-2">
            {decisions
              .filter((d) => d.narrative)
              .map((d, i) => (
                <li
                  key={d.id}
                  className="animate-screening-row-in border-l-2 border-l-border py-4 pl-5"
                  style={{ animationDelay: `${Math.min(i, 12) * 40}ms` }}
                >
                  <div className="flex flex-wrap items-baseline gap-x-3 font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
                    <span className="tabular-nums text-foreground">
                      {fmtDate(d.decision_date)}
                    </span>
                    <span>
                      {d.orders_accepted === 0
                        ? "no trades"
                        : `${d.orders_accepted} placed`}
                      {d.orders_rejected > 0 && ` · ${d.orders_rejected} refused`}
                    </span>
                    {d.nav_at_decision != null && (
                      <span className="tabular-nums">
                        NAV {fmtMoney(d.nav_at_decision)}
                      </span>
                    )}
                  </div>
                  <p className="mt-2 max-w-[72ch] text-sm leading-relaxed">
                    {d.narrative}
                  </p>
                  <ResourceChips resources={d.resources ?? []} />
                </li>
              ))}
          </ul>
        )}
      </section>

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

      <section className="mt-12">
        <h2 className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
          Order log
        </h2>
        <p className="mt-2 max-w-[68ch] text-xs leading-relaxed text-muted-foreground">
          Including orders the broker refused. What an agent tried to do and was
          not allowed to do is part of the record.
        </p>
        {orders.length === 0 ? (
          <p className="mt-4 text-sm text-muted-foreground">No orders yet.</p>
        ) : (
          <ul className="mt-5 grid gap-px bg-border">
            {orders.map((o) => (
              <li key={o.id} className="bg-background py-3">
                <div className="flex flex-wrap items-baseline gap-x-3 font-mono text-xs tabular-nums">
                  <span className="text-muted-foreground">
                    {fmtDate(o.submitted_at.slice(0, 10))}
                  </span>
                  <span
                    className={
                      o.side === "buy"
                        ? "font-medium text-emerald-600 dark:text-emerald-500"
                        : "font-medium text-rose-600 dark:text-rose-500"
                    }
                  >
                    {o.side.toUpperCase()}
                  </span>
                  <Link
                    href={`/quote/${o.ticker}`}
                    className="font-medium hover:text-amber-600 dark:hover:text-amber-500"
                  >
                    {o.ticker}
                  </Link>
                  <span className="text-muted-foreground">
                    ×{Math.round(o.quantity).toLocaleString()}
                  </span>
                  {o.fill_price != null && (
                    <span className="text-muted-foreground">
                      @ {fmtMoney(o.fill_price, 2)}
                    </span>
                  )}
                  <span className={`uppercase tracking-wide ${ORDER_TONE[o.status]}`}>
                    {o.status}
                  </span>
                  {o.realized_pnl != null && (
                    <span className={`font-medium ${toneFor(o.realized_pnl)}`}>
                      {o.realized_pnl >= 0 ? "+" : "−"}
                      {fmtMoney(Math.abs(o.realized_pnl))}
                    </span>
                  )}
                </div>
                {o.reject_reason ? (
                  <p className="mt-1.5 max-w-[72ch] text-xs leading-relaxed text-rose-600/90 dark:text-rose-500/90">
                    {o.reject_reason}
                  </p>
                ) : (
                  o.thesis && (
                    <p className="mt-1.5 max-w-[72ch] text-xs leading-relaxed text-muted-foreground">
                      {o.thesis}
                    </p>
                  )
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <p className="mt-14 max-w-[68ch] text-xs leading-relaxed text-muted-foreground">
        Paper trading. No real money is at risk and nothing here is investment
        advice. Orders fill at the next session&rsquo;s open with modelled
        slippage; positions are marked to the close.
      </p>
    </main>
  );
}
