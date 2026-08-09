import { Suspense } from "react";
import Link from "next/link";
import { notFound } from "next/navigation";
import type { Metadata } from "next";
import { ArrowLeft, ArrowRight, Search, X } from "lucide-react";
import { listCoveredTickers, type CoveredTicker } from "@/app/actions/quotes";
import { TickerLogo } from "@/components/ticker-logo";
import { SentimentMeter } from "./_components/sentiment-meter";

// Must match the root layout's metadataBase host exactly — the site canonicalises
// on WWW, and a bare-host canonical here would split signals for this page alone.
const SITE = (
  process.env.NEXT_PUBLIC_SITE_URL ?? "https://www.newsimpactscreener.com"
).replace(/\/$/, "");

const WINDOW_DAYS = 30;
const PAGE_SIZE = 50;

type SearchParams = { q?: string; page?: string };

function parseQuery(raw: string | undefined): string {
  // Cap length so a pathological query string can't become the page <title>.
  return typeof raw === "string" ? raw.trim().slice(0, 64) : "";
}

function parsePage(raw: string | undefined): number {
  const n = Number.parseInt(String(raw ?? "1"), 10);
  return Number.isFinite(n) && n > 1 ? n : 1;
}

/** The shape gate the sitemap and the directory RPC both use. Guards the
 *  "go straight to the quote page" offer so a query like "%" or "big oil"
 *  doesn't get pitched as a symbol. */
const SYMBOL_RE = /^[A-Z][A-Z0-9.\-]{0,11}$/;

/** Builds a /quote URL, dropping the defaults so page 1 has a clean address. */
function hrefFor(q: string, page: number): string {
  const sp = new URLSearchParams();
  if (q) sp.set("q", q);
  if (page > 1) sp.set("page", String(page));
  const qs = sp.toString();
  return qs ? `/quote?${qs}` : "/quote";
}

export async function generateMetadata({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}): Promise<Metadata> {
  const params = await searchParams;
  const q = parseQuery(params.q);
  const page = parsePage(params.page);

  const title = q
    ? `Ticker search: ${q}`
    : page > 1
      ? `Quotes — page ${page}`
      : "Quotes";

  return {
    title, // root layout template supplies the site suffix
    description:
      "Every ticker we score, ranked by how much impact-scored news it is carrying right now. Open any symbol for its price chart with the news catalysts that moved it.",
    // Self-canonical per page, so a deep page is never folded into page 1.
    alternates: { canonical: `${SITE}${hrefFor(q, page)}` },
    // Only the bare directory is worth indexing. Search results are unbounded
    // and near-duplicate; deep pages are thin, and an out-of-range one renders
    // not-found under a 200 (the shell has already streamed by the time the
    // range is known), which would read as a soft 404. `follow` keeps every one
    // of them a crawl path to the /quote/[symbol] pages, which is the point.
    robots:
      q || page > 1 ? { index: false, follow: true } : { index: true, follow: true },
  };
}

/** Day-granular data, so this stays honest and says "today" rather than "4h". */
function freshness(lastDay: string | null): string {
  if (!lastDay) return "—";
  const then = new Date(`${lastDay}T00:00:00Z`);
  if (Number.isNaN(then.getTime())) return "—";
  const now = new Date();
  const days = Math.floor(
    (Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()) -
      Date.UTC(then.getUTCFullYear(), then.getUTCMonth(), then.getUTCDate())) /
      86_400_000,
  );
  if (days <= 0) return "today";
  if (days === 1) return "1d";
  return `${days}d`;
}

function TickerRow({ t, rank, index }: { t: CoveredTicker; rank: number; index: number }) {
  const subtitle = t.companyName ?? t.sector ?? null;

  return (
    <li
      className="animate-screening-row-in"
      // Staggered entry, capped so row 50 doesn't wait 2.5s. Reused from the
      // screenings list so the two ranked tables feel like one system.
      style={{ animationDelay: `${Math.min(index, 12) * 22}ms` }}
    >
      <Link
        href={`/quote/${t.ticker}`}
        className="group grid grid-cols-[1.5rem_2.25rem_minmax(0,1fr)_auto_auto] items-center gap-x-3 border-b border-border/60 py-3 pr-1 transition-colors hover:bg-muted/60 focus-visible:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500/60 sm:grid-cols-[2.5rem_2.25rem_minmax(0,1fr)_6rem_auto] sm:gap-x-4"
      >
        <span className="font-mono text-xs tabular-nums text-muted-foreground">
          {rank}
        </span>

        <TickerLogo symbol={t.ticker} />

        <span className="min-w-0">
          <span className="block truncate font-mono text-sm font-semibold tracking-tight text-foreground transition-colors group-hover:text-amber-600 dark:group-hover:text-amber-400">
            {t.ticker}
          </span>
          <span className="mt-0.5 block truncate text-xs text-muted-foreground">
            {subtitle ?? <span className="text-muted-foreground">—</span>}
          </span>
        </span>

        {/* Coverage + freshness read as one fact, so they share a column. This
            is the value the list is ranked by, so it stays visible on mobile —
            hiding it would leave a ranked list with its ranking invisible. */}
        <span className="text-right">
          <span className="block font-mono text-sm tabular-nums text-foreground">
            {t.scoredCount.toLocaleString()}
          </span>
          <span className="mt-0.5 block font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
            {freshness(t.lastDay)}
          </span>
        </span>

        <SentimentMeter value={t.avgSentiment} />
      </Link>
    </li>
  );
}

/** A plain GET form — no client JS, so search works on the first paint and each
 *  query is a real, shareable URL. */
function SearchForm({ q }: { q: string }) {
  return (
    <form action="/quote" method="GET" role="search" className="mt-6">
      <label
        htmlFor="quote-search"
        className="mb-2 block font-mono text-[10px] uppercase tracking-[0.2em] text-muted-foreground"
      >
        Find a ticker
      </label>
      <div className="flex items-center gap-2">
        <div className="relative min-w-0 flex-1">
          <Search
            className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden
          />
          <input
            id="quote-search"
            type="search"
            name="q"
            defaultValue={q}
            maxLength={64}
            placeholder="NVDA, chevron, semiconductor…"
            aria-describedby="quote-search-hint"
            className="h-11 w-full rounded-lg border border-border bg-card/60 pl-10 pr-3 text-base outline-none transition-colors placeholder:text-muted-foreground hover:border-border focus-visible:border-amber-500/60 focus-visible:ring-2 focus-visible:ring-amber-500/30 sm:text-sm"
          />
        </div>
        <button
          type="submit"
          className="h-11 shrink-0 cursor-pointer rounded-lg bg-amber-500 px-5 text-sm font-semibold text-amber-950 transition-colors hover:bg-amber-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500/60"
        >
          Search
        </button>
        {q && (
          <Link
            href="/quote"
            aria-label="Clear search"
            className="inline-flex h-11 shrink-0 cursor-pointer items-center gap-1.5 rounded-lg border border-border px-3.5 text-sm text-muted-foreground transition-colors hover:bg-muted/60 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500/60"
          >
            <X className="h-3.5 w-3.5" aria-hidden />
            <span className="hidden sm:inline">Clear</span>
          </Link>
        )}
      </div>
      <p id="quote-search-hint" className="mt-2 text-xs text-muted-foreground">
        Symbols match from the start, company names anywhere.
      </p>
    </form>
  );
}

function Pagination({ q, page, total }: { q: string; page: number; total: number }) {
  const lastPage = Math.max(1, Math.ceil(total / PAGE_SIZE));
  if (lastPage <= 1) return null;

  // A window around the current page — 74 pages of numbers would out-weigh the
  // results themselves, and crawlers only need a connected path through them.
  const from = Math.max(1, Math.min(page - 2, lastPage - 4));
  const to = Math.min(lastPage, Math.max(page + 2, 5));
  const pages: number[] = [];
  for (let p = from; p <= to; p++) pages.push(p);

  // 44px min touch target on every control (h-11 = 2.75rem).
  const step =
    "inline-flex h-11 items-center gap-1.5 rounded-lg border border-border px-3.5 text-sm transition-colors hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500/60 cursor-pointer";
  const stepOff =
    "inline-flex h-11 items-center gap-1.5 rounded-lg border border-border/50 px-3.5 text-sm text-muted-foreground/40";
  const num =
    "inline-flex h-11 w-11 items-center justify-center rounded-lg border border-border font-mono text-sm tabular-nums transition-colors hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500/60 cursor-pointer";

  return (
    <nav
      aria-label="Pagination"
      className="mt-8 flex flex-col items-center justify-between gap-4 sm:flex-row"
    >
      <p className="order-2 font-mono text-xs tabular-nums text-muted-foreground sm:order-1">
        Page {page.toLocaleString()} of {lastPage.toLocaleString()}
      </p>
      <div className="order-1 flex flex-wrap items-center justify-center gap-2 sm:order-2">
        {page > 1 ? (
          <Link href={hrefFor(q, page - 1)} rel="prev" className={step}>
            <ArrowLeft className="h-3.5 w-3.5" aria-hidden />
            <span className="hidden sm:inline">Previous</span>
          </Link>
        ) : (
          <span className={stepOff} aria-hidden>
            <ArrowLeft className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">Previous</span>
          </span>
        )}

        {pages.map((p) =>
          p === page ? (
            <span
              key={p}
              aria-current="page"
              className="inline-flex h-11 w-11 items-center justify-center rounded-lg border border-amber-500/50 bg-amber-500/10 font-mono text-sm font-semibold tabular-nums text-amber-600 dark:text-amber-400"
            >
              {p}
            </span>
          ) : (
            <Link key={p} href={hrefFor(q, p)} className={num}>
              {p}
            </Link>
          ),
        )}

        {page < lastPage ? (
          <Link href={hrefFor(q, page + 1)} rel="next" className={step}>
            <span className="hidden sm:inline">Next</span>
            <ArrowRight className="h-3.5 w-3.5" aria-hidden />
          </Link>
        ) : (
          <span className={stepOff} aria-hidden>
            <span className="hidden sm:inline">Next</span>
            <ArrowRight className="h-3.5 w-3.5" />
          </span>
        )}
      </div>
    </nav>
  );
}

function ColumnLabels() {
  const label =
    "font-mono text-[10px] uppercase tracking-[0.2em] text-muted-foreground";
  return (
    <div
      aria-hidden
      className="grid grid-cols-[1.5rem_2.25rem_minmax(0,1fr)_auto_auto] items-center gap-x-3 border-b border-border pb-2 pr-1 sm:grid-cols-[2.5rem_2.25rem_minmax(0,1fr)_6rem_auto] sm:gap-x-4"
    >
      <span className={label}>#</span>
      <span />
      <span className={label}>Ticker</span>
      <span className={`${label} text-right`}>Scored</span>
      <span className={`${label} text-right`}>Sentiment</span>
    </div>
  );
}

function DirectorySkeleton() {
  return (
    <div aria-hidden>
      <div className="h-4 w-40 animate-pulse rounded bg-muted/60" />
      <div className="mt-6 space-y-px">
        {Array.from({ length: 14 }, (_, i) => (
          <div
            key={i}
            className="flex items-center gap-4 border-b border-border/40 py-3"
          >
            <div className="h-9 w-9 shrink-0 animate-pulse rounded-md bg-muted/60" />
            <div className="min-w-0 flex-1 space-y-1.5">
              <div className="h-3.5 w-16 animate-pulse rounded bg-muted/60" />
              <div className="h-3 w-40 animate-pulse rounded bg-muted/40" />
            </div>
            <div className="h-3.5 w-24 animate-pulse rounded bg-muted/40" />
          </div>
        ))}
      </div>
    </div>
  );
}

async function Directory({ q, page }: { q: string; page: number }) {
  const { items, total } = await listCoveredTickers({
    days: WINDOW_DAYS,
    limit: PAGE_SIZE,
    offset: (page - 1) * PAGE_SIZE,
    search: q,
  });

  if (items.length === 0) {
    // Past the last page there is nothing to show and nothing to index — a real
    // 404 beats an indexable empty page that reads as a soft 404.
    if (page > 1) notFound();

    const symbol = q.toUpperCase();
    return (
      <div className="border-l-2 border-amber-500/60 py-6 pl-5">
        {q ? (
          <>
            <p className="text-sm text-foreground">
              Nothing matching{" "}
              <span className="font-mono font-semibold">{q}</span> has scored
              coverage in the last {WINDOW_DAYS} days.
            </p>
            <p className="mt-3 max-w-[60ch] text-sm leading-relaxed text-muted-foreground">
              {SYMBOL_RE.test(symbol) ? (
                <>
                  Quote pages render for any symbol, so you can still go straight
                  to{" "}
                  <Link
                    href={`/quote/${encodeURIComponent(symbol)}`}
                    className="font-mono text-foreground underline decoration-amber-500/50 underline-offset-4 transition-colors hover:decoration-amber-500"
                  >
                    /quote/{symbol}
                  </Link>
                  , or{" "}
                </>
              ) : (
                <>Try a ticker symbol or a company name, or </>
              )}
              <Link
                href="/quote"
                className="underline decoration-amber-500/50 underline-offset-4 transition-colors hover:text-foreground hover:decoration-amber-500"
              >
                browse the full directory
              </Link>
              .
            </p>
          </>
        ) : (
          <p className="text-sm text-muted-foreground">
            No scored ticker coverage in the last {WINDOW_DAYS} days. Check back
            once the next scoring run lands.
          </p>
        )}
      </div>
    );
  }

  // ItemList so crawlers read this as the parent of the /quote/[symbol] set
  // rather than N loose links — the hub half of the hub-and-spoke. Positions are
  // absolute across pages, so page 2 continues where page 1 stopped.
  const offset = (page - 1) * PAGE_SIZE;
  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "ItemList",
    name: q ? `Tickers matching "${q}"` : "Tickers with scored news coverage",
    numberOfItems: total,
    itemListElement: items.map((t, i) => ({
      "@type": "ListItem",
      position: offset + i + 1,
      url: `${SITE}/quote/${t.ticker}`,
      name: t.companyName ? `${t.ticker} — ${t.companyName}` : t.ticker,
    })),
  };

  const first = offset + 1;
  const last = offset + items.length;

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />

      <p className="mb-5 font-mono text-xs tabular-nums text-muted-foreground">
        {q ? (
          <>
            <span className="text-foreground">{total.toLocaleString()}</span>{" "}
            match{total === 1 ? "" : "es"} for {q}
            {total > items.length && (
              <>
                {" "}
                · showing {first}–{last}
              </>
            )}
          </>
        ) : (
          <>
            <span className="text-foreground">
              {first.toLocaleString()}–{last.toLocaleString()}
            </span>{" "}
            of {total.toLocaleString()} tickers · ranked by scored coverage
          </>
        )}
      </p>

      <ColumnLabels />
      <ul>
        {items.map((t, i) => (
          <TickerRow key={t.ticker} t={t} rank={offset + i + 1} index={i} />
        ))}
      </ul>

      <Pagination q={q} page={page} total={total} />
    </>
  );
}

export default async function QuotesIndex({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const params = await searchParams;
  const q = parseQuery(params.q);
  const page = parsePage(params.page);

  const breadcrumbLd = {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: [
      { "@type": "ListItem", position: 1, name: "Home", item: SITE },
      { "@type": "ListItem", position: 2, name: "Quotes", item: `${SITE}/quote` },
    ],
  };

  return (
    <main className="mx-auto w-full max-w-4xl px-4 py-10 sm:px-6">
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(breadcrumbLd) }}
      />

      <header className="mb-10 border-b border-border/60 pb-8">
        {/* Same eyebrow rule as /articles — the two public boards read as one
            product rather than two designers' pages. */}
        <div className="mb-3 flex items-center justify-between gap-4">
          <p className="inline-flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.2em] text-amber-500/80">
            <span className="h-px w-6 bg-amber-500/60" />
            The Board
          </p>
          <span className="shrink-0 rounded-full border border-border px-2.5 py-1 font-mono text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
            {WINDOW_DAYS}-day window
          </span>
        </div>
        <h1 className="text-4xl font-bold leading-[1.05] tracking-tighter sm:text-5xl">
          Quotes
        </h1>
        <p className="mt-4 max-w-[58ch] text-sm leading-relaxed text-muted-foreground">
          Every ticker we score, ranked by how much impact-scored news it is
          carrying. Open one for its price chart with the catalysts that actually
          moved it — each event scored, not just headlined.
        </p>
        <SearchForm q={q} />
      </header>

      {/* Keyed so switching query or page swaps in the skeleton rather than
          holding the previous page's rows while the new one resolves. */}
      <Suspense key={`${q}:${page}`} fallback={<DirectorySkeleton />}>
        <Directory q={q} page={page} />
      </Suspense>

      <p className="mt-12 border-t border-border/60 pt-6 text-sm text-muted-foreground">
        Looking for the stories behind the moves?{" "}
        <Link
          href="/topics"
          className="underline decoration-amber-500/50 underline-offset-4 transition-colors hover:text-foreground hover:decoration-amber-500"
        >
          Browse topics
        </Link>{" "}
        or read the{" "}
        <Link
          href="/articles"
          className="underline decoration-amber-500/50 underline-offset-4 transition-colors hover:text-foreground hover:decoration-amber-500"
        >
          scored article feed
        </Link>
        .
      </p>
    </main>
  );
}
