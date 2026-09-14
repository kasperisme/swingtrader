import Link from "next/link";
import type { ReactNode } from "react";
import { AlertTriangle, Check, Minus } from "lucide-react";

import {
  directionOf,
  signed,
  type Anchor,
  type Verdict,
} from "@/lib/news/article-verdict";
import { getPriceReaction } from "@/lib/news/price-reaction";
import { AnchorCaption, ScoreRail } from "./score-rail";

function scoreColor(v: number): string {
  if (v > 0.03) return "text-emerald-500";
  if (v < -0.03) return "text-rose-500";
  return "text-muted-foreground";
}

// Agreement is not a sign, so it never borrows gain-green / loss-red: a
// "confirms" on a bearish story would otherwise paint a bad outcome green.
const AGREEMENT_STYLE: Record<Verdict["agreement"], { cls: string; Icon: typeof Check }> = {
  confirms: { cls: "border-border bg-background text-foreground", Icon: Check },
  contradicts: {
    cls: "border-amber-500/50 bg-amber-500/10 text-amber-700 dark:text-amber-300",
    Icon: AlertTriangle,
  },
  unbacked: {
    cls: "border-amber-500/30 bg-amber-500/5 text-amber-700 dark:text-amber-300",
    Icon: Minus,
  },
  diverges: {
    cls: "border-amber-500/30 bg-amber-500/5 text-amber-700 dark:text-amber-300",
    Icon: Minus,
  },
  "no-call": { cls: "border-border bg-background text-foreground", Icon: Minus },
};

function CardLabel({ children }: { children: ReactNode }) {
  return (
    <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
      {children}
    </p>
  );
}

/**
 * One line of stance above the fold: what the source claims, what the scored
 * claims say, and whether the two agree — then the score on its scale and the
 * price's actual reaction beside it.
 */
export function VerdictBanner({
  verdict,
  subject,
  anchor,
  priceSlot,
}: {
  verdict: Verdict;
  /** The primary ticker, or null when the story scores claims but names no ticker. */
  subject: string | null;
  anchor: Anchor | null;
  /** The streamed price-reaction card (its own Suspense boundary). */
  priceSlot: ReactNode;
}) {
  const { cls, Icon } = AGREEMENT_STYLE[verdict.agreement];
  return (
    <section
      aria-label="Verdict"
      className="mt-6 rounded-xl border border-border/60 bg-muted/20 p-4 sm:p-5"
    >
      <p className="inline-flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.2em] text-amber-500/80">
        <span className="h-px w-6 bg-amber-500/60" />
        Verdict
      </p>
      <p className="mt-2 text-lg font-semibold leading-snug tracking-tight text-foreground sm:text-xl">
        {verdict.headline} {verdict.score}
      </p>
      <p
        className={`mt-2.5 inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium ${cls}`}
      >
        <Icon size={12} aria-hidden />
        {verdict.conclusion}
      </p>

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <div className="rounded-lg border border-border/60 bg-background/60 p-3.5">
          <CardLabel>{subject ? `${subject} score` : "Claims average"}</CardLabel>
          <p
            className={`mt-1 font-mono text-2xl font-semibold tabular-nums ${scoreColor(verdict.net)}`}
          >
            {signed(verdict.net)}
          </p>
          <ScoreRail value={verdict.net} size="lg" className="mt-2" />
          <AnchorCaption anchor={anchor} className="mt-2" />
        </div>
        {priceSlot}
      </div>
    </section>
  );
}

function fmtPrice(n: number): string {
  return n >= 1 ? n.toFixed(2) : n.toFixed(4);
}

function fmtDay(ymd: string): string {
  const d = new Date(`${ymd}T12:00:00Z`);
  if (Number.isNaN(d.getTime())) return ymd;
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", timeZone: "UTC" }).format(d);
}

function moveColor(pct: number): string {
  if (pct >= 0.05) return "text-emerald-500";
  if (pct <= -0.05) return "text-rose-500";
  return "text-muted-foreground";
}

/** Below this a daily move is noise for the agreement read. */
const FLAT_PCT = 0.5;

function priceAgreement(expected: number, movePct: number): string | null {
  const dir = directionOf(expected);
  if (Math.abs(movePct) < FLAT_PCT) return "Price flat so far";
  if (dir === "neutral") return null;
  const up = movePct > 0;
  return (dir === "bullish") === up
    ? "Price agrees with the score"
    : "Price is moving against the score";
}

function PriceCardShell({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-lg border border-border/60 bg-background/60 p-3.5">
      <CardLabel>Price reaction</CardLabel>
      {children}
    </div>
  );
}

/**
 * Expected (the score) next to actual (the move since publication). Async and
 * rendered inside its own Suspense boundary: it waits on FMP, and nothing else
 * above the fold should.
 */
export async function PriceReactionCard({
  ticker,
  publishedIso,
  expected,
}: {
  ticker: string;
  publishedIso: string;
  expected: number;
}) {
  const reaction = await getPriceReaction(ticker, publishedIso).catch(() => null);

  if (!reaction) {
    return (
      <PriceCardShell>
        <p className="mt-1 text-sm text-muted-foreground">
          No price data for {ticker} right now.
        </p>
      </PriceCardShell>
    );
  }

  const expectedLine = (
    <span className="text-muted-foreground">
      Expected{" "}
      <span className={`font-mono tabular-nums ${scoreColor(expected)}`}>{signed(expected)}</span>
    </span>
  );

  if (reaction.status === "pending") {
    return (
      <PriceCardShell>
        <p className="mt-1 flex flex-wrap items-baseline gap-x-3 gap-y-1 text-sm">
          {expectedLine}
          <span className="text-muted-foreground">
            Actual <span className="font-mono">—</span>
          </span>
        </p>
        <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
          {ticker} hasn&apos;t traded since this ran. Last close ${fmtPrice(reaction.lastPrice)}{" "}
          ({fmtDay(reaction.lastDate)}); the reaction starts at the next open.
        </p>
        <Link
          href={`/quote/${encodeURIComponent(ticker)}`}
          className="mt-2 inline-block font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground transition-colors hover:text-amber-400"
        >
          {ticker} chart →
        </Link>
      </PriceCardShell>
    );
  }

  const today = reaction.window === "today";
  const span = `${reaction.sessions} session${reaction.sessions === 1 ? "" : "s"} since publication`;
  const agreement = priceAgreement(expected, reaction.movePct);
  const pct = `${reaction.movePct >= 0 ? "+" : "−"}${Math.abs(reaction.movePct).toFixed(1)}%`;

  return (
    <PriceCardShell>
      <p className="mt-1 flex flex-wrap items-baseline gap-x-3 gap-y-1 text-sm">
        {expectedLine}
        <span className="text-muted-foreground">
          Actual{today ? " today" : ""}{" "}
          <span className={`font-mono text-2xl font-semibold tabular-nums ${moveColor(reaction.movePct)}`}>
            {pct}
          </span>
        </span>
      </p>
      {agreement ? (
        <p className="mt-1.5 text-xs font-medium text-foreground/90">{agreement}</p>
      ) : null}
      <p className="mt-1.5 text-[11px] leading-relaxed text-muted-foreground">
        {today ? "" : `${span}. `}${fmtPrice(reaction.price)} vs ${fmtPrice(reaction.refClose)} close
        before publication ({fmtDay(reaction.refDate)}). Not market-adjusted.
      </p>
      <Link
        href={`/quote/${encodeURIComponent(ticker)}`}
        className="mt-2 inline-block font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground transition-colors hover:text-amber-400"
      >
        {ticker} chart →
      </Link>
    </PriceCardShell>
  );
}

export function PriceReactionSkeleton() {
  return (
    <PriceCardShell>
      <div className="mt-2 h-6 w-40 animate-pulse rounded bg-muted/60" />
      <div className="mt-2 h-3 w-full animate-pulse rounded bg-muted/40" />
      <div className="mt-1.5 h-3 w-2/3 animate-pulse rounded bg-muted/40" />
    </PriceCardShell>
  );
}

/** When the story names no ticker there is no price to react — say so rather
 *  than leave half the banner empty. */
export function NoPriceCard() {
  return (
    <PriceCardShell>
      <p className="mt-1 text-sm text-muted-foreground">
        No single ticker to price — this story&apos;s claims are scored on their own.
      </p>
    </PriceCardShell>
  );
}
