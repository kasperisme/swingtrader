"use client";

import { useMemo, useState } from "react";
import type { ArenaNavPoint } from "@/app/actions/arena";

/**
 * The arena's equity curves — every agent's return since funding, on one axis.
 *
 * Two decisions worth stating, because both are the difference between a chart
 * that argues honestly and one that flatters:
 *
 *  - **Percent return, not NAV.** Every agent started at the same $100,000, so
 *    the two are the same shape today — but indexing to a common base is what
 *    keeps the chart correct if an agent is ever funded on a different day, and
 *    it puts the zero line where the eye needs it.
 *
 *  - **The controls are not series.** `the-index` and `the-coinflip` are drawn
 *    as neutral dashed reference lines rather than given categorical hues. They
 *    are the baseline the strategies are measured against, not competitors for
 *    attention — and it keeps the categorical palette at seven, inside the fixed
 *    hue order, rather than inventing a ninth colour.
 *
 * One y-axis only. Hue follows the agent (fixed at roster order), never its
 * rank, so a leader change never repaints the board.
 */

export type CurveSeries = {
  slug: string;
  name: string;
  /** 1-7 for a strategy; null for a deterministic control. */
  colorIndex: number | null;
  points: ArenaNavPoint[];
};

type Props = {
  series: CurveSeries[];
  /** Height of the plot area in px. */
  height?: number;
};

const PAD = { top: 16, right: 16, bottom: 26, left: 48 };

function seriesColor(colorIndex: number | null): string {
  return colorIndex == null
    ? "hsl(var(--muted-foreground))"
    : `hsl(var(--arena-${colorIndex}))`;
}

function fmtPct(v: number, digits = 1) {
  return `${v >= 0 ? "+" : ""}${(v * 100).toFixed(digits)}%`;
}

function fmtDay(iso: string) {
  return new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  });
}

export function EquityCurve({ series, height = 320 }: Props) {
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);
  const [focused, setFocused] = useState<string | null>(null);

  const model = useMemo(() => {
    // One shared x-domain: the union of every session any agent has a mark for.
    const days = Array.from(
      new Set(series.flatMap((s) => s.points.map((p) => p.as_of))),
    ).sort();

    const byDay = new Map(
      series.map((s) => [
        s.slug,
        new Map(s.points.map((p) => [p.as_of, p.cumulative_return ?? 0])),
      ]),
    );

    let min = 0;
    let max = 0;
    for (const s of series) {
      for (const p of s.points) {
        const v = p.cumulative_return ?? 0;
        if (v < min) min = v;
        if (v > max) max = v;
      }
    }
    // Always keep zero in frame — the question "did it make money" is answered
    // by which side of that line the curve is on, so it can never be cropped.
    const span = Math.max(max - min, 0.02);
    const padded = span * 0.12;
    return { days, byDay, yMin: min - padded, yMax: max + padded };
  }, [series]);

  const { days, byDay, yMin, yMax } = model;

  if (days.length === 0) {
    return (
      <div
        className="flex items-center justify-center rounded-lg border border-dashed text-sm text-muted-foreground"
        style={{ height }}
      >
        No sessions marked yet — the first curve appears after the first close.
      </div>
    );
  }

  const W = 1000;
  const H = height;
  const plotW = W - PAD.left - PAD.right;
  const plotH = H - PAD.top - PAD.bottom;

  const x = (i: number) =>
    PAD.left + (days.length === 1 ? plotW / 2 : (i / (days.length - 1)) * plotW);
  const y = (v: number) =>
    PAD.top + plotH - ((v - yMin) / (yMax - yMin)) * plotH;

  const ticks = niceTicks(yMin, yMax, 4);
  // Axis precision follows the tick STEP, not a fixed digit count. On the first
  // sessions the whole range is a fraction of a percent, and rounding to whole
  // percent would label every gridline "+0%".
  const tickStep = ticks.length > 1 ? Math.abs(ticks[1] - ticks[0]) : 0.01;
  const tickDigits = tickStep >= 0.01 ? 0 : tickStep >= 0.001 ? 1 : 2;

  return (
    <figure className="not-prose">
      <div className="-mx-4 overflow-x-auto px-4 sm:mx-0 sm:px-0">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          className="w-full min-w-[560px]"
          style={{ height }}
          role="img"
          aria-label={`Cumulative return of ${series.length} agents since funding. The table below carries the same numbers.`}
          onMouseLeave={() => setHoverIdx(null)}
        >
          {/* Grid — recessive, never competing with the marks. */}
          {ticks.map((t) => (
            <g key={t}>
              <line
                x1={PAD.left}
                x2={W - PAD.right}
                y1={y(t)}
                y2={y(t)}
                stroke="hsl(var(--border))"
                strokeWidth={1}
                opacity={t === 0 ? 0.9 : 0.45}
              />
              <text
                x={PAD.left - 8}
                y={y(t)}
                textAnchor="end"
                dominantBaseline="middle"
                className="fill-muted-foreground font-mono text-[11px] tabular-nums"
              >
                {fmtPct(t, tickDigits)}
              </text>
            </g>
          ))}

          {/* x labels: first and last only — a dated tick per session turns to
              mush inside a month, and the tooltip carries the exact day. */}
          {[0, days.length - 1]
            .filter((i, n, arr) => arr.indexOf(i) === n && i >= 0)
            .map((i) => (
              <text
                key={i}
                x={x(i)}
                y={H - 8}
                textAnchor={i === 0 ? "start" : "end"}
                className="fill-muted-foreground font-mono text-[11px]"
              >
                {fmtDay(days[i])}
              </text>
            ))}

          {/* Controls first, so a strategy line is never hidden behind one. */}
          {series
            .filter((s) => s.colorIndex == null)
            .map((s) => (
              <Line
                key={s.slug}
                s={s}
                days={days}
                byDay={byDay}
                x={x}
                y={y}
                dimmed={focused != null && focused !== s.slug}
              />
            ))}
          {series
            .filter((s) => s.colorIndex != null)
            .map((s) => (
              <Line
                key={s.slug}
                s={s}
                days={days}
                byDay={byDay}
                x={x}
                y={y}
                dimmed={focused != null && focused !== s.slug}
              />
            ))}

          {/* Crosshair */}
          {hoverIdx != null && (
            <line
              x1={x(hoverIdx)}
              x2={x(hoverIdx)}
              y1={PAD.top}
              y2={PAD.top + plotH}
              stroke="hsl(var(--foreground))"
              strokeWidth={1}
              opacity={0.35}
            />
          )}

          {/* Hit targets — one full-height band per session, so the pointer
              never has to find a 2px line. */}
          {days.map((d, i) => (
            <rect
              key={d}
              x={x(i) - plotW / Math.max(days.length - 1, 1) / 2}
              y={PAD.top}
              width={Math.max(plotW / Math.max(days.length - 1, 1), 12)}
              height={plotH}
              fill="transparent"
              onMouseEnter={() => setHoverIdx(i)}
            />
          ))}
        </svg>
      </div>

      {hoverIdx != null && (
        <Tooltip
          day={days[hoverIdx]}
          rows={series
            .map((s) => ({
              slug: s.slug,
              name: s.name,
              color: seriesColor(s.colorIndex),
              value: byDay.get(s.slug)?.get(days[hoverIdx]),
            }))
            .filter((r) => r.value != null)
            .sort((a, b) => (b.value as number) - (a.value as number))}
        />
      )}

      {/* Legend. Always present for >= 2 series — identity is never colour-alone,
          and hovering a row isolates its curve. */}
      <figcaption className="mt-4">
        <ul className="flex flex-wrap gap-x-4 gap-y-2">
          {series.map((s) => (
            <li key={s.slug}>
              <button
                type="button"
                onMouseEnter={() => setFocused(s.slug)}
                onMouseLeave={() => setFocused(null)}
                onFocus={() => setFocused(s.slug)}
                onBlur={() => setFocused(null)}
                className="flex items-center gap-1.5 rounded text-[11px] font-medium text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <span
                  aria-hidden
                  className="h-0.5 w-4 rounded-full"
                  style={{
                    backgroundColor: seriesColor(s.colorIndex),
                    ...(s.colorIndex == null
                      ? {
                          backgroundImage:
                            "repeating-linear-gradient(90deg, currentColor 0 4px, transparent 4px 7px)",
                          backgroundColor: "transparent",
                          color: "hsl(var(--muted-foreground))",
                        }
                      : {}),
                  }}
                />
                {s.name}
                {s.colorIndex == null && (
                  <span className="text-muted-foreground/60">(control)</span>
                )}
              </button>
            </li>
          ))}
        </ul>
      </figcaption>
    </figure>
  );
}

function Line({
  s,
  days,
  byDay,
  x,
  y,
  dimmed,
}: {
  s: CurveSeries;
  days: string[];
  byDay: Map<string, Map<string, number>>;
  x: (i: number) => number;
  y: (v: number) => number;
  dimmed: boolean;
}) {
  const values = byDay.get(s.slug);
  if (!values) return null;

  const pts = days
    .map((d, i) => ({ i, v: values.get(d) }))
    .filter((p): p is { i: number; v: number } => p.v != null);
  if (pts.length === 0) return null;

  const isControl = s.colorIndex == null;
  const color = seriesColor(s.colorIndex);
  const d = pts.map((p, n) => `${n === 0 ? "M" : "L"}${x(p.i)},${y(p.v)}`).join(" ");

  return (
    <g opacity={dimmed ? 0.18 : 1} style={{ transition: "opacity 150ms" }}>
      <path
        d={d}
        fill="none"
        stroke={color}
        strokeWidth={isControl ? 1.5 : 2}
        strokeDasharray={isControl ? "5 4" : undefined}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {/* A single session has no line to read, so the point itself is the mark.
          The 2px surface ring keeps overlapping agents separable. */}
      {pts.length === 1 && (
        <circle
          cx={x(pts[0].i)}
          cy={y(pts[0].v)}
          r={4}
          fill={color}
          stroke="hsl(var(--background))"
          strokeWidth={2}
        />
      )}
    </g>
  );
}

function Tooltip({
  day,
  rows,
}: {
  day: string;
  rows: { slug: string; name: string; color: string; value: number | undefined }[];
}) {
  return (
    <div className="mt-3 rounded-lg border bg-card p-3 shadow-sm">
      <p className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
        {fmtDay(day)}
      </p>
      <dl className="mt-2 grid grid-cols-2 gap-x-6 gap-y-1 sm:grid-cols-3">
        {rows.map((r) => (
          <div key={r.slug} className="flex items-center justify-between gap-3">
            <dt className="flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground">
              <span
                aria-hidden
                className="h-2 w-2 shrink-0 rounded-full"
                style={{ backgroundColor: r.color }}
              />
              <span className="truncate">{r.name}</span>
            </dt>
            <dd
              className={`font-mono text-xs tabular-nums ${
                (r.value ?? 0) >= 0
                  ? "text-emerald-600 dark:text-emerald-500"
                  : "text-rose-600 dark:text-rose-500"
              }`}
            >
              {fmtPct(r.value ?? 0, 2)}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

/** Round tick values that always include zero. */
function niceTicks(min: number, max: number, count: number): number[] {
  const raw = (max - min) / count;
  const mag = Math.pow(10, Math.floor(Math.log10(Math.abs(raw) || 1)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? mag * 10;
  const out: number[] = [];
  for (let t = Math.ceil(min / step) * step; t <= max + 1e-9; t += step) {
    out.push(Math.abs(t) < 1e-9 ? 0 : t);
  }
  return out.includes(0) && min <= 0 && max >= 0 ? out : [...out, 0].sort((a, b) => a - b);
}
