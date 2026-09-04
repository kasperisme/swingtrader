"use client";

import { useMemo, useState } from "react";
import type { ArenaNavPoint } from "@/app/actions/arena";

/**
 * Portfolio value over time, in dollars — the companion to the equity curve.
 *
 * The equity curve answers "how much did it make". This answers "what was it
 * holding while it did", which is a different and often more revealing question:
 * an agent parked in cash and an agent fully invested can print the same flat
 * return, and only this chart tells them apart. The arena's first replay had
 * reasoning agents sitting at 10% invested against a buy-and-hold control at
 * 97%, which is invisible on a return chart and obvious here.
 *
 * Cash is stacked under holdings so the band heights read as the split, and the
 * total height IS net asset value. Shorts are drawn BELOW the zero line rather
 * than stacked: a short is a liability, and stacking it would imply the book is
 * bigger than it is.
 */

type Props = {
  points: ArenaNavPoint[];
  startingCash: number;
  /** 1-7 for a strategy, null for a deterministic control. */
  colorIndex: number | null;
  height?: number;
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

function fmtDay(iso: string) {
  return new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  });
}

export function PortfolioValue({
  points,
  startingCash,
  colorIndex,
  height = 260,
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
    let max = startingCash;
    let minShort = 0;
    for (const p of rows) {
      max = Math.max(max, p.nav, p.cash + (p.long_value ?? 0));
      minShort = Math.min(minShort, -(p.short_value ?? 0));
    }
    // Keep the starting line and the zero axis in frame; head-room so the top
    // band is not flush against the edge.
    return { rows, yMax: max * 1.06, yMin: Math.min(0, minShort * 1.15) };
  }, [points, startingCash]);

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

  const cashBand = band((p) => p.cash, () => 0);
  const longBand = band((p) => p.cash + (p.long_value ?? 0), (p) => p.cash);
  const shortBand = band(() => 0, (p) => -(p.short_value ?? 0));
  const navLine = rows
    .map((p, i) => `${i === 0 ? "M" : "L"}${x(i)},${y(p.nav)}`)
    .join(" ");

  const hasShorts = rows.some((p) => (p.short_value ?? 0) > 0);
  const ticks = niceTicks(yMin, yMax, 4);
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
          aria-label={`Portfolio value over time: cash and holdings stacked to net asset value. Starting capital ${fmtMoney(startingCash)}.${onSelect ? " Click a session to show the book held that day." : ""}`}
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
                {fmtMoney(t)}
              </text>
            </g>
          ))}

          {/* Starting capital — the line that turns height into profit or loss. */}
          <line
            x1={PAD.left}
            x2={W - PAD.right}
            y1={y(startingCash)}
            y2={y(startingCash)}
            stroke="hsl(var(--foreground))"
            strokeWidth={1}
            strokeDasharray="4 4"
            opacity={0.45}
          />
          <text
            x={W - PAD.right}
            y={y(startingCash) - 5}
            textAnchor="end"
            className="fill-muted-foreground font-mono text-[10px]"
          >
            start {fmtMoney(startingCash)}
          </text>

          <path d={cashBand} fill="hsl(var(--muted-foreground))" opacity={cashOpacity} />
          <path d={longBand} fill={invested} opacity={investedOpacity} />
          {hasShorts && (
            <path d={shortBand} fill="hsl(var(--destructive))" opacity={0.3} />
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
                cy={y(rows[selectedIdx].nav)}
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
        </ul>

        {hovered && (
          <dl className="mt-3 flex flex-wrap gap-x-6 gap-y-1 rounded-lg border bg-card p-3 font-mono text-xs tabular-nums">
            <div>
              <dt className="text-[10px] uppercase tracking-widest text-muted-foreground">
                {fmtDay(hovered.as_of)}
              </dt>
            </div>
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
