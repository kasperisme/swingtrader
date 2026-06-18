import type { Metadata } from "next";
import Link from "next/link";
import {
  fmpGetCompanyProfile,
  fmpGetQuote,
  fmpGetOhlc,
  type FmpCompanyProfile,
  type FmpOhlcBar,
} from "@/app/actions/fmp";
import { getTickerImpactNews, type ScoredNewsEvent } from "@/lib/quote/ticker-impact";
import {
  TickerImpactChart,
  type ChartEvent,
} from "./_components/ticker-impact-chart";
import { ArticleBriefingCTA } from "@/app/articles/[slug]/_components/article-briefing-cta";

const SITE_BASE_URL = (
  process.env.NEXT_PUBLIC_SITE_URL ?? "https://www.newsimpactscreener.com"
).replace(/\/$/, "");

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

export async function generateMetadata({
  params,
}: {
  params: Promise<{ symbol: string }>;
}): Promise<Metadata> {
  const symbol = normSymbol((await params).symbol);
  const res = await fmpGetCompanyProfile(symbol);
  const profile = res.ok ? res.data : null;
  const name = profile?.companyName || symbol;
  const known = Boolean(profile?.companyName);

  const title = `${symbol} — ${name} News Impact, Chart & Catalysts`;
  const description = known
    ? `What's actually moving ${name} (${symbol}): an interactive price chart with scored news catalysts, sentiment, key statistics, and company profile — from the News Impact Screener.`
    : `${symbol} stock: news impact score, scored catalysts, price chart, sentiment, and key statistics from the News Impact Screener.`;

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
    // Don't let thin/unknown-symbol pages dilute the index.
    robots: known
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

export default async function QuotePage({
  params,
}: {
  params: Promise<{ symbol: string }>;
}) {
  const symbol = normSymbol((await params).symbol);

  const [profileRes, quoteRes, ohlcRes, events] = await Promise.all([
    fmpGetCompanyProfile(symbol),
    fmpGetQuote(symbol),
    fmpGetOhlc(symbol, "1day"),
    getTickerImpactNews(symbol, { days: 365, limit: 150, perBucket: 2 }),
  ]);

  const profile: FmpCompanyProfile | null = profileRes.ok ? profileRes.data : null;
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

  const price = qnum(quote, "price") ?? profile?.price ?? null;
  const change = qnum(quote, "change") ?? profile?.change ?? null;
  const changePct = qnum(quote, "changePercentage", "changesPercentage") ?? profile?.changePercentage ?? null;
  const companyName = profile?.companyName ?? symbol;
  const exchange = profile?.exchange ?? profile?.exchangeFullName ?? null;
  const tone = (change ?? 0) > 0 ? "up" : (change ?? 0) < 0 ? "down" : undefined;

  const newsFeed = [...events]
    .filter((e) => e.title)
    .sort((a, b) => (b.publishedAt ?? "").localeCompare(a.publishedAt ?? ""))
    .slice(0, 12);

  const canonicalUrl = `${SITE_BASE_URL}/quote/${symbol}`;

  // Structured data: the company as a tradable financial entity + a breadcrumb
  // trail. Lets search engines attach this page to the {ticker} entity and
  // surface it for "{ticker} stock news" / "{company} news impact" queries.
  const jsonLd = {
    "@context": "https://schema.org",
    "@graph": [
      {
        "@type": ["Corporation", "Organization"],
        name: companyName,
        tickerSymbol: symbol,
        url: profile?.website || canonicalUrl,
        ...(profile?.image && !profile.defaultImage ? { logo: profile.image } : {}),
        ...(profile?.description ? { description: profile.description } : {}),
        ...(exchange ? { "@id": `${canonicalUrl}#company` } : {}),
      },
      {
        "@type": "WebPage",
        "@id": canonicalUrl,
        url: canonicalUrl,
        name: `${companyName} (${symbol}) — News Impact, Chart & Catalysts`,
        description: `Scored news catalysts, price chart, sentiment, and key statistics for ${companyName} (${symbol}).`,
        about: { "@type": "Corporation", name: companyName, tickerSymbol: symbol },
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
          { "@type": "ListItem", position: 2, name: "Quotes", item: `${SITE_BASE_URL}/articles` },
          { "@type": "ListItem", position: 3, name: `${symbol} — ${companyName}`, item: canonicalUrl },
        ],
      },
    ],
  };

  return (
    <div className="mx-auto flex w-full min-w-0 max-w-6xl flex-col gap-8 px-4 py-8 sm:px-6 lg:px-8">
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
            <Link href="/articles" className="hover:text-foreground">News</Link>
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

      {/* ── HERO: impact-scored news on the chart ─────────────────── */}
      <section className="grid gap-6 lg:grid-cols-[1.6fr_1fr]">
        <div>
          <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Price & news catalysts
          </h2>
          <TickerImpactChart symbol={symbol} bars={bars} events={chartEvents} />
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
        </div>
      </section>

      {/* ── Key statistics ────────────────────────────────────────── */}
      <section>
        <h2 className="mb-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Key statistics
        </h2>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
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
      </section>

      {/* ── News feed ─────────────────────────────────────────────── */}
      <section className="grid gap-6 lg:grid-cols-[1.6fr_1fr]">
        <div>
          <h2 className="mb-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Latest {symbol} news
          </h2>
          {newsFeed.length === 0 ? (
            <p className="text-sm text-muted-foreground">No recent tagged news.</p>
          ) : (
            <ul className="divide-y divide-border rounded-xl border border-border bg-card">
              {newsFeed.map((e) => (
                <li key={e.articleId} className="p-3">
                  <a href={e.url ?? "#"} target="_blank" rel="noreferrer" className="text-sm font-medium text-foreground hover:underline">
                    {e.title}
                  </a>
                  <p className="mt-0.5 text-[11px] text-muted-foreground">
                    {e.source ?? "—"}
                    {e.publishedAt ? ` · ${new Date(e.publishedAt).toLocaleDateString()}` : ""}
                    {e.sentiment != null ? (
                      <span className={`ml-2 ${e.sentiment > 0 ? "text-emerald-500" : e.sentiment < 0 ? "text-rose-500" : ""}`}>
                        {e.sentiment >= 0 ? "+" : ""}{e.sentiment.toFixed(2)}
                      </span>
                    ) : null}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* ── Profile + briefing CTA ─────────────────────────────── */}
        <div className="flex flex-col gap-6">
          <div>
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

          <ArticleBriefingCTA tickers={[symbol]} tags={[]} source="quote_page" />
        </div>
      </section>
    </div>
  );
}
