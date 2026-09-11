import { Suspense } from "react";
import Link from "next/link";
import { notFound } from "next/navigation";
import type { Metadata } from "next";
import { ArrowLeft, ArrowRight, Search, X } from "lucide-react";
import { listCeos, type CeoListing } from "@/lib/ceos";
import { TickerLogo } from "@/components/ticker-logo";
import { SITE_NAME, SITE_URL } from "@/lib/site";
import { fmtUsdCompact } from "./_format";

const PAGE_SIZE = 50;

const CEOS_DESCRIPTION =
  "Who runs every NYSE and NASDAQ company we cover — each CEO's title, the rest of the leadership team, and what they were actually paid according to the company's own SEC proxy filings.";

type SearchParams = { q?: string; page?: string };

function parseQuery(raw: string | undefined): string {
  return typeof raw === "string" ? raw.trim().slice(0, 64) : "";
}

function parsePage(raw: string | undefined): number {
  const n = Number.parseInt(String(raw ?? "1"), 10);
  return Number.isFinite(n) && n > 1 ? n : 1;
}

function hrefFor(q: string, page: number): string {
  const sp = new URLSearchParams();
  if (q) sp.set("q", q);
  if (page > 1) sp.set("page", String(page));
  const qs = sp.toString();
  return qs ? `/ceos?${qs}` : "/ceos";
}

export async function generateMetadata({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}): Promise<Metadata> {
  const params = await searchParams;
  const q = parseQuery(params.q);
  const page = parsePage(params.page);
  const title = q ? `CEO search: ${q}` : page > 1 ? `CEOs — page ${page}` : "CEO Directory";
  return {
    title,
    description: CEOS_DESCRIPTION,
    alternates: { canonical: `${SITE_URL}${hrefFor(q, page)}` },
    // Same rule as the /quote hub: only the bare directory asks to be indexed;
    // search results and deep pages stay followable crawl paths to the people.
    robots: q || page > 1 ? { index: false, follow: true } : { index: true, follow: true },
    openGraph: {
      type: "website",
      url: `${SITE_URL}/ceos`,
      title: "CEO Directory",
      description: CEOS_DESCRIPTION,
    },
  };
}

function CeoRow({ c, rank, index }: { c: CeoListing; rank: number; index: number }) {
  const primary = c.symbols[0];
  return (
    <li
      className="animate-screening-row-in"
      style={{ animationDelay: `${Math.min(index, 12) * 22}ms` }}
    >
      <Link
        href={`/ceos/${c.slug}`}
        className="group grid grid-cols-[1.5rem_2.25rem_minmax(0,1fr)_auto] items-center gap-x-3 border-b border-border/60 py-3 pr-1 transition-colors hover:bg-muted/60 focus-visible:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500/60 sm:grid-cols-[2.5rem_2.25rem_minmax(0,1fr)_6rem_7rem] sm:gap-x-4"
      >
        <span className="font-mono text-xs tabular-nums text-muted-foreground">{rank}</span>
        {primary ? <TickerLogo symbol={primary} /> : <span />}
        <span className="min-w-0">
          <span className="block truncate text-sm font-semibold tracking-tight text-foreground transition-colors group-hover:text-amber-600 dark:group-hover:text-amber-400">
            {c.name}
          </span>
          <span className="mt-0.5 block truncate text-xs text-muted-foreground">
            {c.primaryCompany ?? primary}
            <span className="font-mono"> · {c.symbols.join(", ")}</span>
          </span>
        </span>
        {/* Market cap is the ranking, so it stays on mobile; pay drops. */}
        <span className="hidden text-right sm:block">
          <span className="block font-mono text-sm tabular-nums text-foreground">
            {fmtUsdCompact(c.latestPay)}
          </span>
          <span className="mt-0.5 block font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
            {c.latestPayYear ? `pay ${c.latestPayYear}` : "no proxy"}
          </span>
        </span>
        <span className="text-right">
          <span className="block font-mono text-sm tabular-nums text-foreground">
            {fmtUsdCompact(c.marketCap)}
          </span>
          <span className="mt-0.5 block font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
            mkt cap
          </span>
        </span>
      </Link>
    </li>
  );
}

function SearchForm({ q }: { q: string }) {
  return (
    <form action="/ceos" method="GET" role="search" className="mt-8">
      <label
        htmlFor="ceo-search"
        className="mb-2 block font-mono text-[10px] uppercase tracking-[0.2em] text-muted-foreground"
      >
        Find a CEO
      </label>
      <div className="flex items-center gap-2">
        <div className="relative min-w-0 flex-1">
          <Search
            className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden
          />
          <input
            id="ceo-search"
            type="search"
            name="q"
            defaultValue={q}
            maxLength={64}
            placeholder="Huang, Nvidia, NVDA…"
            className="h-11 w-full rounded-lg border border-border bg-card/60 pl-10 pr-3 text-base outline-none transition-colors placeholder:text-muted-foreground focus-visible:border-amber-500/60 focus-visible:ring-2 focus-visible:ring-amber-500/30 sm:text-sm"
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
            href="/ceos"
            aria-label="Clear search"
            className="inline-flex h-11 shrink-0 cursor-pointer items-center gap-1.5 rounded-lg border border-border px-3.5 text-sm text-muted-foreground transition-colors hover:bg-muted/60 hover:text-foreground"
          >
            <X className="h-3.5 w-3.5" aria-hidden />
            <span className="hidden sm:inline">Clear</span>
          </Link>
        )}
      </div>
      <p className="mt-2 text-xs text-muted-foreground">
        By name, company or exact ticker.
      </p>
    </form>
  );
}

function Pagination({ q, page, total }: { q: string; page: number; total: number }) {
  const lastPage = Math.max(1, Math.ceil(total / PAGE_SIZE));
  if (lastPage <= 1) return null;
  const step =
    "inline-flex h-11 items-center gap-1.5 rounded-lg border border-border px-3.5 text-sm transition-colors hover:bg-muted/60 cursor-pointer";
  const stepOff =
    "inline-flex h-11 items-center gap-1.5 rounded-lg border border-border/50 px-3.5 text-sm text-muted-foreground/40";
  return (
    <nav aria-label="Pagination" className="mt-8 flex items-center justify-between gap-4">
      <p className="font-mono text-xs tabular-nums text-muted-foreground">
        Page {page.toLocaleString()} of {lastPage.toLocaleString()}
      </p>
      <div className="flex items-center gap-2">
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

function DirectorySkeleton() {
  return (
    <div aria-hidden className="mt-6 space-y-px">
      {Array.from({ length: 14 }, (_, i) => (
        <div key={i} className="flex items-center gap-4 border-b border-border/40 py-3">
          <div className="h-9 w-9 shrink-0 animate-pulse rounded-md bg-muted/60" />
          <div className="min-w-0 flex-1 space-y-1.5">
            <div className="h-3.5 w-40 animate-pulse rounded bg-muted/60" />
            <div className="h-3 w-56 animate-pulse rounded bg-muted/40" />
          </div>
          <div className="h-3.5 w-16 animate-pulse rounded bg-muted/40" />
        </div>
      ))}
    </div>
  );
}

async function Directory({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const params = await searchParams;
  const q = parseQuery(params.q);
  const page = parsePage(params.page);
  const offset = (page - 1) * PAGE_SIZE;
  const { items, total } = await listCeos({ search: q, limit: PAGE_SIZE, offset });

  if (items.length === 0) {
    if (page > 1) notFound();
    return (
      <>
        <SearchForm q={q} />
        <div className="mt-8 border-l-2 border-amber-500/60 py-6 pl-5">
          <p className="text-sm text-foreground">
            {q ? (
              <>
                No CEO matching <span className="font-semibold">{q}</span>.
              </>
            ) : (
              "The directory is being built — profiles appear here as each company is indexed."
            )}
          </p>
          {q && (
            <p className="mt-2 text-sm text-muted-foreground">
              Try the company name or its ticker instead, or{" "}
              <Link href="/ceos" className="underline underline-offset-4 hover:text-foreground">
                browse everyone
              </Link>
              .
            </p>
          )}
        </div>
      </>
    );
  }

  const jsonLd = {
    "@context": "https://schema.org",
    "@graph": [
      {
        "@type": "CollectionPage",
        "@id": `${SITE_URL}/ceos`,
        url: `${SITE_URL}/ceos`,
        name: "CEO Directory",
        description: CEOS_DESCRIPTION,
        isPartOf: { "@type": "WebSite", name: SITE_NAME, url: SITE_URL },
      },
      {
        "@type": "ItemList",
        numberOfItems: total,
        itemListElement: items.map((c, i) => ({
          "@type": "ListItem",
          position: offset + i + 1,
          url: `${SITE_URL}/ceos/${c.slug}`,
          name: c.primaryCompany ? `${c.name} — CEO of ${c.primaryCompany}` : c.name,
        })),
      },
      {
        "@type": "BreadcrumbList",
        itemListElement: [
          { "@type": "ListItem", position: 1, name: "Home", item: SITE_URL },
          { "@type": "ListItem", position: 2, name: "CEOs", item: `${SITE_URL}/ceos` },
        ],
      },
    ],
  };

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />
      <SearchForm q={q} />
      <p className="mb-5 mt-8 font-mono text-xs tabular-nums text-muted-foreground">
        {q ? (
          <>
            <span className="text-foreground">{total.toLocaleString()}</span> match
            {total === 1 ? "" : "es"} for {q}
          </>
        ) : (
          <>
            <span className="text-foreground">
              {(offset + 1).toLocaleString()}–{(offset + items.length).toLocaleString()}
            </span>{" "}
            of {total.toLocaleString()} CEOs, largest company first
          </>
        )}
      </p>
      <ul>
        {items.map((c, i) => (
          <CeoRow key={c.slug} c={c} rank={offset + i + 1} index={i} />
        ))}
      </ul>
      <Pagination q={q} page={page} total={total} />
    </>
  );
}

export default function CeosPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  return (
    <main className="mx-auto max-w-5xl px-4 py-12 sm:py-16">
      <header className="max-w-[68ch]">
        <p className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
          Reference
        </p>
        <h1 className="mt-3 text-3xl font-semibold tracking-tight sm:text-4xl">CEO Directory</h1>
        <p className="mt-4 text-base leading-relaxed text-muted-foreground">
          The people running the companies behind every quote page — their
          title, the team around them, and what the board actually paid them,
          year by year, from the company&apos;s own SEC proxy filing.
        </p>
        <p className="mt-3 text-base leading-relaxed text-muted-foreground">
          For the investors worth learning from rather than the executives
          they bet on, see{" "}
          <Link
            href="/traders"
            className="font-medium text-foreground underline decoration-amber-500/40 underline-offset-4 transition-colors hover:decoration-amber-500"
          >
            Famous Traders
          </Link>
          .
        </p>
      </header>

      <section>
        <Suspense fallback={<DirectorySkeleton />}>
          <Directory searchParams={searchParams} />
        </Suspense>
      </section>
    </main>
  );
}
