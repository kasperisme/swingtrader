import Link from "next/link";
import type { ReactNode } from "react";
import { AlertTriangle, ArrowUpRight, Check, CircleDashed, Minus, Plus } from "lucide-react";

import { signed } from "@/lib/news/article-verdict";
import type { ImpactSummary, ImpactSummaryTicker, Relation } from "@/lib/news/impact-summary";
import { ScoreRail } from "./score-rail";

/**
 * The top of an article: what it means once you account for what each
 * company's price already assumes (the IMPACT_SUMMARY head).
 *
 *   one-paragraph read
 *   ─────────────────────────────────────────────────────────────
 *   TICKER  relation      │ price pays for "…"        │ ACTUAL
 *   +0.40   ━━━━●━━━      │ per-ticker read           │ since publication
 *   ─────────────────────────────────────────────────────────────
 *
 * Hairlines, not boxes — it sits in the article's flow like a dateline. Each
 * row ends on the price move since publication, so the in-context score is
 * shown beside what the market actually did with it.
 */

function signColor(v: number): string {
  if (v > 0.03) return "text-emerald-500";
  if (v < -0.03) return "text-rose-500";
  return "text-muted-foreground";
}

// A relation is not a sign, so it never borrows gain-green / loss-red: news
// that "challenges" a price can be bullish. Amber — the page's one accent —
// marks the reads where the article and the price disagree.
const RELATION: Record<
  Relation,
  { label: string; Icon: typeof Check; cls: string }
> = {
  confirms: { label: "Already priced in", Icon: Check, cls: "text-foreground" },
  challenges: {
    label: "Challenges what's priced in",
    Icon: AlertTriangle,
    cls: "text-amber-600 dark:text-amber-400",
  },
  new_information: {
    label: "Not in the price yet",
    Icon: Plus,
    cls: "text-amber-600 dark:text-amber-400",
  },
  not_material: {
    label: "Doesn't touch the price's assumptions",
    Icon: Minus,
    cls: "text-muted-foreground",
  },
  no_reconstruction: {
    label: "No priced-in read yet",
    Icon: CircleDashed,
    cls: "text-muted-foreground",
  },
};

function fmtAsOf(ymd: string): string {
  const d = new Date(`${ymd}T12:00:00Z`);
  if (Number.isNaN(d.getTime())) return ymd;
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", timeZone: "UTC" }).format(d);
}

function TickerRow({ row, priceSlot }: { row: ImpactSummaryTicker; priceSlot: ReactNode }) {
  const rel = RELATION[row.relation];
  const quoteHref = `/quote/${encodeURIComponent(row.ticker)}`;
  return (
    <div className="grid border-b border-border/70 sm:grid-cols-[minmax(0,0.9fr)_minmax(0,1.7fr)_minmax(0,1fr)]">
      {/* Who, how it relates, and the in-context score. */}
      <div className="min-w-0 py-5 sm:pr-6">
        <dt className="flex flex-wrap items-baseline gap-x-2.5">
          <Link
            href={quoteHref}
            className="font-mono text-lg font-semibold tracking-tight text-foreground transition-colors hover:text-amber-500"
          >
            {row.ticker}
          </Link>
          <span
            className={`font-mono text-2xl font-semibold tabular-nums tracking-tight ${signColor(row.score)}`}
          >
            {signed(row.score)}
          </span>
        </dt>
        <dd>
          <p className={`mt-1.5 inline-flex items-center gap-1.5 text-[13px] font-medium ${rel.cls}`}>
            <rel.Icon size={13} aria-hidden className="shrink-0" />
            {rel.label}
          </p>
          <ScoreRail value={row.score} className="mt-3 max-w-[14rem]" />
        </dd>
      </div>

      {/* The assumption it touches, then why. */}
      <div className="min-w-0 border-t border-border/60 py-5 sm:border-l sm:border-t-0 sm:px-6">
        <dt className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
          {row.assumption ? "The price assumes" : "In context"}
        </dt>
        <dd className="mt-2">
          {row.assumption ? (
            <p className="border-l-2 border-amber-500/50 pl-3 text-[15px] font-medium leading-snug text-foreground">
              {row.assumption}
            </p>
          ) : null}
          {row.read ? (
            <p
              className={`max-w-[60ch] text-sm leading-relaxed text-muted-foreground ${row.assumption ? "mt-2.5" : ""}`}
            >
              {row.read}
            </p>
          ) : null}
          {row.pricedInAsOf ? (
            <Link
              href={`${quoteHref}#priced-in`}
              className="group mt-3 inline-flex items-center gap-1 font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground transition-colors hover:text-amber-500"
            >
              What {row.ticker}&apos;s price assumes · {fmtAsOf(row.pricedInAsOf)}
              <ArrowUpRight
                size={11}
                aria-hidden
                className="transition-transform duration-200 group-hover:-translate-y-px group-hover:translate-x-px"
              />
            </Link>
          ) : (
            <p className="mt-3 font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground/70">
              Read from the article alone
            </p>
          )}
        </dd>
      </div>

      {priceSlot}
    </div>
  );
}

export function ImpactSummaryBanner({
  impact,
  priceSlot,
}: {
  impact: ImpactSummary;
  /** The streamed price part per ticker (each in its own Suspense boundary). */
  priceSlot: (row: ImpactSummaryTicker) => ReactNode;
}) {
  const backed = impact.tickers.filter((t) => t.pricedInAsOf).length;
  return (
    <section aria-labelledby="impact-summary-line" className="mt-8">
      <p className="inline-flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.2em] text-amber-500/80">
        <span className="h-px w-6 bg-amber-500/60" />
        Impact · against what&apos;s priced in
      </p>
      <p
        id="impact-summary-line"
        className="mt-3 max-w-[62ch] text-lg font-semibold leading-snug tracking-tight text-foreground md:text-[1.4rem] md:leading-snug"
      >
        {impact.summary}
      </p>

      {impact.tickers.length > 0 ? (
        <dl className="mt-6 border-t border-border/70">
          {impact.tickers.map((row) => (
            <TickerRow key={row.ticker} row={row} priceSlot={priceSlot(row)} />
          ))}
        </dl>
      ) : null}

      <p className="mt-3 text-[13px] text-muted-foreground">
        Scored by the NIS engine
        {backed > 0 ? " against each company's latest priced-in reconstruction" : ""} ·{" "}
        <Link
          href="/docs/news-impact-scores"
          className="text-foreground underline decoration-border underline-offset-4 transition-colors hover:text-amber-500 hover:decoration-amber-500/60"
        >
          methodology
        </Link>
        .
      </p>
    </section>
  );
}
