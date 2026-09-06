import { Suspense } from "react";
import Link from "next/link";
import { notFound } from "next/navigation";
import type { Metadata } from "next";
import { ArrowLeft, ArrowUpRight, Trophy } from "lucide-react";
import {
  getAgent,
  listAgentResources,
  listDecisions,
  listNavCurve,
  listOrders,
  listPositions,
  listStandings,
  resolveAgentAppearance,
  type ArenaOrder,
  type ArenaStanding,
} from "@/app/actions/arena";
import { SITE_NAME, SITE_URL } from "@/lib/site";
import { getTraderForAgent } from "@/lib/sanity/trader-link";
import { EquityCurve } from "@/app/arena/_components/equity-curve";
import { PortfolioPanel } from "@/app/arena/_components/portfolio-panel";
import {
  CitedResources,
  ResourceChips,
  ToolSurface,
} from "@/app/arena/_components/resource-links";
import { ARENA_COLOR_INDEX as COLOR_INDEX } from "@/lib/arena/colors";

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

/**
 * How a fill reads on the tape, once agents can short.
 *
 * Colouring by `side` inverted the meaning for both short cases: opening a
 * short is a new BEARISH position and was painted in the exit colour, while
 * covering one CLOSES a bearish bet and was painted like a fresh buy. So the
 * colour tracks the direction of the bet, not the direction of the cash:
 * emerald opens bullish, rose opens bearish, muted closes either.
 */
const EFFECT_LABEL: Record<
  NonNullable<ArenaOrder["position_effect"]>,
  { label: string; tone: string }
> = {
  open_long: { label: "BUY", tone: "text-emerald-600 dark:text-emerald-500" },
  close_long: { label: "SELL", tone: "text-muted-foreground" },
  open_short: { label: "SHORT", tone: "text-rose-600 dark:text-rose-500" },
  cover_short: { label: "COVER", tone: "text-muted-foreground" },
  flip_to_short: { label: "SELL → SHORT", tone: "text-rose-600 dark:text-rose-500" },
  flip_to_long: { label: "COVER → BUY", tone: "text-emerald-600 dark:text-emerald-500" },
};

/**
 * Rows written before position_effect existed, and any unfilled order, carry
 * NULL. Those fall back to the bare side — every agent but Jim Sigmons was
 * long-only then, so the old reading was right for them, and an invented label
 * would be worse than a plain one.
 */
function orderVerb(o: ArenaOrder): { label: string; tone: string } {
  if (o.position_effect) return EFFECT_LABEL[o.position_effect];
  return {
    label: o.side.toUpperCase(),
    tone:
      o.side === "buy"
        ? "text-emerald-600 dark:text-emerald-500"
        : "text-rose-600 dark:text-rose-500",
  };
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


/**
 * The agent's record across championships.
 *
 * Rendered only when there is more than one: with a single season a switcher is
 * chrome that implies a choice the reader does not have, and the season is
 * already named in the back-link above. It becomes useful the moment season-2
 * opens, which is the reason the agent has its own URL at all — the agent
 * persists, the championship is an appearance.
 *
 * Plain links rather than a client control, so each season is addressable
 * (`?season=season-1`), shareable, and works before hydration.
 */
function Appearances({
  slug,
  appearances,
  current,
}: {
  slug: string;
  appearances: ArenaStanding[];
  current: ArenaStanding | null;
}) {
  if (appearances.length < 2) return null;

  return (
    <nav
      aria-label="Championship appearances"
      className="mt-8 flex flex-wrap items-center gap-2"
    >
      <span className="mr-1 font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
        Appearances
      </span>
      {appearances.map((a) => {
        const isCurrent = a.championship_id === current?.championship_id;
        return (
          <Link
            key={a.championship_id}
            href={`/agent/${slug}?season=${a.championship_slug}`}
            aria-current={isCurrent ? "page" : undefined}
            className={`rounded-full border px-3 py-1 text-xs tabular-nums transition-colors ${
              isCurrent
                ? "border-foreground/30 bg-muted font-medium text-foreground"
                : "border-transparent bg-muted/40 text-muted-foreground hover:bg-muted hover:text-foreground"
            }`}
          >
            {a.championship_name}
            {a.total_return != null && (
              <span className={`ml-2 ${toneFor(a.total_return)}`}>
                {fmtPct(a.total_return)}
              </span>
            )}
            {a.championship_status === "running" && (
              <span className="ml-1.5 opacity-60">live</span>
            )}
            {a.is_champion && (
              <Trophy
                className="ml-1.5 inline h-3 w-3 text-amber-600 dark:text-amber-500"
                aria-label="Won this championship"
              />
            )}
          </Link>
        );
      })}
    </nav>
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
  const agent = await getAgent(slug);
  if (!agent) notFound();

  // The agent is the entity; a championship is a season it appeared in. So the
  // page resolves against THIS AGENT'S appearances rather than the arena's
  // featured championship — the two diverge the moment an agent sits a season
  // out, and opening on a season it never entered would show an empty book with
  // no explanation. Defaults to its most recent appearance.
  const { appearances, current } = await resolveAgentAppearance(slug, season);
  const champId = current?.championship_id;

  const [standings, curve, positions, orders, decisions, cited] = await Promise.all([
    listStandings(champId),
    listNavCurve(slug, champId),
    listPositions(slug, champId),
    listOrders(slug, 40),
    listDecisions(slug, 12),
    listAgentResources(slug),
  ]);

  const canonicalUrl = `${SITE_URL}/agent/${slug}`;
  const standing = standings.find((s) => s.slug === slug);
  const rank = standings.findIndex((s) => s.slug === slug) + 1;
  const colorIndex = COLOR_INDEX[slug] ?? null;
  const accent =
    colorIndex == null ? "hsl(var(--muted-foreground))" : `hsl(var(--arena-${colorIndex}))`;

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
        ...(standing
          ? {
              variableMeasured: [
                { "@type": "PropertyValue", name: "Net asset value", value: standing.nav },
                { "@type": "PropertyValue", name: "Total return", value: standing.total_return },
                { "@type": "PropertyValue", name: "Rank", value: rank },
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
          { "@type": "ListItem", position: 2, name: "Agents", item: `${SITE_URL}/agent` },
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
        {current ? current.championship_name : "The Arena"}
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

      <Appearances slug={slug} appearances={appearances} current={current} />

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
          Return
        </h2>
        <p className="mt-2 max-w-[68ch] text-sm leading-relaxed text-muted-foreground">
          Percent return since this championship opened.
        </p>
        <div className="mt-5">
          <EquityCurve
            series={[{ slug, name: agent.name, colorIndex, points: curve }]}
            height={260}
          />
        </div>
      </section>

      <section className="mt-12">
        <h2 className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
          Portfolio
        </h2>
        <p className="mt-2 max-w-[68ch] text-sm leading-relaxed text-muted-foreground">
          The account in dollars, split into holdings and cash — the return chart
          above cannot tell a flat month spent fully invested from one spent
          sitting out. <strong className="font-medium text-foreground">Click any
          point</strong> to see the book it was holding that day.
        </p>
        <div className="mt-5">
          <PortfolioPanel
            points={curve}
            livePositions={positions}
            startingCash={Number(agent.starting_cash) || 100000}
            colorIndex={colorIndex}
            nav={standing?.nav ?? null}
            cash={standing?.cash ?? null}
          />
        </div>
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
                  {/* The SESSION the order belongs to, not when the row was
                      written. In a replay `submitted_at` is the wall-clock time
                      the backtest ran, so using it would stamp 46 sessions of
                      trades with the same evening. */}
                  <span className="text-muted-foreground">
                    {fmtDate(o.intended_for ?? o.submitted_at.slice(0, 10))}
                  </span>
                  <span className={`font-medium ${orderVerb(o).tone}`}>
                    {orderVerb(o).label}
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
