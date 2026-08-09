import Link from "next/link";
import { TickerLogo } from "@/components/ticker-logo";
import type { TopicMonth, TopicTickerImpact } from "@/app/actions/topics";
import type { AccentClasses } from "./accent";

/**
 * The two charts on a topic hub.
 *
 * Both are plain server-rendered SVG/CSS — no charting library and no client
 * bundle. `recharts` and `d3` are in the project, but neither earns its weight
 * for a bar and a column strip, and the quote page's chart is hand-rolled the
 * same way, so this matches what is already here.
 *
 * Impact is the same signed -1..+1 scale used by the claim pills and by the
 * /quote sentiment meter, drawn the same way: outward from a centre line,
 * emerald positive / rose negative, always with the number beside it so hue is
 * never the only carrier.
 */

function impactTone(v: number) {
  if (v >= 0.15) return { text: "text-emerald-800 dark:text-emerald-300", fill: "bg-emerald-500/70" };
  if (v <= -0.15) return { text: "text-rose-800 dark:text-rose-300", fill: "bg-rose-500/70" };
  return { text: "text-muted-foreground", fill: "bg-muted-foreground/50" };
}

function signed(v: number, digits = 2) {
  return `${v > 0 ? "+" : ""}${v.toFixed(digits)}`;
}

/**
 * Half-domain for the mean-impact bars.
 *
 * Individual claims run the full -1..+1, but a MEAN of hundreds of them cannot:
 * across both live topics the extremes are +0.47 and -0.05. Drawn on a ±1 track
 * every bar sat inside the middle quarter and the whole left half was dead
 * space. ±0.5 is still a FIXED domain — so a bar length means the same thing on
 * every topic — it is just the right fixed domain, and it is labelled on the
 * axis so nobody has to infer it.
 */
const MEAN_DOMAIN = 0.5;

/** Below this, a mean is one loud week rather than a pattern. */
const THIN_SAMPLE = 10;

/* ── Which names the story actually moves ─────────────────────────────────── */

export function TickerImpactBars({
  rows,
  accent,
}: {
  rows: TopicTickerImpact[];
  accent: AccentClasses;
}) {
  if (rows.length === 0) return null;

  // Impact uses the absolute -1..+1 scale, not a per-topic normalisation, so a
  // bar of a given length means the same thing on every topic.
  const mostCovered = rows.reduce((a, b) => (b.claims > a.claims ? b : a));
  // Compare against the best ADEQUATELY-sampled name: a +0.9 mean off two
  // claims is noise, and leading the reader with it would be a false headline.
  const strongest = rows.find((r) => r.claims >= THIN_SAMPLE) ?? rows[0];

  return (
    <div>
      <ul className="divide-y divide-border/60">
        {rows.map((r) => {
          const tone = impactTone(r.meanImpact);
          const pct = Math.min(Math.abs(r.meanImpact) / MEAN_DOMAIN, 1) * 50;
          const thin = r.claims < THIN_SAMPLE;
          return (
            <li key={r.ticker}>
              <Link
                href={`/quote/${r.ticker}`}
                className="group grid grid-cols-[1.75rem_minmax(0,1fr)_auto] items-center gap-x-3 rounded py-2.5 pr-2 transition-colors hover:bg-muted/60 focus-visible:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500/60 sm:grid-cols-[1.75rem_4.5rem_minmax(0,1fr)_auto] sm:gap-x-4"
              >
                <TickerLogo symbol={r.ticker} className="h-7 w-7" />
                <span
                  className={`font-mono text-sm font-semibold transition-colors ${accent.hoverText}`}
                >
                  {r.ticker}
                </span>

                {/* Diverging impact bar. Hidden on the narrowest screens, where
                    the number alone carries it rather than a 40px stub. */}
                <span className="hidden items-center gap-3 sm:flex">
                  <span className="relative h-2 min-w-0 flex-1 overflow-hidden rounded-full bg-border/60">
                    <span className="absolute left-1/2 top-0 h-full w-px -translate-x-1/2 bg-border" />
                    <span
                      className={`absolute top-0 h-full ${tone.fill} ${thin ? "opacity-40" : ""}`}
                      style={
                        r.meanImpact >= 0
                          ? { left: "50%", width: `${pct}%` }
                          : { right: "50%", width: `${pct}%` }
                      }
                    />
                  </span>
                </span>

                <span className="flex items-baseline gap-3">
                  <span className={`w-12 text-right font-mono text-sm tabular-nums ${tone.text}`}>
                    {signed(r.meanImpact)}
                  </span>
                  <span
                    className="w-16 text-right font-mono text-xs tabular-nums text-muted-foreground"
                    title={thin ? `Only ${r.claims} claims — a thin sample` : undefined}
                  >
                    {r.claims.toLocaleString()}
                    <span className="ml-1 hidden sm:inline">claims</span>
                  </span>
                </span>
              </Link>
            </li>
          );
        })}
      </ul>

      {/* The scale, stated. An unlabelled fixed domain is just a guess for the
          reader. Aligned to the bar column, so it only shows where bars do. */}
      <div
        aria-hidden
        className="mt-2 hidden grid-cols-[1.75rem_4.5rem_minmax(0,1fr)_auto] gap-x-4 sm:grid"
      >
        <span />
        <span />
        <span className="flex justify-between font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
          <span>−{MEAN_DOMAIN.toFixed(1)}</span>
          <span>0</span>
          <span>+{MEAN_DOMAIN.toFixed(1)}</span>
        </span>
        <span className="flex">
          <span className="w-12" />
          <span className="w-16" />
        </span>
      </div>

      {/* The reading, stated. A chart that leaves the reader to notice the point
          usually means they don't. */}
      {mostCovered.ticker !== strongest.ticker && (
        <p className="mt-4 max-w-[62ch] text-sm leading-relaxed text-muted-foreground">
          Coverage and impact disagree:{" "}
          <span className="font-mono text-foreground">{mostCovered.ticker}</span> draws
          the most claims ({mostCovered.claims.toLocaleString()}) at{" "}
          <span className="font-mono">{signed(mostCovered.meanImpact)}</span>, while{" "}
          <span className="font-mono text-foreground">{strongest.ticker}</span> scores
          highest at <span className="font-mono">{signed(strongest.meanImpact)}</span>{" "}
          on just {strongest.claims.toLocaleString()}. Being talked about most is not
          the same as being moved most.
        </p>
      )}
    </div>
  );
}

/* ── How the story built ──────────────────────────────────────────────────── */

function monthLabel(m: string) {
  const [y, mo] = m.split("-");
  const d = new Date(Number(y), Number(mo) - 1, 1);
  return d.toLocaleDateString("en-GB", { month: "short" });
}

export function ClaimTimeline({
  months,
  accent,
}: {
  months: TopicMonth[];
  accent: AccentClasses;
}) {
  if (months.length === 0) return null;

  const maxClaims = Math.max(...months.map((m) => m.claims), 1);
  const peak = months.reduce((a, b) => (b.claims > a.claims ? b : a));

  return (
    <div>
      {/* Columns are height=volume, tint=direction. Two encodings, because
          volume alone would say a quiet bearish month and a quiet bullish one
          are the same month. */}
      <ul className="flex h-40 items-end gap-1" role="list">
        {months.map((m) => {
          const tone = impactTone(m.meanImpact);
          const h = Math.max(4, Math.round((m.claims / maxClaims) * 100));
          return (
            <li
              key={m.month}
              className="group relative flex h-full min-w-0 flex-1 flex-col justify-end"
              title={`${m.month}: ${m.claims} claims, mean impact ${signed(m.meanImpact)}`}
            >
              <span
                className={`w-full rounded-t-sm ${tone.fill} transition-opacity group-hover:opacity-80`}
                style={{ height: `${h}%` }}
              />
              <span className="sr-only">
                {m.month}: {m.claims} claims, mean impact {signed(m.meanImpact)}
              </span>
            </li>
          );
        })}
      </ul>

      {/* Sparse axis — one label per quarter keeps 16 months readable at 390px. */}
      <ul aria-hidden className="mt-2 flex gap-1 border-t border-border/60 pt-2">
        {months.map((m, i) => (
          <li
            key={m.month}
            className="min-w-0 flex-1 text-center font-mono text-[10px] uppercase tracking-widest text-muted-foreground"
          >
            {i % 3 === 0 ? monthLabel(m.month) : " "}
          </li>
        ))}
      </ul>

      <p className="mt-4 max-w-[62ch] text-sm leading-relaxed text-muted-foreground">
        Coverage peaked in{" "}
        <span className="text-foreground">
          {monthLabel(peak.month)} {peak.month.slice(0, 4)}
        </span>{" "}
        at {peak.claims.toLocaleString()} scored claims. Column height is claim
        volume; colour is the mean scored impact of that month —{" "}
        <span className="text-emerald-800 dark:text-emerald-300">green</span> where
        the month read positive for these names,{" "}
        <span className="text-rose-800 dark:text-rose-300">red</span> where it read
        negative. A tall red column is a busy month that went against them.
      </p>

      <span className={`mt-4 block h-px w-10 ${accent.rule}`} aria-hidden />
    </div>
  );
}
