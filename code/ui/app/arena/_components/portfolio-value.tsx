"use client";

import { useMemo, useState } from "react";
import type { ArenaNavPoint } from "@/app/actions/arena";

/**
 * One agent's book over time, in either of the two encodings that matter.
 *
 *  - **`return`** — the equity line: cumulative return since funding, against
 *    the zero line that separates profit from loss. The question "did it make
 *    money", answered in the shape everyone already reads.
 *
 *  - **`value`** — portfolio value in dollars, cash stacked under holdings so
 *    the band heights read as the split and the total height IS net asset
 *    value. This answers "what was it holding while it did", which the return
 *    line cannot: an agent parked in cash and an agent fully invested print the
 *    same flat return. The arena's first replay had reasoning agents sitting at
 *    10% invested against a buy-and-hold control at 97% — invisible on a return
 *    chart, obvious here. Shorts are drawn BELOW the zero line rather than
 *    stacked: a short is a liability, and stacking it would imply the book is
 *    bigger than it is.
 *
 * The x-axis, the hover crosshair and the click-to-select are identical in both
 * — it is the same chart with a different y — so switching encoding never
 * changes which session the holdings table below is showing.
 */

export type PortfolioChartMode = "value" | "return";

type Props = {
  points: ArenaNavPoint[];
  startingCash: number;
  /** 1-7 for a strategy, null for a deterministic control. */
  colorIndex: number | null;
  height?: number;
  /** Which y-encoding to draw. */
  mode?: PortfolioChartMode;
  /** Session the table below is showing, marked on the chart. */
  selected?: string | null;
  /** Click a session to drive the holdings table. */
  onSelect?: (asOf: string) => void;
};

const PAD = { top: 16, right: 16, bottom: 26, left: 58 };

function fmtMoney(v: number) {
  const abs = Math.abs(v);
  if (abs >= 1_000_000) return `$${(v / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000) return `$${Math.round(v / 1_000)}k`;
  return `$${Math.round(v)}`;
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

/** Cumulative return, falling back to NAV against funding when it is missing. */
function returnOf(p: ArenaNavPoint, startingCash: number) {
  if (p.cumulative_return != null) return p.cumulative_return;
  return startingCash ? p.nav / startingCash - 1 : 0;
}

export function PortfolioValue({
  points,
  startingCash,
  colorIndex,
  height = 260,
  mode = "value",
  selected = null,
  onSelect,
}: Props) {
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);

  // Holdings carry the agent's hue. The two deterministic controls have no hue,
  // and painting both bands from the same muted token made their charts
  // grey-on-grey — unreadable on exactly the two agents everyone compares
  // against. They get the foreground token instead, so the split still reads.
  const isControl = colorIndex == null;
  const invested = isControl
    ? "hsl(var(--foreground))"
    : `hsl(var(--arena-${colorIndex}))`;
  const investedOpacity = isControl ? 0.3 : 0.42;
  const cashOpacity = isControl ? 0.1 : 0.18;

  const model = useMemo(() => {
    const rows = [...points].sort((a, b) => a.as_of.localeCompare(b.as_of));

    if (mode === "return") {
      let min = 0;
      let max = 0;
      for (const p of rows) {
        const v = returnOf(p, startingCash);
        if (v < min) min = v;
        if (v > max) max = v;
      }
      // Zero always stays in frame — the question "did it make money" is
      // answered by which side of that line the curve is on, so it can never be
      // cropped out.
      const span = Math.max(max - min, 0.02);
      const pad = span * 0.12;
      return { rows, yMin: min - pad, yMax: max + pad };
    }

    let max = startingCash;
    let minShort = 0;
    for (const p of rows) {
      max = Math.max(max, p.nav, p.cash + (p.long_value ?? 0));
      minShort = Math.min(minShort, -(p.short_value ?? 0));
    }
    // Keep the starting line and the zero axis in frame; head-room so the top
    // band is not flush against the edge.
    return { rows, yMax: max * 1.06, yMin: Math.min(0, minShort * 1.15) };
  }, [points, startingCash, mode]);

  const { rows, yMax, yMin } = model;

  if (rows.length === 0) {
    return (
      <div
        className="flex items-center justify-center rounded-lg border border-dashed text-sm text-muted-foreground"
        style={{ height }}
      >
        No sessions marked yet.
      </div>
    );
  }

  const isReturn = mode === "return";
  const W = 1000;
  const H = height;
  const plotW = W - PAD.left - PAD.right;
  const plotH = H - PAD.top - PAD.bottom;

  const x = (i: number) =>
    PAD.left + (rows.length === 1 ? plotW / 2 : (i / (rows.length - 1)) * plotW);
  const y = (v: number) =>
    PAD.top + plotH - ((v - yMin) / (yMax - yMin)) * plotH;

  const band = (top: (p: ArenaNavPoint) => number, bottom: (p: ArenaNavPoint) => number) => {
    const up = rows.map((p, i) => `${i === 0 ? "M" : "L"}${x(i)},${y(top(p))}`);
    const down = [...rows].reverse().map((p, n) => {
      const i = rows.length - 1 - n;
      return `L${x(i)},${y(bottom(p))}`;
    });
    return `${up.join(" ")} ${down.join(" ")} Z`;
  };

  // The marked value per session — NAV in dollars, or cumulative return.
  const valueAt = (p: ArenaNavPoint) => (isReturn ? returnOf(p, startingCash) : p.nav);

  const cashBand = isReturn ? "" : band((p) => p.cash, () => 0);
  const longBand = isReturn ? "" : band((p) => p.cash + (p.long_value ?? 0), (p) => p.cash);
  const shortBand = isReturn ? "" : band(() => 0, (p) => -(p.short_value ?? 0));
  // In return mode the fill runs between the line and zero, so a losing stretch
  // reads as area BELOW the axis rather than as a smaller positive block.
  const returnArea = isReturn
    ? `${rows.map((p, i) => `${i === 0 ? "M" : "L"}${x(i)},${y(valueAt(p))}`).join(" ")} L${x(rows.length - 1)},${y(0)} L${x(0)},${y(0)} Z`
    : "";
  const navLine = rows
    .map((p, i) => `${i === 0 ? "M" : "L"}${x(i)},${y(valueAt(p))}`)
    .join(" ");

  const hasShorts = rows.some((p) => (p.short_value ?? 0) > 0);
  const ticks = niceTicks(yMin, yMax, 4);
  // Axis precision follows the tick STEP, not a fixed digit count: on the first
  // sessions the whole range is a fraction of a percent, and rounding to whole
  // percent would label every gridline "+0%".
  const tickStep = ticks.length > 1 ? Math.abs(ticks[1] - ticks[0]) : 0.01;
  const tickDigits = tickStep >= 0.01 ? 0 : tickStep >= 0.001 ? 1 : 2;
  const tickLabel = (t: number) => (isReturn ? fmtPct(t, tickDigits) : fmtMoney(t));
  const baseline = isReturn ? 0 : startingCash;

  const hovered = hoverIdx == null ? null : rows[hoverIdx];
  const selectedIdx = selected
    ? (rows.findIndex((p) => p.as_of === selected) === -1
        ? null
        : rows.findIndex((p) => p.as_of === selected))
    : null;

  return (
    <figure className="not-prose">
      <div className="-mx-4 overflow-x-auto px-4 sm:mx-0 sm:px-0">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          className="w-full min-w-[560px]"
          style={{ height }}
          role="img"
          aria-label={`${
            isReturn
              ? "Cumulative return since funding, against the zero line."
              : `Portfolio value over time: cash and holdings stacked to net asset value. Starting capital ${fmtMoney(startingCash)}.`
          }${onSelect ? " Click a session to show the book held that day." : ""}`}
          onMouseLeave={() => setHoverIdx(null)}
        >
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
                {tickLabel(t)}
              </text>
            </g>
          ))}

          {/* Funding — the line that turns height into profit or loss. */}
          <line
            x1={PAD.left}
            x2={W - PAD.right}
            y1={y(baseline)}
            y2={y(baseline)}
            stroke="hsl(var(--foreground))"
            strokeWidth={1}
            strokeDasharray="4 4"
            opacity={0.45}
          />
          <text
            x={W - PAD.right}
            y={y(baseline) - 5}
            textAnchor="end"
            className="fill-muted-foreground font-mono text-[10px]"
          >
            start {isReturn ? "0%" : fmtMoney(startingCash)}
          </text>

          {isReturn ? (
            <path d={returnArea} fill={invested} opacity={0.14} />
          ) : (
            <>
              <path d={cashBand} fill="hsl(var(--muted-foreground))" opacity={cashOpacity} />
              <path d={longBand} fill={invested} opacity={investedOpacity} />
              {hasShorts && (
                <path d={shortBand} fill="hsl(var(--destructive))" opacity={0.3} />
              )}
            </>
          )}

          <path
            d={navLine}
            fill="none"
            stroke={invested}
            strokeWidth={2}
            strokeLinecap="round"
            strokeLinejoin="round"
          />

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

          {[0, rows.length - 1]
            .filter((i, n, arr) => arr.indexOf(i) === n && i >= 0)
            .map((i) => (
              <text
                key={i}
                x={x(i)}
                y={H - 8}
                textAnchor={i === 0 ? "start" : "end"}
                className="fill-muted-foreground font-mono text-[11px]"
              >
                {fmtDay(rows[i].as_of)}
              </text>
            ))}

          {selectedIdx != null && (
            <g>
              <line
                x1={x(selectedIdx)}
                x2={x(selectedIdx)}
                y1={PAD.top}
                y2={PAD.top + plotH}
                stroke={invested}
                strokeWidth={1.5}
                opacity={0.75}
              />
              <circle
                cx={x(selectedIdx)}
                cy={y(valueAt(rows[selectedIdx]))}
                r={4.5}
                fill={invested}
                stroke="hsl(var(--background))"
                strokeWidth={2}
              />
            </g>
          )}

          {rows.map((p, i) => (
            <rect
              key={p.as_of}
              className={onSelect ? "cursor-pointer" : undefined}
              onClick={onSelect ? () => onSelect(p.as_of) : undefined}
              x={x(i) - plotW / Math.max(rows.length - 1, 1) / 2}
              y={PAD.top}
              width={Math.max(plotW / Math.max(rows.length - 1, 1), 12)}
              height={plotH}
              fill="transparent"
              onMouseEnter={() => setHoverIdx(i)}
            />
          ))}
        </svg>
      </div>

      <figcaption className="mt-3">
        <ul className="flex flex-wrap gap-x-4 gap-y-1.5 text-[11px] text-muted-foreground">
          {isReturn ? (
            <li className="flex items-center gap-1.5">
              <span
                aria-hidden
                className="h-0.5 w-4 rounded-full"
                style={{ backgroundColor: invested }}
              />
              Cumulative return since funding
            </li>
          ) : (
            <>
              <li className="flex items-center gap-1.5">
                <span
                  aria-hidden
                  className="h-2.5 w-2.5 rounded-sm"
                  style={{ backgroundColor: invested, opacity: investedOpacity }}
                />
                Holdings
              </li>
              <li className="flex items-center gap-1.5">
                <span
                  aria-hidden
                  className="h-2.5 w-2.5 rounded-sm bg-muted-foreground/25"
                />
                Cash
              </li>
              {hasShorts && (
                <li className="flex items-center gap-1.5">
                  <span aria-hidden className="h-2.5 w-2.5 rounded-sm bg-destructive/30" />
                  Shorts (below the line — a liability)
                </li>
              )}
              <li className="flex items-center gap-1.5">
                <span
                  aria-hidden
                  className="h-0.5 w-4 rounded-full"
                  style={{ backgroundColor: invested }}
                />
                Net asset value
              </li>
            </>
          )}
        </ul>

        {hovered && (
          <dl className="mt-3 flex flex-wrap gap-x-6 gap-y-1 rounded-lg border bg-card p-3 font-mono text-xs tabular-nums">
            <div>
              <dt className="text-[10px] uppercase tracking-widest text-muted-foreground">
                {fmtDay(hovered.as_of)}
              </dt>
            </div>
            {isReturn && (
              <div className="flex gap-1.5">
                <dt className="text-muted-foreground">Return</dt>
                <dd
                  className={`font-medium ${
                    returnOf(hovered, startingCash) >= 0
                      ? "text-emerald-600 dark:text-emerald-500"
                      : "text-rose-600 dark:text-rose-500"
                  }`}
                >
                  {fmtPct(returnOf(hovered, startingCash), 2)}
                </dd>
              </div>
            )}
            <div className="flex gap-1.5">
              <dt className="text-muted-foreground">NAV</dt>
              <dd className="font-medium">{fmtMoney(hovered.nav)}</dd>
            </div>
            <div className="flex gap-1.5">
              <dt className="text-muted-foreground">Cash</dt>
              <dd>
                {fmtMoney(hovered.cash)}
                <span className="ml-1 text-muted-foreground">
                  ({Math.round((hovered.cash / (hovered.nav || 1)) * 100)}%)
                </span>
              </dd>
            </div>
            <div className="flex gap-1.5">
              <dt className="text-muted-foreground">Holdings</dt>
              <dd>{fmtMoney(hovered.long_value ?? 0)}</dd>
            </div>
            {(hovered.short_value ?? 0) > 0 && (
              <div className="flex gap-1.5">
                <dt className="text-muted-foreground">Short</dt>
                <dd>{fmtMoney(hovered.short_value)}</dd>
              </div>
            )}
            <div className="flex gap-1.5">
              <dt className="text-muted-foreground">Positions</dt>
              <dd>{hovered.n_positions}</dd>
            </div>
          </dl>
        )}
      </figcaption>
    </figure>
  );
}

/** Round tick values that always include zero and the starting line's scale. */
function niceTicks(min: number, max: number, count: number): number[] {
  const raw = (max - min) / count;
  const mag = Math.pow(10, Math.floor(Math.log10(Math.abs(raw) || 1)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? mag * 10;
  const out: number[] = [];
  for (let t = Math.ceil(min / step) * step; t <= max + 1e-9; t += step) {
    out.push(Math.abs(t) < 1e-9 ? 0 : t);
  }
  return out;
}
