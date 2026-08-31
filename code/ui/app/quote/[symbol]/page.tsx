import { cache } from "react";
import type { Metadata } from "next";
import Link from "next/link";
import {
  fmpGetCompanyProfile,
  fmpGetQuote,
  fmpGetOhlc,
  type FmpOhlcBar,
} from "@/app/actions/fmp";
import {
  getTickerImpactNewsResult,
  type ScoredNewsEvent,
} from "@/lib/quote/ticker-impact";
import { getPricedInVote } from "@/lib/quote/priced-in";
import { getTickerPeers, peerLabel, type TickerPeer } from "@/lib/quote/peers";
import { PricedInPanel } from "./_components/priced-in-panel";
import {
  TickerImpactChart,
  type ChartEvent,
} from "./_components/ticker-impact-chart";
import { ArticleBriefingCTA } from "@/app/articles/[slug]/_components/article-briefing-cta";
import { QuoteChartWorkspace } from "./_components/quote-chart-workspace";
import { QuoteTabs } from "./_components/quote-tabs";
import { QuoteRelationshipGraph } from "./_components/quote-relationship-graph";
import { SITE_URL } from "@/lib/site";

const SITE_BASE_URL = SITE_URL;

function normSymbol(raw: string): string {
  return decodeURIComponent(raw || "").trim().toUpperCase().slice(0, 12);
}

type RawQuote = Record<string, unknown>;

function qnum(q: RawQuote | null, ...keys: string[]): number | null {
  if (!q) return null;
  for (const k of keys) {
    const v = q[k];
    if (v != null && Number.isFinite(Number(v))) return Number(v);
  }
  return null;
}

function fmtCompact(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return "—";
  return new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(n);
}
function fmtFixed(n: number | null | undefined, d = 2): string {
  if (n == null || !Number.isFinite(n)) return "—";
  return n.toFixed(d);
}

/** Fixed locale + zone: the page is prerendered, so the string must be stable. */
const DAY_FMT = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  year: "numeric",
  timeZone: "UTC",
});
function fmtDay(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : DAY_FMT.format(d);
}

/** Which impact dimensions are doing the most work across the window. */
function topDimensions(events: ScoredNewsEvent[], n = 2): string[] {
  const tally = new Map<string, number>();
  for (const e of events) {
    for (const d of e.topDimensions) tally.set(d, (tally.get(d) ?? 0) + 1);
  }
  return [...tally.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, n)
    .map(([d]) => d.replace(/_/g, " "));
}

function meanSentiment(events: ScoredNewsEvent[]): number | null {
  const vals = events.map((e) => e.sentiment).filter((s): s is number => s != null);
  if (vals.length === 0) return null;
  return vals.reduce((a, b) => a + b, 0) / vals.length;
}

/**
 * Per-request reads shared by `generateMetadata` and the page body.
 *
 * Both passes of one render now need the same catalysts and the same
 * reconstruction — the description quotes real numbers out of them, and the
 * indexability decision is made from them. `cache()` is request-scoped, so the
 * two passes share one round trip instead of doubling every query.
 */
const profileOf = cache(async (symbol: string) => {
  const res = await fmpGetCompanyProfile(symbol);
  return res.ok ? res.data : null;
});
const eventsOf = cache((symbol: string) =>
  getTickerImpactNewsResult(symbol, { days: 365, limit: 150, perBucket: 2 }),
);
const pricedInOf = cache((symbol: string) => getPricedInVote(symbol));
const peersOf = cache((symbol: string) => getTickerPeers(symbol));

/**
 * Is there anything here that Google can't already get from a thousand other
 * quote pages?
 *
 * Price, market cap and the vendor's company blurb are the same commodity data
 * everywhere; publishing 1,500 pages of it is how a site earns "Crawled —
 * currently not indexed". A page qualifies for the index when it carries the
 * work that is actually ours: scored catalysts, or a published reconstruction
 * of what the price already reflects. Everything else stays crawlable and
 * followable — it just doesn't ask to be indexed until it has something to say.
 *
 * Fails OPEN. `ok: false` means the catalyst query itself failed, which looks
 * exactly like an uncovered ticker from here — and a transient RPC timeout must
 * never be what noindexes a page that has real coverage.
 */
function isSubstantive(
  events: { ok: boolean; events: ScoredNewsEvent[] },
  pricedIn: unknown,
): boolean {
  return !events.ok || events.events.length >= 3 || Boolean(pricedIn);
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ symbol: string }>;
}): Promise<Metadata> {
  const symbol = normSymbol((await params).symbol);
  const [profile, eventsResult, pricedIn] = await Promise.all([
    profileOf(symbol),
    eventsOf(symbol),
    pricedInOf(symbol),
  ]);
  const events = eventsResult.events;
  const name = profile?.companyName || symbol;
  const known = Boolean(profile?.companyName);

  // Lead with the query people actually type ("NVDA stock news"), not with our
  // product vocabulary — "news impact" is a term we invented and nobody
  // searches for it. The brand suffix comes from the layout's title template,
  // so the distinctive part has to sit at the front.
  const title = `${symbol} Stock News & Catalysts — ${name}`;
  const description = known
    ? events.length > 0
      ? `Why ${name} (${symbol}) is moving: ${events.length} scored news catalysts from the past year plotted on the price chart, with sentiment, key statistics and connected tickers.`
      : `${name} (${symbol}) stock: price chart, sentiment, key statistics, connected tickers and news catalysts scored for impact by the News Impact Screener.`
    : `${symbol} stock: scored news catalysts, price chart, sentiment, and key statistics from the News Impact Screener.`;

  const canonical = `/quote/${symbol}`;
  const ogImage =
    profile?.image && !profile.defaultImage ? [{ url: profile.image }] : undefined;

  const keywords = [
    symbol,
    `${symbol} stock`,
    `${symbol} news`,
    `${name} stock`,
    `${symbol} price`,
    `${symbol} news impact`,
    "news impact score",
    "swing trading",
    "stock catalysts",
    profile?.sector,
    profile?.industry,
  ].filter((k): k is string => Boolean(k));

  return {
    title,
    description,
    keywords,
    category: "finance",
    alternates: { canonical },
    // Don't let thin pages dilute the index — see `isSubstantive`.
    robots:
      known && isSubstantive(eventsResult, pricedIn)
        ? { index: true, follow: true }
        : { index: false, follow: true },
    openGraph: {
      title,
      description,
      type: "website",
      url: canonical,
      siteName: "News Impact Screener",
      images: ogImage,
    },
    twitter: {
      card: ogImage ? "summary_large_image" : "summary",
      title,
      description,
      images: ogImage?.map((i) => i.url),
    },
  };
}

/** Map each scored event onto the nearest trading bar + that day's move. */
function attachBars(events: ScoredNewsEvent[], bars: FmpOhlcBar[]): ChartEvent[] {
  if (bars.length === 0) return [];
  // bars are ascending by date; build a date->index map for exact hits.
  const idxByDate = new Map<string, number>();
  bars.forEach((b, i) => idxByDate.set(b.date.slice(0, 10), i));
  const dates = bars.map((b) => b.date.slice(0, 10));

  const out: ChartEvent[] = [];
  for (const e of events) {
    if (!e.publishedAt) continue;
    const day = e.publishedAt.slice(0, 10);
    let idx = idxByDate.get(day);
    if (idx == null) {
      // nearest prior trading day
      let lo = 0;
      let hi = dates.length - 1;
      let found = -1;
      while (lo <= hi) {
        const mid = (lo + hi) >> 1;
        if (dates[mid] <= day) {
          found = mid;
          lo = mid + 1;
        } else {
          hi = mid - 1;
        }
      }
      idx = found;
    }
    if (idx == null || idx < 0) continue;
    const bar = bars[idx];
    const prev = idx > 0 ? bars[idx - 1] : null;
    const movePct =
      prev && prev.close > 0 ? ((bar.close - prev.close) / prev.close) * 100 : null;
    out.push({ ...e, barIndex: idx, movePct });
  }
  return out;
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: "up" | "down" }) {
  return (
    <div className="rounded-lg border border-border bg-card px-3 py-2">
      <p className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <p
        className={`mt-0.5 font-mono text-sm font-medium tabular-nums ${
          tone === "up" ? "text-emerald-500" : tone === "down" ? "text-rose-500" : "text-foreground"
        }`}
      >
        {value}
      </p>
    </div>
  );
}

/**
 * The paragraph that exists on no other quote page on the internet.
 *
 * A ticker page is otherwise a pile of commodity numbers — price, market cap,
 * the data vendor's company blurb — reprinted identically by fifty sites, which
 * is exactly the profile of a page search engines crawl and decline to index.
 * This is the summary of our own scoring: how many catalysts, the loudest one
 * and what the stock did that day, which way the coverage leans, and which
 * impact dimensions are driving it. It is server-rendered, above the tabs, and
 * it changes as the coverage does.
 */
function CatalystLede({
  symbol,
  name,
  events,
  top,
}: {
  symbol: string;
  name: string;
  events: ScoredNewsEvent[];
  top: ChartEvent | null;
}) {
  // `top` is the day the stock actually moved most, not the highest raw impact
  // score — that one is nearly always a macro index story ("Dow slips as…"),
  // which reads as filler on a single-company page.
  if (events.length < 3) return null;

  const dims = topDimensions(events);
  const mean = meanSentiment(events);
  const lean =
    mean == null ? null : mean > 0.08 ? "positive" : mean < -0.08 ? "negative" : "mixed";
  const topDay = fmtDay(top?.publishedAt);

  return (
    <p className="max-w-[80ch] text-sm leading-relaxed text-muted-foreground">
      We have scored{" "}
      <span className="font-medium text-foreground">{events.length} news catalysts</span> on{" "}
      {name} ({symbol}) over the past 12 months.
      {top && topDay ? (
        <>
          {" "}
          The biggest single-day move next to one of them came {topDay}, when{" "}
          {symbol} closed{" "}
          <span
            className={
              (top.movePct ?? 0) >= 0 ? "text-emerald-500" : "text-rose-500"
            }
          >
            {(top.movePct ?? 0) >= 0 ? "+" : "−"}
            {Math.abs(top.movePct ?? 0).toFixed(1)}%
          </span>
          : “{top.title}”.
        </>
      ) : null}
      {lean ? (
        <>
          {" "}
          Coverage across the window leans {lean} (average ticker sentiment{" "}
          {mean != null ? `${mean >= 0 ? "+" : "−"}${Math.abs(mean).toFixed(2)}` : "—"}).
        </>
      ) : null}
      {dims.length > 0 ? (
        <> Most of the impact sits in {dims.join(" and ")}.</>
      ) : null}
    </p>
  );
}

/**
 * Crawlable links to the tickers this one is actually entangled with.
 *
 * The relationship explorer below renders the same graph far better — but it is
 * a d3 canvas mounted client-side on scroll, so a crawler saw an empty div and
 * these 1,500 pages linked to each other exactly zero times. The graph is in
 * the database; this puts one hop of it in the HTML, with the link type as the
 * context rather than a bare ticker chip.
 */
function PeerLinks({
  symbol,
  companyName,
  peers,
}: {
  symbol: string;
  companyName: string;
  peers: TickerPeer[];
}) {
  if (peers.length === 0) return null;
  return (
    <section>
      <h2 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        Tickers connected to {symbol}
      </h2>
      <p className="mb-3 max-w-[80ch] text-xs text-muted-foreground">
        Suppliers, customers, partners and competitors of {companyName}, taken
        from what the news actually said about them rather than from a sector
        bucket. The count is how many articles established each link.
      </p>
      <ul className="flex flex-wrap gap-2">
        {peers.map((p) => (
          <li key={p.ticker}>
            <Link
              href={`/quote/${p.ticker}`}
              className="flex items-baseline gap-2 rounded-lg border border-border bg-card px-3 py-1.5 transition-colors hover:border-amber-500/60"
            >
              <span className="font-mono text-sm font-semibold">{p.ticker}</span>
              <span className="text-[11px] text-muted-foreground">{peerLabel(p)}</span>
              <span className="text-[11px] tabular-nums text-muted-foreground/70">
                {p.articleCount}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

export default async function QuotePage({
  params,
}: {
  params: Promise<{ symbol: string }>;
}) {
  // Case is normalised to a 308 in proxy.ts before this route is reached.
  const symbol = normSymbol((await params).symbol);

  const [profile, quoteRes, ohlcRes, eventsResult, pricedIn, peers] =
    await Promise.all([
      profileOf(symbol),
      fmpGetQuote(symbol),
      fmpGetOhlc(symbol, "1day"),
      eventsOf(symbol),
      pricedInOf(symbol),
      peersOf(symbol),
    ]);
  const events = eventsResult.events;

  const quote: RawQuote | null =
    quoteRes.ok && Array.isArray(quoteRes.data) ? (quoteRes.data[0] as RawQuote) ?? null : null;
  const bars: FmpOhlcBar[] = ohlcRes.ok ? ohlcRes.data : [];

  const hasAnything = Boolean(profile || quote || bars.length || events.length);
  if (!hasAnything) {
    return (
      <div className="mx-auto max-w-3xl px-4 py-20 text-center">
        <h1 className="text-2xl font-bold">{symbol}</h1>
        <p className="mt-3 text-sm text-muted-foreground">
          No data available for this symbol yet. Check the ticker and try again.
        </p>
        <Link href="/articles" className="mt-6 inline-block text-sm text-primary hover:underline">
          ← Back to articles
        </Link>
      </div>
    );
  }

  const chartEvents = attachBars(events, bars);

  // "What moved" — rank by impact, breaking ties by absolute price move.
  const moved = [...chartEvents]
    .sort(
      (a, b) =>
        b.impactMagnitude - a.impactMagnitude ||
        Math.abs(b.movePct ?? 0) - Math.abs(a.movePct ?? 0),
    )
    .slice(0, 6);

  // The sharpest price day among the well-scored catalysts — see CatalystLede.
  const ledeTop =
    [...moved]
      .filter((e) => e.movePct != null && e.title)
      .sort((a, b) => Math.abs(b.movePct ?? 0) - Math.abs(a.movePct ?? 0))[0] ??
    null;

  const price = qnum(quote, "price") ?? profile?.price ?? null;
  const change = qnum(quote, "change") ?? profile?.change ?? null;
  const changePct = qnum(quote, "changePercentage", "changesPercentage") ?? profile?.changePercentage ?? null;
  const companyName = profile?.companyName ?? symbol;
  const exchange = profile?.exchange ?? profile?.exchangeFullName ?? null;
  const tone = (change ?? 0) > 0 ? "up" : (change ?? 0) < 0 ? "down" : undefined;

  const canonicalUrl = `${SITE_BASE_URL}/quote/${symbol}`;

  // Structured data: the company as a tradable financial entity + a breadcrumb
  // trail. Lets search engines attach this page to the {ticker} entity and
  // surface it for "{ticker} stock news" / "{company} news impact" queries.
  // Newest scored catalyst = the last time this page's own content actually
  // changed. Deploy time would be a lie, and `dateModified` is the signal that
  // decides whether a crawler comes back to a page it already has.
  const lastCatalystAt =
    events.reduce<string | null>(
      (max, e) => (e.publishedAt && (!max || e.publishedAt > max) ? e.publishedAt : max),
      null,
    ) ?? null;

  const jsonLd = {
    "@context": "https://schema.org",
    "@graph": [
      {
        "@type": ["Corporation", "Organization"],
        // Always identified, so the WebPage can point at this node instead of
        // repeating a second, unlinked copy of the company.
        "@id": `${canonicalUrl}#company`,
        name: companyName,
        tickerSymbol: symbol,
        url: profile?.website || canonicalUrl,
        ...(profile?.website ? { sameAs: [profile.website] } : {}),
        ...(exchange ? { identifier: `${exchange}:${symbol}` } : {}),
        ...(profile?.industry ? { industry: profile.industry } : {}),
        ...(profile?.image && !profile.defaultImage ? { logo: profile.image } : {}),
        ...(profile?.description ? { description: profile.description } : {}),
      },
      {
        "@type": "WebPage",
        "@id": canonicalUrl,
        url: canonicalUrl,
        name: `${symbol} Stock News & Catalysts — ${companyName}`,
        description: `Scored news catalysts, price chart, sentiment, key statistics and connected tickers for ${companyName} (${symbol}).`,
        about: { "@id": `${canonicalUrl}#company` },
        ...(lastCatalystAt ? { dateModified: lastCatalystAt } : {}),
        isPartOf: {
          "@type": "WebSite",
          name: "News Impact Screener",
          url: SITE_BASE_URL,
        },
        primaryImageOfPage:
          profile?.image && !profile.defaultImage ? profile.image : undefined,
      },
      {
        "@type": "BreadcrumbList",
        itemListElement: [
          { "@type": "ListItem", position: 1, name: "Home", item: SITE_BASE_URL },
          { "@type": "ListItem", position: 2, name: "Quotes", item: `${SITE_BASE_URL}/quote` },
          { "@type": "ListItem", position: 3, name: `${symbol} — ${companyName}`, item: canonicalUrl },
        ],
      },
    ],
  };

  return (
    <div className="mx-auto flex w-full min-w-0 max-w-7xl flex-col gap-8 px-4 py-8 sm:px-6 lg:px-8">
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />
      {/* ── Breadcrumb (entity trail for crawlers + orientation) ──── */}
      <nav aria-label="Breadcrumb" className="-mb-4 text-xs text-muted-foreground">
        <ol className="flex flex-wrap items-center gap-1.5">
          <li>
            <Link href="/" className="hover:text-foreground">Home</Link>
          </li>
          <li aria-hidden className="text-muted-foreground/50">/</li>
          <li>
            <Link href="/quote" className="hover:text-foreground">Quotes</Link>
          </li>
          <li aria-hidden className="text-muted-foreground/50">/</li>
          <li className="font-medium text-foreground" aria-current="page">
            {symbol}
          </li>
        </ol>
      </nav>
      {/* ── Header ───────────────────────────────────────────────── */}
      <header className="flex flex-wrap items-end justify-between gap-4 border-b border-border/60 pb-5">
        <div className="flex items-center gap-4">
          {profile?.image ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={profile.image}
              alt={`${companyName} (${symbol}) logo`}
              width={48}
              height={48}
              className="h-12 w-12 shrink-0 rounded-md border border-border bg-muted object-contain"
            />
          ) : null}
          <div className="min-w-0">
            <p className="font-mono text-[11px] uppercase tracking-[0.2em] text-amber-500/80">
              {exchange ?? "Quote"}
            </p>
            <h1 className="text-2xl font-bold leading-tight tracking-tight md:text-3xl">
              {companyName} <span className="font-mono text-muted-foreground">{symbol}</span>
            </h1>
          </div>
        </div>
        <div className="text-right">
          <p className="font-mono text-3xl font-semibold tabular-nums">
            {price != null ? fmtFixed(price, 2) : "—"}
            {profile?.currency ? <span className="ml-1 text-sm text-muted-foreground">{profile.currency}</span> : null}
          </p>
          <p className={`font-mono text-sm tabular-nums ${tone === "up" ? "text-emerald-500" : tone === "down" ? "text-rose-500" : "text-muted-foreground"}`}>
            {change != null ? `${change > 0 ? "+" : ""}${fmtFixed(change, 2)}` : "—"}
            {changePct != null ? ` (${changePct > 0 ? "+" : ""}${fmtFixed(changePct, 2)}%)` : ""}
          </p>
        </div>
      </header>

      {/* ── The unique summary (see CatalystLede) ─────────────────── */}
      <CatalystLede
        symbol={symbol}
        name={companyName}
        events={events}
        top={ledeTop}
      />

      <QuoteTabs
        tabs={[
          {
            id: "overview",
            label: "Overview",
            panel: (
              <section className="grid gap-6 lg:grid-cols-[1.6fr_1fr]">
                <div>
                  <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    Price & news catalysts
                  </h2>
                  <TickerImpactChart symbol={symbol} bars={bars} events={chartEvents} />

                  {/* Key statistics — the numbers you read the chart against, so
                      they sit directly under it rather than further down. */}
                  <h2 className="mb-3 mt-6 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    Key statistics
                  </h2>
                  <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-4">
                    <Stat label="Market cap" value={fmtCompact(profile?.marketCap)} />
                    <Stat label="P/E" value={fmtFixed(qnum(quote, "pe"))} />
                    <Stat label="EPS" value={fmtFixed(qnum(quote, "eps"))} />
                    <Stat label="Beta" value={fmtFixed(profile?.beta, 2)} />
                    <Stat label="52W range" value={profile?.range ?? "—"} />
                    <Stat label="Day range" value={qnum(quote, "dayLow") != null ? `${fmtFixed(qnum(quote, "dayLow"))}–${fmtFixed(qnum(quote, "dayHigh"))}` : "—"} />
                    <Stat label="Open" value={fmtFixed(qnum(quote, "open"))} />
                    <Stat label="Prev close" value={fmtFixed(qnum(quote, "previousClose"))} />
                    <Stat label="Volume" value={fmtCompact(qnum(quote, "volume") ?? profile?.volume)} />
                    <Stat label="Avg volume" value={fmtCompact(qnum(quote, "avgVolume") ?? profile?.averageVolume)} />
                    <Stat label="Dividend" value={fmtFixed(profile?.lastDividend, 2)} />
                    <Stat label="IPO" value={profile?.ipoDate ?? "—"} />
                  </div>
                </div>
                <div>
                  <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    What moved {symbol}
                  </h2>
                  {moved.length === 0 ? (
                    <p className="rounded-lg border border-border bg-card p-4 text-sm text-muted-foreground">
                      No scored catalysts in the window yet.
                    </p>
                  ) : (
                    <ol className="flex flex-col gap-2">
                      {moved.map((e, i) => (
                        <li key={e.articleId} className="rounded-lg border border-border bg-card p-3">
                          <div className="flex items-start gap-2">
                            <span className="mt-0.5 font-mono text-xs text-muted-foreground">{i + 1}</span>
                            <div className="min-w-0 flex-1">
                              <a
                                href={e.url ?? "#"}
                                target="_blank"
                                rel="noreferrer"
                                className="line-clamp-2 text-sm font-medium text-foreground hover:underline"
                              >
                                {e.title}
                              </a>
                              <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-muted-foreground">
                                {e.sentiment != null ? (
                                  <span className={e.sentiment > 0 ? "text-emerald-500" : e.sentiment < 0 ? "text-rose-500" : ""}>
                                    {e.sentiment >= 0 ? "+" : ""}{e.sentiment.toFixed(2)}
                                  </span>
                                ) : null}
                                <span>impact {e.impactMagnitude.toFixed(1)}</span>
                                {e.movePct != null ? (
                                  <span className={e.movePct >= 0 ? "text-emerald-500" : "text-rose-500"}>
                                    {e.movePct >= 0 ? "▲" : "▼"}{Math.abs(e.movePct).toFixed(1)}%
                                  </span>
                                ) : null}
                              </div>
                            </div>
                          </div>
                        </li>
                      ))}
                    </ol>
                  )}

                  <Link
                    href={`/articles?tag=${encodeURIComponent(symbol)}`}
                    className="mt-3 inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
                  >
                    Show more {symbol} articles →
                  </Link>

                  <div className="mt-6">
                    <h2 className="mb-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                      Profile
                    </h2>
                    <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-xs">
                      <dt className="text-muted-foreground">Sector</dt>
                      <dd className="text-right">{profile?.sector ?? "—"}</dd>
                      <dt className="text-muted-foreground">Industry</dt>
                      <dd className="text-right">{profile?.industry ?? "—"}</dd>
                      <dt className="text-muted-foreground">CEO</dt>
                      <dd className="text-right">{profile?.ceo ?? "—"}</dd>
                      <dt className="text-muted-foreground">Employees</dt>
                      <dd className="text-right tabular-nums">{profile?.fullTimeEmployees ?? "—"}</dd>
                      <dt className="text-muted-foreground">Country</dt>
                      <dd className="text-right">{profile?.country ?? "—"}</dd>
                    </dl>
                    {profile?.website ? (
                      <a href={profile.website} target="_blank" rel="noreferrer" className="mt-2 inline-block text-xs font-medium text-primary hover:underline">
                        {profile.website.replace(/^https?:\/\//, "")}
                      </a>
                    ) : null}
                    {profile?.description ? (
                      <p className="mt-3 max-h-48 overflow-y-auto text-xs leading-relaxed text-muted-foreground">
                        {profile.description}
                      </p>
                    ) : null}
                  </div>
                </div>
              </section>
            ),
          },
          // Only a tab when there is a vote to show — an empty tab reads as a
          // broken one.
          ...(pricedIn
            ? [
                {
                  id: "priced-in",
                  label: "Priced in",
                  panel: (
                    <section>
                      <h2 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                        What the price already reflects
                      </h2>
                      <p className="mb-3 max-w-[70ch] text-xs text-muted-foreground">
                        Analysts publish price targets on {symbol}, and they
                        disagree. Where the share price actually sits among them
                        shows which of their arguments the market is buying —
                        and which it is ignoring.
                      </p>
                      <PricedInPanel
                        vote={pricedIn}
                        livePrice={price}
                        membersOnly
                      />
                    </section>
                  ),
                },
              ]
            : []),
          {
            id: "chart",
            label: "Chart",
            wide: true,
            panel: (
              <section>
                <h2 className="mb-1 px-4 text-xs font-semibold uppercase tracking-wide text-muted-foreground sm:px-6 lg:px-8">
                  Chart {symbol} yourself
                </h2>
                <p className="mb-3 max-w-[70ch] px-4 text-xs text-muted-foreground sm:px-6 lg:px-8">
                  Daily OHLCV with SMA overlays and session pivots. Draw your
                  levels and trendlines on it, or ask the AI analyst what the
                  price is reacting to.
                </p>
                <QuoteChartWorkspace symbol={symbol} />
              </section>
            ),
          },
          {
            id: "network",
            label: "Network",
            wide: true,
            panel: (
              <section>
                <h2 className="mb-1 px-4 text-xs font-semibold uppercase tracking-wide text-muted-foreground sm:px-6 lg:px-8">
                  Who {symbol} is connected to
                </h2>
                <p className="mb-3 max-w-[70ch] px-4 text-xs text-muted-foreground sm:px-6 lg:px-8">
                  Suppliers, customers, partners and competitors, derived from
                  what the news actually says about {companyName} — not a sector
                  bucket. Click an edge to see the articles that established the
                  link.
                </p>
                <QuoteRelationshipGraph symbol={symbol} />
              </section>
            ),
          },
        ]}
      />

      {/* ── Connected tickers (server-rendered link graph) ────────── */}
      <PeerLinks symbol={symbol} companyName={companyName} peers={peers} />

      {lastCatalystAt ? (
        <p className="text-xs text-muted-foreground">
          Latest scored catalyst for {symbol}:{" "}
          <time dateTime={lastCatalystAt}>{fmtDay(lastCatalystAt)}</time>.
        </p>
      ) : null}

      {/* ── Briefing CTA ──────────────────────────────────────────── */}
      <section>
        <ArticleBriefingCTA tickers={[symbol]} tags={[]} source="quote_page" />
      </section>
    </div>
  );
}
