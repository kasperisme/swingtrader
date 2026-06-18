"use client";

import { useMemo, useState } from "react";

export type ChartBar = {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
};

export type ChartEvent = {
  articleId: number;
  title: string | null;
  url: string | null;
  source: string | null;
  publishedAt: string | null;
  sentiment: number | null;
  impactMagnitude: number;
  topDimensions: string[];
  /** Index into the full `bars` array nearest this event's date. */
  barIndex: number;
  /** Close-to-prior-close % move on the event's bar (null if unknown). */
  movePct: number | null;
};

const RANGES = [
  { id: "1M", days: 22 },
  { id: "3M", days: 66 },
  { id: "6M", days: 132 },
  { id: "1Y", days: 264 },
] as const;
type RangeId = (typeof RANGES)[number]["id"];

/**
 * Target number of catalysts to plot in any range. We keep the top-N by impact
 * within the visible window, so the chart shows ~the same number of markers
 * whether you're looking at 1M or 1Y — just spread over a different interval.
 */
const MARKERS_TARGET = 14;

const VB_W = 1000;
const VB_H = 460;
const PLOT_TOP = 16;
const PLOT_BOT = 360; // price plot bottom; volume lives below
const VOL_TOP = 376;
const VOL_BOT = 444;
const PAD_L = 8;
const PAD_R = 64; // room for price axis labels on the right

function sentimentColor(s: number | null): string {
  if (s == null) return "hsl(var(--muted-foreground))";
  if (s > 0.15) return "hsl(142 70% 45%)"; // emerald
  if (s < -0.15) return "hsl(350 75% 55%)"; // rose
  return "hsl(var(--muted-foreground))";
}

function fmtDate(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function prettyDim(key: string): string {
  return key.replace(/_/g, " ");
}

export function TickerImpactChart({
  symbol,
  bars,
  events,
}: {
  symbol: string;
  bars: ChartBar[];
  events: ChartEvent[];
}) {
  const [rangeId, setRangeId] = useState<RangeId>("6M");
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const range = RANGES.find((r) => r.id === rangeId) ?? RANGES[2];

  const view = useMemo(() => {
    const start = Math.max(0, bars.length - range.days);
    const slice = bars.slice(start);
    return { start, slice };
  }, [bars, range.days]);

  const geom = useMemo(() => {
    const { slice, start } = view;
    if (slice.length === 0) return null;
    let lo = Infinity;
    let hi = -Infinity;
    let vMax = 0;
    for (const b of slice) {
      if (b.low < lo) lo = b.low;
      if (b.high > hi) hi = b.high;
      if (b.volume > vMax) vMax = b.volume;
    }
    if (!Number.isFinite(lo) || !Number.isFinite(hi) || hi <= lo) {
      hi = lo + 1;
    }
    const pad = (hi - lo) * 0.08;
    lo -= pad;
    hi += pad;
    const n = slice.length;
    const x = (i: number) =>
      PAD_L + (n <= 1 ? 0 : ((VB_W - PAD_L - PAD_R) * i) / (n - 1));
    const yPrice = (p: number) =>
      PLOT_TOP + ((hi - p) / (hi - lo)) * (PLOT_BOT - PLOT_TOP);
    const yVol = (v: number) =>
      VOL_BOT - (vMax > 0 ? (v / vMax) * (VOL_BOT - VOL_TOP) : 0);

    const linePts = slice.map((b, i) => `${x(i)},${yPrice(b.close)}`);
    const areaPath =
      `M ${x(0)},${PLOT_BOT} ` +
      slice.map((b, i) => `L ${x(i)},${yPrice(b.close)}`).join(" ") +
      ` L ${x(n - 1)},${PLOT_BOT} Z`;
    const linePath = "M " + linePts.join(" L ");

    // price axis ticks
    const ticks = Array.from({ length: 5 }, (_, k) => lo + ((hi - lo) * k) / 4);

    // Map global event barIndex into the sliced view, then keep the loudest
    // MARKERS_TARGET so the marker count stays ~constant across ranges (1M and
    // 1Y both show ~14, just spread over a different interval).
    const inView = events
      .map((e) => ({ ...e, vi: e.barIndex - start }))
      .filter((e) => e.vi >= 0 && e.vi < n);
    const viewEvents = [...inView]
      .sort((a, b) => b.impactMagnitude - a.impactMagnitude)
      .slice(0, MARKERS_TARGET);
    const maxMag = Math.max(1, ...viewEvents.map((e) => e.impactMagnitude));

    return { slice, x, yPrice, yVol, areaPath, linePath, ticks, lo, hi, vMax, viewEvents, maxMag, n };
  }, [view, events]);

  const selected = useMemo(
    () => events.find((e) => e.articleId === selectedId) ?? null,
    [events, selectedId],
  );

  if (!geom) {
    return (
      <div className="flex h-64 items-center justify-center rounded-xl border border-border bg-card text-sm text-muted-foreground">
        No price data available for {symbol}.
      </div>
    );
  }

  const last = geom.slice[geom.slice.length - 1];
  const first = geom.slice[0];
  const periodChange = first.close > 0 ? ((last.close - first.close) / first.close) * 100 : 0;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-baseline gap-2">
          <span className="font-mono text-sm text-muted-foreground">{symbol}</span>
          <span
            className={`font-mono text-xs ${periodChange >= 0 ? "text-emerald-500" : "text-rose-500"}`}
          >
            {periodChange >= 0 ? "+" : ""}
            {periodChange.toFixed(2)}% · {rangeId}
          </span>
        </div>
        <div className="inline-flex rounded-md border border-border bg-muted/40 p-0.5">
          {RANGES.map((r) => (
            <button
              key={r.id}
              type="button"
              onClick={() => setRangeId(r.id)}
              className={`cursor-pointer rounded px-2.5 py-1 text-xs font-medium transition-colors ${
                rangeId === r.id
                  ? "bg-background text-foreground"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {r.id}
            </button>
          ))}
        </div>
      </div>

      <div className="rounded-xl border border-border bg-card p-2">
        <svg
          viewBox={`0 0 ${VB_W} ${VB_H}`}
          className="h-auto w-full"
          role="img"
          aria-label={`${symbol} price with scored news catalysts`}
        >
          {/* price axis gridlines + labels */}
          {geom.ticks.map((t, i) => {
            const y = geom.yPrice(t);
            return (
              <g key={`tick-${i}`}>
                <line
                  x1={PAD_L}
                  x2={VB_W - PAD_R}
                  y1={y}
                  y2={y}
                  stroke="hsl(var(--border))"
                  strokeWidth={0.5}
                  strokeDasharray="2 4"
                />
                <text
                  x={VB_W - PAD_R + 6}
                  y={y + 3}
                  fontSize={11}
                  fill="hsl(var(--muted-foreground))"
                  className="font-mono"
                >
                  {t.toFixed(2)}
                </text>
              </g>
            );
          })}

          {/* volume */}
          {geom.slice.map((b, i) => {
            const up = b.close >= b.open;
            const bw = Math.max(0.5, (VB_W - PAD_L - PAD_R) / geom.n - 0.5);
            return (
              <rect
                key={`vol-${i}`}
                x={geom.x(i) - bw / 2}
                y={geom.yVol(b.volume)}
                width={bw}
                height={Math.max(0, VOL_BOT - geom.yVol(b.volume))}
                fill={up ? "hsl(142 70% 45% / 0.35)" : "hsl(350 75% 55% / 0.35)"}
              />
            );
          })}

          {/* price area + line */}
          <path d={geom.areaPath} fill="hsl(var(--primary) / 0.10)" />
          <path d={geom.linePath} fill="none" stroke="hsl(var(--primary))" strokeWidth={1.6} />

          {/* event markers */}
          {geom.viewEvents.map((e) => {
            const cx = geom.x(e.vi);
            const cy = geom.yPrice(geom.slice[e.vi].close);
            const r = 3 + 5 * Math.min(1, e.impactMagnitude / geom.maxMag);
            const isSel = e.articleId === selectedId;
            return (
              <g
                key={`ev-${e.articleId}`}
                className="cursor-pointer"
                onClick={() => setSelectedId(isSel ? null : e.articleId)}
              >
                <line x1={cx} x2={cx} y1={cy} y2={PLOT_BOT} stroke={sentimentColor(e.sentiment)} strokeWidth={isSel ? 1.2 : 0.5} strokeOpacity={isSel ? 0.6 : 0.25} />
                <circle
                  cx={cx}
                  cy={cy}
                  r={isSel ? r + 2 : r}
                  fill={sentimentColor(e.sentiment)}
                  stroke="hsl(var(--background))"
                  strokeWidth={1.5}
                  fillOpacity={0.9}
                />
              </g>
            );
          })}
        </svg>
      </div>

      {/* selected event detail */}
      {selected ? (
        <div className="rounded-lg border border-border bg-background/80 p-3">
          <div className="flex items-start justify-between gap-3">
            <a
              href={selected.url ?? "#"}
              target="_blank"
              rel="noreferrer"
              className="text-sm font-semibold text-foreground hover:underline"
            >
              {selected.title ?? `Article #${selected.articleId}`}
            </a>
            <button
              type="button"
              onClick={() => setSelectedId(null)}
              className="shrink-0 text-xs text-muted-foreground hover:text-foreground"
              aria-label="Close"
            >
              ✕
            </button>
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
            <span>{selected.source ?? "—"}</span>
            <span>{fmtDate(selected.publishedAt)}</span>
            {selected.sentiment != null ? (
              <span style={{ color: sentimentColor(selected.sentiment) }}>
                sentiment {selected.sentiment >= 0 ? "+" : ""}
                {selected.sentiment.toFixed(2)}
              </span>
            ) : null}
            <span>impact {selected.impactMagnitude.toFixed(1)}</span>
            {selected.movePct != null ? (
              <span className={selected.movePct >= 0 ? "text-emerald-500" : "text-rose-500"}>
                {selected.movePct >= 0 ? "▲" : "▼"} {Math.abs(selected.movePct).toFixed(1)}% that day
              </span>
            ) : null}
          </div>
          {selected.topDimensions.length > 0 ? (
            <div className="mt-2 flex flex-wrap gap-1">
              {selected.topDimensions.map((d) => (
                <span
                  key={d}
                  className="rounded border border-border px-1.5 py-0.5 text-[10px] text-muted-foreground"
                >
                  {prettyDim(d)}
                </span>
              ))}
            </div>
          ) : null}
        </div>
      ) : (
        <p className="text-center text-[11px] text-muted-foreground">
          Dots are scored news catalysts — size = impact, color = sentiment. Tap one to read it.
        </p>
      )}
    </div>
  );
}
