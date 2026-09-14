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

/**
 * The top of an article: one line of stance, then a three-part strip that
 * reads left to right as the question a reader arrives with —
 *
 *   HEADLINE SAYS   →   EXPECTED (our score)   →   ACTUAL (the price)
 *
 * with a small = / ≠ on each divider saying whether the neighbours agree.
 * Hairlines, not boxes: it sits in the article's flow like a dateline does,
 * and the strip collapses to two parts when the story names no ticker rather
 * than leaving half of it apologising for a price it cannot show.
 */

function signColor(v: number): string {
  if (v > 0.03) return "text-emerald-500";
  if (v < -0.03) return "text-rose-500";
  return "text-muted-foreground";
}

const DIRECTION_COLOR = {
  bullish: "text-emerald-500",
  bearish: "text-rose-500",
  neutral: "text-foreground",
} as const;

// Agreement is not a sign, so it never borrows gain-green / loss-red: a
// "confirms" on a bearish story would otherwise paint a bad outcome green.
// Amber — the page's one accent — marks the disagreements worth a second look.
const AGREEMENT: Record<
  Verdict["agreement"],
  { text: string; Icon: typeof Check; glyph: string | null; glyphCls: string }
> = {
  confirms: { text: "text-foreground", Icon: Check, glyph: "=", glyphCls: "text-foreground" },
  contradicts: {
    text: "text-amber-600 dark:text-amber-400",
    Icon: AlertTriangle,
    glyph: "≠",
    glyphCls: "border-amber-500/60 text-amber-600 dark:text-amber-400",
  },
  unbacked: {
    text: "text-amber-600 dark:text-amber-400",
    Icon: Minus,
    glyph: "~",
    glyphCls: "border-amber-500/40 text-amber-600 dark:text-amber-400",
  },
  diverges: {
    text: "text-amber-600 dark:text-amber-400",
    Icon: Minus,
    glyph: "~",
    glyphCls: "border-amber-500/40 text-amber-600 dark:text-amber-400",
  },
  "no-call": { text: "text-muted-foreground", Icon: Minus, glyph: null, glyphCls: "" },
};

/** The = / ≠ badge on the divider between two parts of the strip — on the top
 *  hairline when stacked, on the vertical one side by side. */
function Connector({ glyph, cls, label }: { glyph: string; cls: string; label: string }) {
  return (
    <span
      title={label}
      aria-hidden
      className={`absolute left-4 top-0 z-10 grid h-6 w-6 -translate-y-1/2 place-items-center rounded-full border border-border bg-background font-mono text-[12px] leading-none sm:left-0 sm:top-1/2 sm:-translate-x-1/2 ${cls}`}
    >
      {glyph}
    </span>
  );
}

function StripPart({
  label,
  first = false,
  firstWhenStacked = false,
  className = "",
  connector,
  children,
}: {
  label: string;
  first?: boolean;
  /** Leads the strip below `sm` because the part before it is hidden there. */
  firstWhenStacked?: boolean;
  className?: string;
  connector?: ReactNode;
  children: ReactNode;
}) {
  const edge = first
    ? "sm:pr-6"
    : `${firstWhenStacked ? "" : "border-t"} border-border/60 sm:border-l sm:border-t-0 sm:px-6 sm:last:pr-0`;
  return (
    <div className={`relative min-w-0 py-5 ${edge} ${className}`}>
      {connector}
      <dt className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
        {label}
      </dt>
      <dd className="mt-2">{children}</dd>
    </div>
  );
}

function Sub({ children }: { children: ReactNode }) {
  return <p className="mt-1.5 text-[11px] leading-relaxed text-muted-foreground">{children}</p>;
}

function HeadlinePart({ verdict }: { verdict: Verdict }) {
  const { stance } = verdict;
  const [value, sub, color] =
    stance.kind === "call"
      ? [stance.label, "Rating stated in the headline", DIRECTION_COLOR[stance.direction]]
      : stance.kind === "tone"
        ? [`Leans ${stance.direction}`, "From its wording — no explicit rating", DIRECTION_COLOR[stance.direction]]
        : ["No call", "No rating or direction in the headline", "text-muted-foreground"];
  return (
    // A phone reader has just read "Headline takes no side." — a screen-third
    // of "No call" would only repeat it. Side by side it earns its column as
    // the thing the score is compared against.
    <StripPart label="Headline says" first className={stance.kind === "none" ? "hidden sm:block" : ""}>
      <p className={`text-2xl font-semibold leading-tight tracking-tight ${color}`}>{value}</p>
      <Sub>{sub}</Sub>
    </StripPart>
  );
}

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
  /** The streamed price part (its own Suspense boundary), or null with no ticker. */
  priceSlot: ReactNode | null;
}) {
  const a = AGREEMENT[verdict.agreement];
  const hasPrice = priceSlot != null;
  const n = verdict.claimCount;
  const scoreSubject = subject ?? `${n} claim${n === 1 ? "" : "s"}`;
  const noCall = verdict.agreement === "no-call";

  return (
    <section aria-labelledby="verdict-line" className="mt-8">
      <p className="inline-flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.2em] text-amber-500/80">
        <span className="h-px w-6 bg-amber-500/60" />
        Verdict
      </p>
      <p
        id="verdict-line"
        className="mt-3 max-w-[48ch] text-xl font-semibold leading-snug tracking-tight text-foreground md:text-2xl md:leading-snug"
      >
        <span className="text-muted-foreground">{verdict.headline}</span>{" "}
        {noCall ? `${verdict.score.replace(/\.$/, "")} — ${verdict.read}.` : verdict.score}
      </p>
      {/* With no call to agree or disagree with, the conclusion would only
          repeat the read the sentence now ends on. */}
      {noCall ? null : (
        <p className={`mt-2 inline-flex items-center gap-1.5 text-sm font-medium ${a.text}`}>
          <a.Icon size={14} aria-hidden className="shrink-0" />
          {verdict.conclusion}
        </p>
      )}

      <dl
        className={`mt-6 grid border-y border-border/70 ${
          hasPrice
            ? "sm:grid-cols-[minmax(0,0.85fr)_minmax(0,1.25fr)_minmax(0,1fr)]"
            : "sm:grid-cols-[minmax(0,0.85fr)_minmax(0,2fr)]"
        }`}
      >
        <HeadlinePart verdict={verdict} />

        <StripPart
          label={`${hasPrice ? "Expected" : "NIS score"} · ${scoreSubject}`}
          firstWhenStacked={verdict.stance.kind === "none"}
          connector={
            a.glyph ? <Connector glyph={a.glyph} cls={a.glyphCls} label={verdict.conclusion} /> : null
          }
        >
          <p className="flex flex-wrap items-baseline gap-x-2.5 gap-y-0.5">
            <span
              className={`font-mono text-3xl font-semibold tabular-nums tracking-tight ${signColor(verdict.net)}`}
            >
              {signed(verdict.net)}
            </span>
            <span className="text-sm text-muted-foreground">{verdict.read}</span>
          </p>
          <ScoreRail value={verdict.net} size="lg" className="mt-3 max-w-md" />
          <AnchorCaption anchor={anchor} className="mt-2" />
        </StripPart>

        {priceSlot}
      </dl>

      <p className="mt-3 text-[13px] text-muted-foreground">
        Scored by the NIS engine ·{" "}
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

// ── Price part ───────────────────────────────────────────────────────────────

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

/** Below this a move is noise for the agreement read. */
const FLAT_PCT = 0.5;

function priceAgreement(
  expected: number,
  movePct: number,
): { text: string; glyph: string; cls: string } | null {
  if (Math.abs(movePct) < FLAT_PCT) {
    return { text: "Price flat so far", glyph: "~", cls: "text-muted-foreground" };
  }
  const dir = directionOf(expected);
  if (dir === "neutral") return null;
  return (dir === "bullish") === movePct > 0
    ? { text: "Price agrees with the score", glyph: "=", cls: "text-foreground" }
    : {
        text: "Price is moving against the score",
        glyph: "≠",
        cls: "border-amber-500/60 text-amber-600 dark:text-amber-400",
      };
}

function ChartLink({ ticker }: { ticker: string }) {
  return (
    <Link
      href={`/quote/${encodeURIComponent(ticker)}`}
      className="mt-2.5 inline-block font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground transition-colors hover:text-amber-500"
    >
      {ticker} chart →
    </Link>
  );
}

/**
 * Actual — what the price has done since the story ran, beside the score that
 * said what it should do. Async inside its own Suspense boundary: it waits on
 * FMP, and nothing else above the fold should.
 */
export async function PricePart({
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
      <StripPart label={`Actual · ${ticker}`}>
        <p className="font-mono text-3xl font-semibold text-muted-foreground">—</p>
        <Sub>No price for {ticker} right now — the quote feed didn&apos;t answer.</Sub>
        <ChartLink ticker={ticker} />
      </StripPart>
    );
  }

  if (reaction.status === "pending") {
    return (
      <StripPart label="Actual · no session yet">
        <p className="font-mono text-3xl font-semibold text-muted-foreground">—</p>
        <Sub>
          {ticker} hasn&apos;t traded since this ran. Last close ${fmtPrice(reaction.lastPrice)} (
          {fmtDay(reaction.lastDate)}); the reaction starts at the next open.
        </Sub>
        <ChartLink ticker={ticker} />
      </StripPart>
    );
  }

  const label =
    reaction.window === "today"
      ? "Actual · today"
      : `Actual · ${reaction.sessions} session${reaction.sessions === 1 ? "" : "s"}`;
  const agreement = priceAgreement(expected, reaction.movePct);
  const pct = `${reaction.movePct >= 0 ? "+" : "−"}${Math.abs(reaction.movePct).toFixed(1)}%`;

  return (
    <StripPart
      label={label}
      connector={
        agreement ? <Connector glyph={agreement.glyph} cls={agreement.cls} label={agreement.text} /> : null
      }
    >
      <p
        className={`font-mono text-3xl font-semibold tabular-nums tracking-tight ${moveColor(reaction.movePct)}`}
      >
        {pct}
      </p>
      {agreement ? <p className="mt-1.5 text-xs font-medium text-foreground/90">{agreement.text}</p> : null}
      <Sub>
        ${fmtPrice(reaction.price)} vs ${fmtPrice(reaction.refClose)} close before publication (
        {fmtDay(reaction.refDate)}) · not market-adjusted
      </Sub>
      <ChartLink ticker={ticker} />
    </StripPart>
  );
}

export function PricePartSkeleton() {
  return (
    <StripPart label="Actual">
      <div className="h-8 w-24 animate-pulse rounded bg-muted/60" />
      <div className="mt-2.5 h-3 w-full max-w-[14rem] animate-pulse rounded bg-muted/40" />
      <div className="mt-1.5 h-3 w-2/3 max-w-[10rem] animate-pulse rounded bg-muted/40" />
    </StripPart>
  );
}
