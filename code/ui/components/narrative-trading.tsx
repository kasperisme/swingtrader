import Link from "next/link";
import { ArrowRight, Minus, TrendingDown, TrendingUp } from "lucide-react";
import type { LucideProps } from "lucide-react";

import type { NarrativeShowcase, PricedInHighlight } from "@/lib/quote/priced-in";
import { TickerLogo } from "@/components/ticker-logo";

/**
 * The landing page's "narrative trading" surfaces.
 *
 * Marketing name for what the quote page ships as the priced-in reconstruction.
 * The product keeps its own label; only the pitch is renamed, so nothing here
 * imports from `app/quote/**` — the two are allowed to drift.
 *
 * Everything drawn is arithmetic on other people's published price targets plus
 * the prose the generator wrote about them. Deliberately NOT drawn: the
 * per-driver "this is 25% priced in" percentages, which are unvalidated. They
 * are excluded from the quote page for that reason and a marketing page is a
 * worse place for them, not a better one.
 *
 * Server components throughout — the rail is arithmetic on stored numbers, so
 * there is nothing to hydrate and no JS ships for any of it.
 */

function money(n: number): string {
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: "USD",
    // Cents only where there are cents — analysts publish round numbers, and a
    // rail reading "$245.00" beside "$400" is ragged for no information.
    maximumFractionDigits: n >= 100 || Number.isInteger(n) ? 0 : 2,
  }).format(n);
}

/** Position along the low..high axis, clamped so a marker never leaves the rail. */
function pct(value: number, low: number, high: number): number {
  if (!(high > low)) return 50;
  return Math.max(2, Math.min(98, ((value - low) / (high - low)) * 100));
}

/** Where the price sits in the published distribution, as a plain-English lean. */
function lean(gap: number | null): { Icon: React.ComponentType<LucideProps>; text: string } {
  if (gap == null) return { Icon: Minus, text: "sitting among the published models" };
  if (Math.abs(gap) < 0.08) {
    return {
      Icon: Minus,
      text: `within ${Math.abs(gap * 100).toFixed(0)}% of the median target — broadly agreeing with the analysts`,
    };
  }
  if (gap < 0) {
    return {
      Icon: TrendingDown,
      text: `${Math.abs(gap * 100).toFixed(0)}% below the median target — more cautious than the analysts`,
    };
  }
  return {
    Icon: TrendingUp,
    text: `${(gap * 100).toFixed(0)}% above the median target — more optimistic than the analysts`,
  };
}

/**
 * low ─── median ─── high, with today's price marked.
 *
 * The one visual that carries the whole idea: the price is a position among
 * other people's published numbers, not a number on its own.
 */
function TargetRail({ v }: { v: PricedInHighlight }) {
  const anchor = v.priceAtAsOf ?? v.median;
  return (
    <div>
      <div className="relative h-2 rounded-full bg-muted">
        <div
          className="absolute -top-1 h-4 w-px bg-muted-foreground/50"
          style={{ left: `${pct(v.median, v.low, v.high)}%` }}
          aria-hidden
        />
        <div
          className="absolute top-1/2 h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-[3px] border-background bg-amber-500 shadow-sm"
          style={{ left: `${pct(anchor, v.low, v.high)}%` }}
          aria-hidden
        />
      </div>
      <div className="relative mt-2 h-8 text-[11px]">
        <span className="absolute left-0 text-muted-foreground">{money(v.low)}</span>
        <span
          className="absolute -translate-x-1/2 whitespace-nowrap text-muted-foreground"
          style={{ left: `${pct(v.median, v.low, v.high)}%` }}
        >
          median {money(v.median)}
        </span>
        <span className="absolute right-0 text-muted-foreground">{money(v.high)}</span>
        <span
          className="absolute top-4 -translate-x-1/2 whitespace-nowrap font-medium text-amber-600 dark:text-amber-400"
          style={{ left: `${pct(anchor, v.low, v.high)}%` }}
        >
          {money(anchor)} today
        </span>
      </div>
    </div>
  );
}

/** How the published models split around the price. */
function VoteTiles({ v }: { v: PricedInHighlight }) {
  const tiles = [
    { label: "Agree with the price", value: v.nEndorsed, hint: "within 8%" },
    { label: "Say it's too cheap", value: v.nContestedBull, hint: "15%+ higher" },
    { label: "Say it's too dear", value: v.nContestedBear, hint: "15%+ lower" },
  ];
  return (
    <dl className="grid grid-cols-3 gap-px overflow-hidden rounded-lg border border-border bg-border text-center">
      {tiles.map((t) => (
        <div key={t.label} className="bg-card px-2 py-3">
          <dt className="text-[10px] uppercase tracking-wide text-muted-foreground">
            {t.label}
          </dt>
          <dd className="mt-1 font-mono text-lg text-foreground">{t.value}</dd>
          <dd className="text-[10px] text-muted-foreground">{t.hint}</dd>
        </div>
      ))}
    </dl>
  );
}

// ── Compact card, for the "real output" preview row ───────────────────────────

/**
 * The narrative alongside the briefing PDF and the screening CSV.
 *
 * Deliberately shows only the SHAPE — the rail, the split, one sentence — while
 * the section further down shows what it says. Two cards of the same prose one
 * after another would read as a page repeating itself.
 */
export function NarrativeTradingPreviewCard({
  featured,
  totalCovered,
}: {
  featured: PricedInHighlight;
  totalCovered: number;
}) {
  const { Icon, text } = lean(featured.medianGap);
  return (
    <div className="group relative flex flex-col overflow-hidden rounded-2xl border border-border bg-card shadow-[0_24px_80px_-32px_rgba(0,0,0,0.6)]">
      <div className="flex items-center gap-2 border-b border-border bg-background/60 px-4 py-2.5">
        <span className="h-2.5 w-2.5 rounded-full bg-border" />
        <span className="h-2.5 w-2.5 rounded-full bg-border" />
        <span className="h-2.5 w-2.5 rounded-full bg-border" />
        <span className="ml-2 truncate font-mono text-xs text-muted-foreground">
          {featured.ticker.toLowerCase()}-narrative-{featured.asOf}
        </span>
        <span className="ml-auto shrink-0 rounded-full border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-amber-400">
          Live read
        </span>
      </div>

      <div className="relative h-[360px] overflow-hidden">
        <Link
          href={`/quote/${featured.ticker}`}
          aria-label={`Open the ${featured.ticker} narrative`}
          className="absolute inset-0 z-10"
        />
        <div className="pointer-events-none px-4 pb-4 pt-5">
          <div className="flex items-center gap-2.5">
            <TickerLogo symbol={featured.ticker} className="h-8 w-8" />
            <div className="min-w-0">
              <p className="font-mono text-sm font-semibold tracking-tight">
                {featured.ticker}
              </p>
              <p className="text-[11px] text-muted-foreground">
                {featured.nTargets} published analyst models
              </p>
            </div>
          </div>

          <div className="mt-6">
            <TargetRail v={featured} />
          </div>

          <p className="mt-7 flex items-start gap-2 text-xs leading-5 text-foreground">
            <Icon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
            <span>The market is {text}.</span>
          </p>

          <div className="mt-4">
            <VoteTiles v={featured} />
          </div>
        </div>
        <div className="pointer-events-none absolute inset-x-0 bottom-0 h-20 bg-gradient-to-t from-card to-transparent" />
        <span className="pointer-events-none absolute bottom-4 left-1/2 -translate-x-1/2 rounded-full border border-amber-500/30 bg-background/90 px-4 py-1.5 text-xs font-semibold text-amber-400 opacity-0 shadow-lg transition-opacity duration-300 group-hover:opacity-100">
          Read the narrative →
        </span>
      </div>

      <div className="flex items-center justify-between gap-3 border-t border-border px-4 py-3">
        <Link
          href="/quote"
          className="relative z-20 inline-flex items-center gap-1.5 text-sm font-semibold text-amber-400 transition-colors hover:text-amber-300"
        >
          Browse narratives
          <ArrowRight className="h-4 w-4" />
        </Link>
        <span className="relative z-20 font-mono text-[11px] text-muted-foreground">
          {totalCovered} tickers
        </span>
      </div>
    </div>
  );
}

// ── The full section ──────────────────────────────────────────────────────────

/**
 * The three moves the feature exists to support, each anchored to the part of
 * the live card that supplies it. Written as a method a reader can copy, not as
 * feature bullets — "narrative trading" is a new phrase and the section has to
 * teach it before it can sell it.
 */
const HOW_TO_READ = [
  {
    step: "Read what the price already pays for",
    detail:
      "Anything widely reported is already in the number. Buying a story everyone has read is paying full price for old news.",
  },
  {
    step: "Find what it refuses to pay for",
    detail:
      "The rejected models are the opportunity. They name the specific upside — and downside — the market is currently declining to fund.",
  },
  {
    step: "Trade the one claim that settles it",
    detail:
      "Most disagreements come down to a single variable. Know which one, and you know exactly which headline to act on and which to ignore.",
  },
];

export function NarrativeTradingSection({ showcase }: { showcase: NarrativeShowcase }) {
  const { featured, others, totalCovered } = showcase;

  // Nothing published, or the query failed. A heading and three abstract steps
  // with no worked example underneath is a worse page than no section at all.
  if (!featured && others.length === 0) return null;

  return (
    <section id="narrative-trading" className="border-t border-border py-16 md:py-24">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
        <p className="font-mono text-xs uppercase tracking-[0.2em] text-amber-500">
          Narrative trading
        </p>
        <h2 className="mt-3 text-balance text-2xl font-bold tracking-tight sm:text-3xl">
          Every price is a story the market already believes
        </h2>
        <p className="mt-3 max-w-2xl text-sm leading-relaxed text-muted-foreground">
          A share price is a vote on a set of claims. Narrative trading is reading that
          vote before you take the other side — what the price already pays for, what it
          refuses to pay for, and the single question that settles the difference. We
          reconstruct it from every published analyst model on the name, the reported
          segments and a reverse-DCF.
          {totalCovered > 0 && (
            <>
              {" "}
              <span className="text-foreground">
                Free on {totalCovered} tickers, no account.
              </span>
            </>
          )}
        </p>

        <ol className="mt-10 grid gap-x-8 gap-y-6 sm:grid-cols-3">
          {HOW_TO_READ.map((h, i) => (
            <li key={h.step}>
              <span
                aria-hidden
                className="font-mono text-xs font-semibold tabular-nums text-amber-500/60"
              >
                {String(i + 1).padStart(2, "0")}
              </span>
              <h3 className="mt-2 text-base font-semibold tracking-tight">{h.step}</h3>
              <p className="mt-1.5 text-sm leading-6 text-muted-foreground">{h.detail}</p>
            </li>
          ))}
        </ol>

        {featured && <FeaturedNarrative v={featured} />}

        {others.length > 0 && (
          <div className="mt-10">
            <p className="text-xs text-muted-foreground">
              Also reconstructed and free to read
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              {others.slice(0, 18).map((t) => (
                <Link
                  key={t}
                  href={`/quote/${t}`}
                  className="rounded-lg border border-border bg-background/60 px-2.5 py-1 font-mono text-xs text-muted-foreground transition-colors hover:border-amber-400/60 hover:bg-amber-500/10 hover:text-amber-400"
                >
                  {t}
                </Link>
              ))}
              <Link
                href="/quote"
                className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-2.5 py-1 font-mono text-xs font-semibold text-amber-400 transition-colors hover:bg-amber-500/20"
              >
                all {totalCovered} →
              </Link>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

/** The worked example: one real reconstruction, read the way the steps describe. */
function FeaturedNarrative({ v }: { v: PricedInHighlight }) {
  const { Icon, text } = lean(v.medianGap);
  return (
    <div className="mt-12 overflow-hidden rounded-2xl border border-border bg-card shadow-[0_24px_80px_-32px_rgba(0,0,0,0.6)]">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-border bg-background/60 px-5 py-3">
        <TickerLogo symbol={v.ticker} className="h-8 w-8" />
        <div className="min-w-0">
          <p className="font-mono text-sm font-semibold tracking-tight">{v.ticker}</p>
          <p className="text-[11px] text-muted-foreground">
            {v.nTargets} published analyst models · as of {v.asOf}
          </p>
        </div>
        <span className="ml-auto shrink-0 rounded-full border border-amber-500/30 bg-amber-500/10 px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-amber-400">
          Worked example
        </span>
      </div>

      <div className="grid gap-8 p-5 sm:p-6 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)] lg:gap-10">
        {/* Left: the vote itself — the arithmetic, nothing written. */}
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.15em] text-muted-foreground">
            Where the price sits
          </p>
          <div className="mt-5">
            <TargetRail v={v} />
          </div>
          <p className="mt-7 flex items-start gap-2 text-sm leading-6 text-foreground">
            <Icon className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
            <span>The market is {text}.</span>
          </p>
          <div className="mt-4">
            <VoteTiles v={v} />
          </div>
          {v.parts.position && (
            <p className="mt-4 text-pretty text-sm leading-relaxed text-muted-foreground">
              {v.parts.position}
            </p>
          )}
        </div>

        {/* Right: what that vote is actually buying and refusing. */}
        <div>
          <div className="grid gap-6 sm:grid-cols-2 sm:gap-8">
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-[0.15em] text-muted-foreground">
                The price pays for
              </p>
              <ul className="mt-3 space-y-3">
                {v.parts.paysFor.slice(0, 3).map((item) => (
                  <li
                    key={item}
                    className="border-l-2 border-border pl-3 text-sm leading-6 text-foreground/90"
                  >
                    {item}
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-[0.15em] text-amber-600 dark:text-amber-400">
                The price refuses to pay for
              </p>
              <ul className="mt-3 space-y-3">
                {v.parts.declines.slice(0, 3).map((item) => (
                  <li
                    key={item}
                    className="border-l-2 border-amber-500/40 pl-3 text-sm leading-6 text-foreground/90"
                  >
                    {item}
                  </li>
                ))}
              </ul>
            </div>
          </div>

          {v.parts.crux && (
            <div className="mt-6 rounded-xl border border-border bg-background/50 p-4">
              <p className="text-[11px] font-semibold uppercase tracking-[0.15em] text-muted-foreground">
                What the disagreement turns on
              </p>
              <p className="mt-2 text-pretty text-sm leading-relaxed text-foreground">
                {v.parts.crux}
              </p>
            </div>
          )}
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-5 py-4">
        <Link
          href={`/quote/${v.ticker}`}
          className="inline-flex items-center gap-1.5 text-sm font-semibold text-amber-400 transition-colors hover:text-amber-300"
        >
          Read {v.ticker}&rsquo;s full narrative
          <ArrowRight className="h-4 w-4" />
        </Link>
        <p className="max-w-[46ch] text-[11px] leading-5 text-muted-foreground">
          Written by a language model from the published models, the reported segments
          and a reverse-DCF — not a recommendation, and not a house view.
        </p>
      </div>
    </div>
  );
}
