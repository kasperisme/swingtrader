"use client";

import type { MouseEvent as ReactMouseEvent } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Brush,
  LineChart,
  ComposedChart,
  Line,
  Bar,
  Scatter,
  ErrorBar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
} from "recharts";
import type { MouseHandlerDataParam } from "recharts";
import { TrendingUp, TrendingDown, Minus, ChevronRight, Sparkles, X } from "lucide-react";
import { CLUSTERS } from "../vectors/dimensions";
import { fmpGetOhlc } from "@/app/actions/fmp";
import { ArticlesGrid } from "@/components/articles-grid";

export interface ArticleImpact {
  published_at: string;
  impact_json: Record<string, number>;
  /** Mean confidence across `news_impact_heads` rows for this article; drives weighted period averages. */
  confidence?: number | null;
  id?: number | null;
  title?: string | null;
  url?: string | null;
  source?: string | null;
  slug?: string | null;
  image_url?: string | null;
  created_at?: string | null;
}

// ── cluster palette ──────────────────────────────────────────────────────────
const CLUSTER_COLORS: Record<string, string> = {
  MACRO_SENSITIVITY: "hsl(var(--chart-1))",
  SECTOR_ROTATION: "hsl(var(--chart-2))",
  BUSINESS_MODEL: "hsl(var(--chart-4))",
  FINANCIAL_STRUCTURE: "hsl(var(--chart-3))",
  GROWTH_PROFILE: "hsl(var(--chart-3))",
  VALUATION_POSITIONING: "hsl(var(--chart-5))",
  GEOGRAPHY_TRADE: "hsl(var(--chart-5))",
  SUPPLY_CHAIN_EXPOSURE: "hsl(var(--chart-1))",
  MARKET_BEHAVIOUR: "hsl(var(--chart-2))",
};

// Distinct colors for individual dimensions within a drilled-down cluster
const DIM_PALETTE = [
  "hsl(var(--chart-1))",
  "hsl(var(--chart-5))",
  "hsl(var(--chart-2))",
  "hsl(var(--chart-3))",
  "hsl(var(--chart-4))",
  "hsl(var(--accent))",
  "hsl(var(--primary))",
  "hsl(var(--chart-2))",
  "hsl(var(--chart-5))",
  "hsl(var(--chart-3))",
];

// ── helpers ──────────────────────────────────────────────────────────────────

type ViewMode = "daily" | "hourly";
type BenchmarkId = "none" | "sp500" | "nasdaq100";
type AggregationMode = "period" | "cumulative";

type OhlcPoint = {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
};

const BENCHMARK_OPTIONS: Array<{ id: BenchmarkId; label: string; symbol: string | null }> = [
  { id: "none", label: "No index", symbol: null },
  { id: "sp500", label: "S&P 500 (^GSPC)", symbol: "^GSPC" },
  { id: "nasdaq100", label: "Nasdaq 100 (QQQ)", symbol: "QQQ" },
];

// ── local-time bucket helpers ─────────────────────────────────────────────────
// All bucketing uses the browser's local timezone so the X-axis matches the
// user's wall clock, not UTC.

const pad2 = (n: number) => String(n).padStart(2, "0");

function localDateStr(d: Date): string {
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
}

function localBucket(d: Date, mode: ViewMode): string {
  const base = localDateStr(d);
  return mode === "hourly" ? `${base}T${pad2(d.getHours())}` : base;
}

function toBucket(iso: string, mode: ViewMode): string {
  const d = new Date(iso);
  if (!Number.isNaN(d.getTime())) return localBucket(d, mode);
  // Fallback for plain date strings with no time component.
  return mode === "hourly" ? iso.slice(0, 13) : iso.slice(0, 10);
}

function normalizeToBucket(dateLike: string, mode: ViewMode): string | null {
  if (!dateLike) return null;
  const parsed = new Date(dateLike.replace(" ", "T"));
  if (Number.isNaN(parsed.getTime())) return null;
  return localBucket(parsed, mode);
}

function formatBucket(bucket: string, mode: ViewMode): string {
  if (mode === "hourly") {
    // "2024-01-15T14" → "01-15 14h"
    const [datePart, hourPart] = bucket.split("T");
    return `${datePart.slice(5)} ${hourPart}h`;
  }
  return bucket.slice(5); // "2024-01-15" → "01-15"
}

type DateParts = {
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: number;
};

function getTimeZoneParts(date: Date, timeZone: string): DateParts {
  const dtf = new Intl.DateTimeFormat("en-US", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  const parts = dtf.formatToParts(date);
  const map = Object.fromEntries(parts.map((p) => [p.type, p.value]));
  return {
    year: Number.parseInt(map.year ?? "0", 10),
    month: Number.parseInt(map.month ?? "0", 10),
    day: Number.parseInt(map.day ?? "0", 10),
    hour: Number.parseInt(map.hour ?? "0", 10),
    minute: Number.parseInt(map.minute ?? "0", 10),
  };
}

function compareDateOnly(a: { year: number; month: number; day: number }, b: { year: number; month: number; day: number }): number {
  if (a.year !== b.year) return a.year - b.year;
  if (a.month !== b.month) return a.month - b.month;
  return a.day - b.day;
}

function addDaysDateOnly(
  d: { year: number; month: number; day: number },
  deltaDays: number,
): { year: number; month: number; day: number } {
  const tmp = new Date(Date.UTC(d.year, d.month - 1, d.day));
  tmp.setUTCDate(tmp.getUTCDate() + deltaDays);
  return {
    year: tmp.getUTCFullYear(),
    month: tmp.getUTCMonth() + 1,
    day: tmp.getUTCDate(),
  };
}

function nthWeekdayOfMonth(
  year: number,
  month1to12: number,
  weekday: number,
  n: number,
): { year: number; month: number; day: number } {
  const first = new Date(Date.UTC(year, month1to12 - 1, 1));
  const firstWeekday = first.getUTCDay();
  const delta = (weekday - firstWeekday + 7) % 7;
  const day = 1 + delta + (n - 1) * 7;
  return { year, month: month1to12, day };
}

function lastWeekdayOfMonth(
  year: number,
  month1to12: number,
  weekday: number,
): { year: number; month: number; day: number } {
  const last = new Date(Date.UTC(year, month1to12, 0));
  const lastDay = last.getUTCDate();
  const lastWeekday = last.getUTCDay();
  const delta = (lastWeekday - weekday + 7) % 7;
  return { year, month: month1to12, day: lastDay - delta };
}

function easterSundayUtc(year: number): { year: number; month: number; day: number } {
  // Anonymous Gregorian algorithm
  const a = year % 19;
  const b = Math.floor(year / 100);
  const c = year % 100;
  const d = Math.floor(b / 4);
  const e = b % 4;
  const f = Math.floor((b + 8) / 25);
  const g = Math.floor((b - f + 1) / 3);
  const h = (19 * a + b - d - g + 15) % 30;
  const i = Math.floor(c / 4);
  const k = c % 4;
  const l = (32 + 2 * e + 2 * i - h - k) % 7;
  const m = Math.floor((a + 11 * h + 22 * l) / 451);
  const month = Math.floor((h + l - 7 * m + 114) / 31); // 3=Mar, 4=Apr
  const day = ((h + l - 7 * m + 114) % 31) + 1;
  return { year, month, day };
}

function observedFixedHoliday(
  year: number,
  month: number,
  day: number,
): { year: number; month: number; day: number } {
  const d = new Date(Date.UTC(year, month - 1, day));
  const dow = d.getUTCDay();
  if (dow === 6) return addDaysDateOnly({ year, month, day }, -1); // Saturday -> Friday
  if (dow === 0) return addDaysDateOnly({ year, month, day }, 1); // Sunday -> Monday
  return { year, month, day };
}

function isUsMarketHolidayNyDate(year: number, month: number, day: number): boolean {
  const target = { year, month, day };
  const same = (x: { year: number; month: number; day: number }) => compareDateOnly(x, target) === 0;

  const newYears = observedFixedHoliday(year, 1, 1);
  const mlk = nthWeekdayOfMonth(year, 1, 1, 3); // 3rd Monday Jan
  const presidents = nthWeekdayOfMonth(year, 2, 1, 3); // 3rd Monday Feb
  const easter = easterSundayUtc(year);
  const goodFriday = addDaysDateOnly(easter, -2);
  const memorial = lastWeekdayOfMonth(year, 5, 1); // last Monday May
  const juneteenth = observedFixedHoliday(year, 6, 19);
  const independence = observedFixedHoliday(year, 7, 4);
  const labor = nthWeekdayOfMonth(year, 9, 1, 1); // 1st Monday Sep
  const thanksgiving = nthWeekdayOfMonth(year, 11, 4, 4); // 4th Thursday Nov
  const christmas = observedFixedHoliday(year, 12, 25);

  return (
    same(newYears) ||
    same(mlk) ||
    same(presidents) ||
    same(goodFriday) ||
    same(memorial) ||
    same(juneteenth) ||
    same(independence) ||
    same(labor) ||
    same(thanksgiving) ||
    same(christmas)
  );
}

function isUsMarketTradingDayNyDate(year: number, month: number, day: number): boolean {
  const dow = new Date(Date.UTC(year, month - 1, day)).getUTCDay();
  if (dow === 0 || dow === 6) return false;
  return !isUsMarketHolidayNyDate(year, month, day);
}

function nyTimeToUtcDate(
  year: number,
  month: number,
  day: number,
  hour: number,
  minute: number,
): Date {
  // Resolve local NY wall-clock to UTC with iterative timezone-part correction.
  let guessUtcMs = Date.UTC(year, month - 1, day, hour, minute, 0, 0);
  const desiredMs = Date.UTC(year, month - 1, day, hour, minute, 0, 0);
  for (let i = 0; i < 5; i += 1) {
    const current = getTimeZoneParts(new Date(guessUtcMs), "America/New_York");
    const currentMs = Date.UTC(current.year, current.month - 1, current.day, current.hour, current.minute, 0, 0);
    const diffMs = desiredMs - currentMs;
    if (diffMs === 0) break;
    guessUtcMs += diffMs;
  }
  return new Date(guessUtcMs);
}

/** Articles whose time bucket falls in [startBucket, endBucket] (inclusive), using the same bucketing as the chart. */
function articlesInBucketRange(
  rows: ArticleImpact[],
  startBucket: string,
  endBucket: string,
  mode: ViewMode,
): ArticleImpact[] {
  const lo = startBucket <= endBucket ? startBucket : endBucket;
  const hi = startBucket <= endBucket ? endBucket : startBucket;
  return rows.filter((a) => {
    const b = toBucket(a.published_at, mode);
    return b >= lo && b <= hi;
  });
}

/** Mean of available dimension scores in ``impact_json`` for one cluster (matches chart bucket logic). */
function clusterMeanImpact(article: ArticleImpact, clusterId: string): number | null {
  const cluster = CLUSTERS.find((c) => c.id === clusterId);
  if (!cluster) return null;
  const scores = cluster.dimensions
    .map((d) => article.impact_json[d.key])
    .filter((v): v is number => typeof v === "number" && Number.isFinite(v));
  if (scores.length === 0) return null;
  return scores.reduce((a, b) => a + b, 0) / scores.length;
}

/**
 * Recharts 3 does not run tooltip/mouse-sync on mousedown, so activeTooltipIndex is often
 * undefined when the user clicks without a prior mousemove. Map clientX into band index using
 * the wrapper rect and approximate plot gutters (Y-axis left, optional benchmark Y right).
 */
function clientXToDataIndex(
  clientX: number,
  chartRect: DOMRect,
  dataLen: number,
  plotLeftPx: number,
  plotRightPx: number,
): number {
  if (dataLen < 2) return 0;
  const innerW = Math.max(1, chartRect.width - plotLeftPx - plotRightPx);
  const xRel = clientX - chartRect.left - plotLeftPx;
  const t = xRel / innerW;
  const clamped = Math.max(0, Math.min(1, t));
  return Math.round(clamped * (dataLen - 1));
}

/** Non-negative weight from model confidence; missing → 1 (neutral). */
function impactConfidenceWeight(confidence: number | null | undefined): number {
  if (confidence == null || !Number.isFinite(confidence)) return 1;
  return Math.max(0, confidence);
}

/** sum(value × weight) / sum(weight); if all weights are 0, plain mean of values. */
function weightedMeanPairs(pairs: { value: number; weight: number }[]): number | null {
  if (pairs.length === 0) return null;
  let sumW = 0;
  let sumVW = 0;
  for (const { value, weight } of pairs) {
    if (!Number.isFinite(value)) continue;
    const w = Number.isFinite(weight) && weight > 0 ? weight : 0;
    sumW += w;
    sumVW += value * w;
  }
  if (sumW > 0) return sumVW / sumW;
  const vals = pairs.map((p) => p.value).filter((v) => Number.isFinite(v));
  return vals.length > 0 ? vals.reduce((a, b) => a + b, 0) / vals.length : null;
}

/** Compute per-period confidence-weighted average impact per cluster and dimension */
function buildPeriodData(
  articles: ArticleImpact[],
  mode: ViewMode,
): Array<{
  date: string;
  clusters: Record<string, number | null>;
  dimensions: Record<string, number | null>;
  count: number;
}> {
  const byDate = new Map<string, ArticleImpact[]>();
  for (const a of articles) {
    const d = toBucket(a.published_at, mode);
    if (!byDate.has(d)) byDate.set(d, []);
    byDate.get(d)!.push(a);
  }

  const sorted = Array.from(byDate.entries()).sort((a, b) =>
    a[0].localeCompare(b[0]),
  );

  // Collect all dimension keys across all clusters
  const allDimKeys = CLUSTERS.flatMap((c) => c.dimensions.map((d) => d.key));

  return sorted.map(([date, rows]) => {
    const clusters: Record<string, number | null> = {};
    for (const cluster of CLUSTERS) {
      const pairs: { value: number; weight: number }[] = [];
      for (const row of rows) {
        const w = impactConfidenceWeight(row.confidence);
        const dimKeys = cluster.dimensions.map((d) => d.key);
        const scores = dimKeys
          .map((k) => row.impact_json[k])
          .filter((v) => v != null && !isNaN(v)) as number[];
        if (scores.length === 0) continue;
        const value = scores.reduce((a, b) => a + b, 0) / scores.length;
        pairs.push({ value, weight: w });
      }
      clusters[cluster.id] = weightedMeanPairs(pairs);
    }

    const dimensions: Record<string, number | null> = {};
    for (const key of allDimKeys) {
      const pairs: { value: number; weight: number }[] = [];
      for (const row of rows) {
        const v = row.impact_json[key];
        if (v == null || isNaN(v)) continue;
        pairs.push({ value: v, weight: impactConfidenceWeight(row.confidence) });
      }
      dimensions[key] = weightedMeanPairs(pairs);
    }

    return { date, clusters, dimensions, count: rows.length };
  });
}

/** Fill missing date/hour buckets in the range with null values */
function fillDateGaps(
  data: ReturnType<typeof buildPeriodData>,
  mode: ViewMode,
  startBucket: string,
  endBucket: string,
): ReturnType<typeof buildPeriodData> {
  if (!startBucket || !endBucket) return data;

  const allDimKeys = CLUSTERS.flatMap((c) => c.dimensions.map((d) => d.key));
  const dataMap = new Map(data.map((d) => [d.date, d]));
  const result: ReturnType<typeof buildPeriodData> = [];

  const emptyEntry = (date: string) => {
    const clusters: Record<string, number | null> = {};
    for (const cluster of CLUSTERS) clusters[cluster.id] = null;
    const dimensions: Record<string, number | null> = {};
    for (const key of allDimKeys) dimensions[key] = null;
    return { date, clusters, dimensions, count: 0 };
  };

  const toHourlyBucket = (bucket: string, endOfDay: boolean): string | null => {
    // Accept either "YYYY-MM-DD" or "YYYY-MM-DDTHH".
    if (/^\d{4}-\d{2}-\d{2}T\d{2}$/.test(bucket)) return bucket;
    if (/^\d{4}-\d{2}-\d{2}$/.test(bucket)) return `${bucket}T${endOfDay ? "23" : "00"}`;
    return null;
  };

  if (mode === "daily") {
    let current = startBucket.slice(0, 10);
    const end = endBucket.slice(0, 10);
    while (current <= end) {
      result.push(dataMap.get(current) ?? emptyEntry(current));
      const [y, m, day] = current.split("-").map(Number);
      const d = new Date(y, m - 1, day); // local midnight
      d.setDate(d.getDate() + 1);
      if (Number.isNaN(d.getTime())) break;
      current = localDateStr(d);
    }
  } else {
    // hourly buckets: "2024-01-15T14" (local time)
    const normalizedStart = toHourlyBucket(startBucket, false);
    const normalizedEnd = toHourlyBucket(endBucket, true);
    if (!normalizedStart || !normalizedEnd) return data;

    let current: string = normalizedStart;
    const end: string = normalizedEnd;

    while (current <= end) {
      result.push(dataMap.get(current) ?? emptyEntry(current));
      const [datePart, hourPart] = current.split("T");
      const [y, m, day] = datePart.split("-").map(Number);
      const hour = Number.parseInt(hourPart, 10);
      if (Number.isNaN(hour)) break;
      const d = new Date(y, m - 1, day, hour); // local time
      d.setHours(d.getHours() + 1);
      if (Number.isNaN(d.getTime())) break;
      current = localBucket(d, "hourly");
    }
  }

  return result;
}

/** Apply rolling window moving average to cluster data */
function applyClusterMA(
  daily: ReturnType<typeof buildPeriodData>,
  window: number,
): Array<{ date: string; [key: string]: number | string | null }> {
  return daily.map((point, i) => {
    const start = Math.max(0, i - window + 1);
    const slice = daily.slice(start, i + 1);
    const result: { date: string; [key: string]: number | string | null } = {
      date: point.date,
      __articleCount: point.count,
    };
    for (const cluster of CLUSTERS) {
      const vals = slice
        .map((d) => d.clusters[cluster.id])
        .filter((v): v is number => v != null);
      result[cluster.id] =
        vals.length > 0 ? vals.reduce((a, b) => a + b, 0) / vals.length : null;
    }
    const clusterVals = CLUSTERS.map((c) => result[c.id] as number | null).filter(
      (v): v is number => v != null,
    );
    result.__clusterMean =
      clusterVals.length > 0
        ? clusterVals.reduce((a, b) => a + b, 0) / clusterVals.length
        : null;
    return result;
  });
}

/** Apply rolling window MA to dimension data for a specific cluster */
function applyDimensionMA(
  daily: ReturnType<typeof buildPeriodData>,
  window: number,
  dimKeys: string[],
): Array<{ date: string; [key: string]: number | string | null }> {
  return daily.map((point, i) => {
    const start = Math.max(0, i - window + 1);
    const slice = daily.slice(start, i + 1);
    const result: { date: string; [key: string]: number | string | null } = {
      date: point.date,
    };
    for (const key of dimKeys) {
      const vals = slice
        .map((d) => d.dimensions[key])
        .filter((v): v is number => v != null);
      result[key] =
        vals.length > 0 ? vals.reduce((a, b) => a + b, 0) / vals.length : null;
    }
    return result;
  });
}

function accumulateSeries(
  data: Array<{ date: string; [key: string]: number | string | null }>,
  keys: string[],
): Array<{ date: string; [key: string]: number | string | null }> {
  const running: Record<string, number> = Object.fromEntries(keys.map((k) => [k, 0]));
  const seen: Record<string, boolean> = Object.fromEntries(keys.map((k) => [k, false]));

  return data.map((point) => {
    const next: { date: string; [key: string]: number | string | null } = { date: point.date };
    for (const key of keys) {
      const raw = point[key];
      if (typeof raw === "number" && Number.isFinite(raw)) {
        running[key] += raw;
        seen[key] = true;
      }
      next[key] = seen[key] ? running[key] : null;
    }
    return next;
  });
}

// ── sub-components ───────────────────────────────────────────────────────────

function Leaderboard({
  latest,
  selected,
  drilldownId,
  onToggle,
  onFocus,
  onDrilldown,
  maOff,
  cumulative,
}: {
  latest: Record<string, number | null>;
  selected: Set<string>;
  drilldownId: string | null;
  onToggle: (id: string) => void;
  onFocus: (id: string) => void;
  onDrilldown: (id: string) => void;
  maOff: boolean;
  cumulative: boolean;
}) {
  const sorted = CLUSTERS.map((c) => ({
    cluster: c,
    score: latest[c.id] ?? null,
  })).sort((a, b) => {
    if (a.score == null && b.score == null) return 0;
    if (a.score == null) return 1;
    if (b.score == null) return -1;
    return b.score - a.score;
  });

  return (
    <div className="flex flex-col gap-0.5">
      <p className="text-[10px] font-semibold text-muted-foreground/70 uppercase tracking-widest mb-2 px-2">
        {cumulative ? "Cumulative" : maOff ? "Latest" : "MA Score"}
      </p>
      {sorted.map(({ cluster, score }) => {
        const color = CLUSTER_COLORS[cluster.id];
        const isSelected = selected.has(cluster.id);
        const isDrilled = drilldownId === cluster.id;
        const isPos = score != null && score > 0.05;
        const isNeg = score != null && score < -0.05;

        return (
          <div
            key={cluster.id}
            className={`group flex items-center gap-1 px-2 py-1.5 rounded-lg transition-colors cursor-pointer ${
              isDrilled ? "bg-muted ring-1 ring-border" : "hover:bg-muted/50"
            }`}
          >
            {/* Toggle visibility */}
            <button
              onClick={() => onToggle(cluster.id)}
              onDoubleClick={(e) => { e.preventDefault(); onFocus(cluster.id); }}
              className={`flex items-center gap-2 flex-1 text-left min-w-0 ${!isSelected ? "opacity-50" : ""}`}
              title="Click to toggle · Double-click to focus"
            >
              <span
                className="w-2.5 h-2.5 rounded-full shrink-0"
                style={{ backgroundColor: color }}
              />
              <span className="flex-1 text-xs font-medium truncate">
                {cluster.label}
              </span>
              <span className="flex items-center gap-0.5 text-xs font-mono tabular-nums shrink-0">
                {isPos ? (
                  <TrendingUp size={10} className="text-emerald-500" />
                ) : isNeg ? (
                  <TrendingDown size={10} className="text-rose-500" />
                ) : (
                  <Minus size={10} className="text-muted-foreground" />
                )}
                <span
                  className={
                    isPos
                      ? "text-emerald-500"
                      : isNeg
                        ? "text-rose-500"
                        : "text-muted-foreground"
                  }
                >
                  {score != null
                    ? (score >= 0 ? "+" : "") + score.toFixed(2)
                    : "—"}
                </span>
              </span>
            </button>

            {/* Drill-down toggle */}
            <button
              onClick={() => onDrilldown(cluster.id)}
              title={isDrilled ? "Close drill-down" : "Drill into dimensions"}
              className={`shrink-0 p-0.5 rounded transition-all cursor-pointer ${
                isDrilled
                  ? "text-foreground bg-background opacity-100"
                  : "text-muted-foreground opacity-0 group-hover:opacity-100 hover:text-foreground"
              }`}
            >
              {isDrilled ? <X size={12} /> : <ChevronRight size={12} />}
            </button>
          </div>
        );
      })}
      <p className="text-[10px] text-muted-foreground/40 mt-2 px-2 leading-snug">
        Click to toggle · hover <ChevronRight size={8} className="inline" /> to drill
      </p>
    </div>
  );
}

function CustomTooltip({
  active,
  payload,
  label,
  labelMap,
}: {
  active?: boolean;
  payload?: Array<{ name: string; value: number | null; color: string }>;
  label?: string;
  labelMap: Record<string, string>;
}) {
  if (!active || !payload?.length) return null;

  const articleCount = payload.find((p) => p.name === "__articleCount")?.value ?? null;
  const sorted = [...payload]
    .filter((p) => p.name !== "__articleCount")
    .filter((p) => typeof p.value === "number" && Number.isFinite(p.value))
    .sort((a, b) => (b.value as number) - (a.value as number));

  return (
    <div className="bg-background border rounded-lg shadow-lg p-3 text-xs max-w-[220px]">
      <p className="font-semibold mb-2 text-muted-foreground">{label}</p>
      {typeof articleCount === "number" ? (
        <p className="mb-2 text-[11px] text-muted-foreground">
          Articles: <span className="font-mono tabular-nums">{articleCount}</span>
        </p>
      ) : null}
      {sorted.map((p) => {
        const numericValue = typeof p.value === "number" && Number.isFinite(p.value) ? p.value : null;
        if (numericValue == null) return null;
        const displayLabel = labelMap[p.name] ?? p.name;
        const isPos = numericValue > 0.05;
        const isNeg = numericValue < -0.05;
        return (
          <div key={p.name} className="flex items-center gap-1.5 py-0.5">
            <span
              className="w-2 h-2 rounded-full shrink-0"
              style={{ backgroundColor: p.color }}
            />
            <span className="flex-1 truncate text-foreground/80">
              {displayLabel}
            </span>
            <span
              className={`font-mono tabular-nums ${isPos ? "text-emerald-500" : isNeg ? "text-rose-500" : "text-muted-foreground"}`}
            >
              {numericValue >= 0 ? "+" : ""}
              {numericValue.toFixed(3)}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function BenchmarkOpenTick({
  cx,
  cy,
  payload,
}: {
  cx?: number;
  cy?: number;
  payload?: {
    __benchmarkOpen?: number | null;
    __benchmarkClose?: number | null;
  };
}) {
  if (!Number.isFinite(cx) || !Number.isFinite(cy)) return null;
  const x = cx as number;
  const y = cy as number;
  const open = payload?.__benchmarkOpen;
  const close = payload?.__benchmarkClose;
  const isUp = typeof open === "number" && typeof close === "number" && close >= open;
  const color = isUp ? "#10b981" : "#ef4444";
  return (
    <line
      x1={x - 6}
      x2={x - 1}
      y1={y}
      y2={y}
      stroke={color}
      strokeWidth={1.6}
      strokeLinecap="round"
    />
  );
}

function BenchmarkCloseTick({
  cx,
  cy,
  payload,
}: {
  cx?: number;
  cy?: number;
  payload?: {
    __benchmarkOpen?: number | null;
    __benchmarkClose?: number | null;
  };
}) {
  if (!Number.isFinite(cx) || !Number.isFinite(cy)) return null;
  const x = cx as number;
  const y = cy as number;
  const open = payload?.__benchmarkOpen;
  const close = payload?.__benchmarkClose;
  const isUp = typeof open === "number" && typeof close === "number" && close >= open;
  const color = isUp ? "#10b981" : "#ef4444";
  return (
    <line
      x1={x + 1}
      x2={x + 6}
      y1={y}
      y2={y}
      stroke={color}
      strokeWidth={1.8}
      strokeLinecap="round"
    />
  );
}

function DimensionDrilldown({
  clusterId,
  chartData,
  maWindow,
  latestDimScores,
  mode,
  chartHeight = 260,
}: {
  clusterId: string;
  chartData: Array<{ date: string; [key: string]: number | string | null }>;
  maWindow: number;
  latestDimScores: Record<string, number | null>;
  mode: ViewMode;
  chartHeight?: number;
}) {
  const cluster = CLUSTERS.find((c) => c.id === clusterId);
  if (!cluster) return null;

  const dims = cluster.dimensions;
  const clusterColor = CLUSTER_COLORS[clusterId];

  const allDimKeys = new Set(dims.map((d) => d.key));
  const [selectedDims, setSelectedDims] = useState<Set<string>>(allDimKeys);

  function toggleDim(key: string) {
    setSelectedDims((prev) => {
      const next = new Set(prev);
      if (next.has(key)) { if (next.size > 1) next.delete(key); }
      else next.add(key);
      return next;
    });
  }

  function focusDim(key: string) {
    setSelectedDims((prev) => {
      if (prev.size === 1 && prev.has(key)) return allDimKeys;
      return new Set([key]);
    });
  }

  // Sort dimensions by latest score (desc)
  const sortedDims = [...dims].sort((a, b) => {
    const sa = latestDimScores[a.key] ?? 0;
    const sb = latestDimScores[b.key] ?? 0;
    return sb - sa;
  });

  const labelMap = Object.fromEntries(dims.map((d) => [d.key, d.label]));

  return (
    <div
      className="border border-border rounded-xl p-4 flex flex-col gap-4"
      style={{ borderLeftColor: clusterColor, borderLeftWidth: 3 }}
    >
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-semibold">{cluster.label}</p>
          <p className="text-[11px] text-muted-foreground mt-0.5">
            {dims.length} dimensions ·{" "}
            {maWindow === 0
              ? "no smoothing"
              : `${maWindow}${mode === "hourly" ? "h" : "d"} MA`}
          </p>
        </div>
      </div>

      <div className="flex gap-6">
        {/* Dimension chart */}
        <div className="flex-1 min-w-0">
          <ResponsiveContainer width="100%" height={chartHeight}>
            <LineChart
              data={chartData}
              margin={{ top: 5, right: 10, left: 0, bottom: 5 }}
            >
              <CartesianGrid
                strokeDasharray="3 3"
                stroke="currentColor"
                strokeOpacity={0.1}
              />
              <XAxis
                dataKey="date"
                tick={{ fontSize: 10, fill: "currentColor", opacity: 0.5 }}
                tickLine={false}
                tickFormatter={(v: string) => formatBucket(v, mode)}
                interval="preserveStartEnd"
              />
              <YAxis
                domain={["auto", "auto"]}
                allowDataOverflow={false}
                tick={{ fontSize: 10, fill: "currentColor", opacity: 0.5 }}
                tickLine={false}
                axisLine={false}
                tickFormatter={(v: number) =>
                  (v >= 0 ? "+" : "") + v.toFixed(1)
                }
                width={38}
              />
              <ReferenceLine
                y={0}
                stroke="currentColor"
                strokeOpacity={0.3}
                strokeWidth={1}
              />
              <Tooltip content={<CustomTooltip labelMap={labelMap} />} />
              {dims.map((dim, i) => (
                <Line
                  key={dim.key}
                  type="monotone"
                  dataKey={dim.key}
                  name={dim.key}
                  stroke={DIM_PALETTE[i % DIM_PALETTE.length]}
                  dot={false}
                  strokeWidth={1.5}
                  strokeOpacity={selectedDims.has(dim.key) ? 1 : 0.15}
                  connectNulls
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>

        {/* Dimension scores */}
        <div className="w-52 shrink-0 flex flex-col gap-1">
          <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground mb-1">
            Latest Score
          </p>
          {sortedDims.map((dim) => {
            const score = latestDimScores[dim.key];
            const isPos = score != null && score > 0.05;
            const isNeg = score != null && score < -0.05;
            const isSelected = selectedDims.has(dim.key);
            return (
              <button
                key={dim.key}
                onClick={() => toggleDim(dim.key)}
                onDoubleClick={(e) => { e.preventDefault(); focusDim(dim.key); }}
                className={`flex items-center gap-2 px-2 py-1 rounded text-xs w-full text-left transition-opacity hover:bg-muted/50 ${!isSelected ? "opacity-40" : ""}`}
                title={`${dim.description} · Click to toggle · Double-click to focus`}
              >
                <span
                  className="w-2 h-2 rounded-full shrink-0"
                  style={{
                    backgroundColor:
                      DIM_PALETTE[dims.indexOf(dim) % DIM_PALETTE.length],
                  }}
                />
                <span className="flex-1 truncate text-foreground/80">
                  {dim.label}
                </span>
                <span
                  className={`font-mono tabular-nums shrink-0 ${isPos ? "text-emerald-500" : isNeg ? "text-rose-500" : "text-muted-foreground"}`}
                >
                  {score != null
                    ? (score >= 0 ? "+" : "") + score.toFixed(2)
                    : "—"}
                </span>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}

// ── main component ───────────────────────────────────────────────────────────

const MA_OPTIONS: Record<ViewMode, { label: string; value: number }[]> = {
  daily: [
    { label: "Off", value: 0 },
    { label: "3d", value: 3 },
    { label: "7d", value: 7 },
    { label: "14d", value: 14 },
    { label: "30d", value: 30 },
  ],
  hourly: [
    { label: "Off", value: 0 },
    { label: "3h", value: 3 },
    { label: "6h", value: 6 },
    { label: "12h", value: 12 },
    { label: "24h", value: 24 },
  ],
};

const DEFAULT_MA: Record<ViewMode, number> = { daily: 7, hourly: 6 };

type QuickRange = "7d" | "30d" | "90d" | "1y" | "custom";

function toDateInputValue(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso.slice(0, 10) : localDateStr(d);
}

export function NewsTrendsUI({ articles, chartHeight = 400 }: { articles: ArticleImpact[]; chartHeight?: number }) {
  const [viewMode, setViewMode] = useState<ViewMode>("daily");
  const [maWindow, setMaWindow] = useState(7);
  const [aggregationMode, setAggregationMode] = useState<AggregationMode>("period");
  const [selected, setSelected] = useState<Set<string>>(
    new Set(CLUSTERS.map((c) => c.id)),
  );
  const [drilldownId, setDrilldownId] = useState<string | null>(null);

  // Date range filter
  const allDates = useMemo(
    () => articles.map((a) => toDateInputValue(a.published_at)).sort(),
    [articles],
  );
  const minDate = allDates[0] ?? "";
  const maxDate = allDates[allDates.length - 1] ?? "";

  const [dateFrom, setDateFrom] = useState<string>("");
  const [dateTo, setDateTo] = useState<string>("");
  const [quickRange, setQuickRange] = useState<QuickRange>("1y");
  const [benchmark, setBenchmark] = useState<BenchmarkId>("none");
  const [benchmarkData, setBenchmarkData] = useState<OhlcPoint[]>([]);
  const [showClusterMean, setShowClusterMean] = useState(true);
  const [showArticleCount, setShowArticleCount] = useState(true);
  const [showUsSessionMarkers, setShowUsSessionMarkers] = useState(true);

  function applyQuickRange(range: QuickRange) {
    setQuickRange(range);
    if (range === "custom") return;
    const days = range === "7d" ? 7 : range === "30d" ? 30 : range === "90d" ? 90 : 365;
    const [ey, em, ed] = (maxDate || localDateStr(new Date())).split("-").map(Number);
    const end = new Date(ey, em - 1, ed); // local midnight
    const start = new Date(end);
    start.setDate(start.getDate() - days);
    setDateFrom(localDateStr(start));
    setDateTo(localDateStr(end));
  }

  const filteredArticles = useMemo(() => {
    if (!dateFrom && !dateTo) return articles;
    return articles.filter((a) => {
      const d = toDateInputValue(a.published_at);
      if (dateFrom && d < dateFrom) return false;
      if (dateTo && d > dateTo) return false;
      return true;
    });
  }, [articles, dateFrom, dateTo]);

  function switchMode(mode: ViewMode) {
    setViewMode(mode);
    setMaWindow((prev) => (prev === 0 ? 0 : DEFAULT_MA[mode]));
  }

  const daily = useMemo(() => {
    const raw = buildPeriodData(filteredArticles, viewMode);
    const start = dateFrom || minDate;
    const end = dateTo || maxDate;
    return fillDateGaps(raw, viewMode, start, end);
  }, [filteredArticles, viewMode, dateFrom, dateTo, minDate, maxDate]);
  const effectiveMaWindow = maWindow === 0 ? 1 : maWindow;

  const chartDataBase = useMemo(
    () => applyClusterMA(daily, effectiveMaWindow),
    [daily, effectiveMaWindow],
  );
  const chartData = useMemo(() => {
    if (aggregationMode === "period") return chartDataBase;
    return accumulateSeries(
      chartDataBase,
      [...CLUSTERS.map((c) => c.id), "__clusterMean"],
    );
  }, [aggregationMode, chartDataBase]);

  useEffect(() => {
    const symbol = BENCHMARK_OPTIONS.find((b) => b.id === benchmark)?.symbol;
    if (!symbol) {
      setBenchmarkData([]);
      return;
    }

    let cancelled = false;
    const interval = viewMode === "hourly" ? "1hour" : "1day";
    fmpGetOhlc(symbol, interval)
      .then((res) => {
        if (!res.ok) throw new Error("Failed benchmark fetch");
        const raw = res.data;
        return raw
          .map((r) => ({
            date: String(r.date ?? ""),
            open: Number(r.open),
            high: Number(r.high),
            low: Number(r.low),
            close: Number(r.close),
          }))
          .filter(
            (r) =>
              r.date &&
              Number.isFinite(r.open) &&
              Number.isFinite(r.high) &&
              Number.isFinite(r.low) &&
              Number.isFinite(r.close),
          );
      })
      .then((rows) => {
        if (!cancelled) setBenchmarkData(rows);
      })
      .catch(() => {
        if (!cancelled) setBenchmarkData([]);
      });

    return () => {
      cancelled = true;
    };
  }, [benchmark, viewMode]);

  const benchmarkByBucket = useMemo(() => {
    if (benchmark === "none" || benchmarkData.length === 0 || daily.length === 0) {
      return new Map<string, { open: number; high: number; low: number; close: number }>();
    }

    const startBucket = daily[0]?.date;
    const endBucket = daily[daily.length - 1]?.date;
    if (!startBucket || !endBucket) {
      return new Map<string, { open: number; high: number; low: number; close: number }>();
    }

    const bucketValues = new Map<
      string,
      { open: number; high: number; low: number; close: number }
    >();
    for (const p of benchmarkData) {
      const bucket = normalizeToBucket(p.date, viewMode);
      if (!bucket) continue;
      if (bucket < startBucket || bucket > endBucket) continue;
      bucketValues.set(bucket, {
        open: p.open,
        high: p.high,
        low: p.low,
        close: p.close,
      });
    }

    const sortedBuckets = Array.from(bucketValues.keys()).sort((a, b) => a.localeCompare(b));
    if (sortedBuckets.length === 0) {
      return new Map<string, { open: number; high: number; low: number; close: number }>();
    }

    const base = bucketValues.get(sortedBuckets[0])?.open ?? Number.NaN;
    if (!Number.isFinite(base) || Math.abs(base) < 1e-9) {
      return new Map<string, { open: number; high: number; low: number; close: number }>();
    }

    return new Map(
      sortedBuckets.map((bucket) => {
        const ohlc = bucketValues.get(bucket)!;
        return [
          bucket,
          {
            open: (ohlc.open - base) / base,
            high: (ohlc.high - base) / base,
            low: (ohlc.low - base) / base,
            close: (ohlc.close - base) / base,
          },
        ] as const;
      }),
    );
  }, [benchmark, benchmarkData, daily, viewMode]);

  const chartDataWithBenchmark = useMemo(() => {
    if (benchmark === "none" || benchmarkByBucket.size === 0) return chartData;
    return chartData.map((point) => {
      const benchmarkValue = benchmarkByBucket.get(String(point.date));
      return {
        ...point,
        __benchmarkOpen: benchmarkValue?.open ?? null,
        __benchmarkHigh: benchmarkValue?.high ?? null,
        __benchmarkLow: benchmarkValue?.low ?? null,
        __benchmarkClose: benchmarkValue?.close ?? null,
        __benchmarkMid:
          benchmarkValue != null ? (benchmarkValue.high + benchmarkValue.low) / 2 : null,
        __benchmarkRangeLow:
          benchmarkValue != null ? (benchmarkValue.high - benchmarkValue.low) / 2 : null,
        __benchmarkRangeHigh:
          benchmarkValue != null ? (benchmarkValue.high - benchmarkValue.low) / 2 : null,
      };
    });
  }, [benchmark, benchmarkByBucket, chartData]);

  const usSessionMarkers = useMemo(() => {
    if (!showUsSessionMarkers || viewMode !== "hourly" || chartDataWithBenchmark.length === 0) {
      return {
        openBuckets: [] as string[],
        closeBuckets: [] as string[],
        sessions: [] as Array<{ start: string; end: string }>,
      };
    }

    const tradingDays = new Map<
      string,
      { year: number; month: number; day: number }
    >();
    for (const point of chartDataWithBenchmark) {
      const dateStr = String(point.date);
      const [localDatePart] = dateStr.split("T");
      if (!localDatePart) continue;
      const localMidnight = new Date(`${localDatePart}T00:00:00`);
      if (Number.isNaN(localMidnight.getTime())) continue;
      const ny = getTimeZoneParts(localMidnight, "America/New_York");
      const nyKey = `${ny.year}-${pad2(ny.month)}-${pad2(ny.day)}`;
      if (!tradingDays.has(nyKey) && isUsMarketTradingDayNyDate(ny.year, ny.month, ny.day)) {
        tradingDays.set(nyKey, { year: ny.year, month: ny.month, day: ny.day });
      }
    }

    const dataBuckets = new Set(chartDataWithBenchmark.map((p) => String(p.date)));
    const openBuckets = new Set<string>();
    const closeBuckets = new Set<string>();
    const sessions: Array<{ start: string; end: string }> = [];

    for (const day of tradingDays.values()) {
      const openLocalBucket = localBucket(
        nyTimeToUtcDate(day.year, day.month, day.day, 9, 30),
        "hourly",
      );
      const closeLocalBucket = localBucket(
        nyTimeToUtcDate(day.year, day.month, day.day, 16, 0),
        "hourly",
      );
      if (dataBuckets.has(openLocalBucket)) openBuckets.add(openLocalBucket);
      if (dataBuckets.has(closeLocalBucket)) closeBuckets.add(closeLocalBucket);
      if (dataBuckets.has(openLocalBucket) && dataBuckets.has(closeLocalBucket)) {
        sessions.push({ start: openLocalBucket, end: closeLocalBucket });
      }
    }

    return {
      openBuckets: Array.from(openBuckets).sort((a, b) => a.localeCompare(b)),
      closeBuckets: Array.from(closeBuckets).sort((a, b) => a.localeCompare(b)),
      sessions: sessions.sort((a, b) => a.start.localeCompare(b.start)),
    };
  }, [chartDataWithBenchmark, showUsSessionMarkers, viewMode]);

  const [articleModalDate, setArticleModalDate] = useState<string | null>(null);

  const articlesByBucket = useMemo(() => {
    const map = new Map<string, ArticleImpact[]>();
    for (const a of articles) {
      const bucket = toBucket(a.published_at, viewMode);
      if (!map.has(bucket)) map.set(bucket, []);
      map.get(bucket)!.push(a);
    }
    return map;
  }, [articles, viewMode]);

  const modalArticles = articleModalDate ? (articlesByBucket.get(articleModalDate) ?? []) : [];

  /** X-axis zoom: Brush strip below the chart */
  const [brushRange, setBrushRange] = useState<{
    startIndex: number;
    endIndex: number;
  } | null>(null);

  /** Click-drag on the chart: highlight a period (separate from brush zoom) */
  const [rangeSelectDrag, setRangeSelectDrag] = useState<{
    start: number;
    cur: number;
  } | null>(null);
  const [periodSelection, setPeriodSelection] = useState<{
    start: number;
    end: number;
  } | null>(null);
  const [periodZeitgeistOpen, setPeriodZeitgeistOpen] = useState(false);
  const [periodModalSortCluster, setPeriodModalSortCluster] = useState<string>(
    () => CLUSTERS[0]?.id ?? "",
  );
  const [periodModalSortDir, setPeriodModalSortDir] = useState<"desc" | "asc">("desc");
  const rangeDragRef = useRef<{ start: number; cur: number } | null>(null);
  const brushBlockRef = useRef(false);
  /** Outer chart stack (plot uses full width); used with clientX for stable index mapping. */
  const chartSelectAreaRef = useRef<HTMLDivElement>(null);

  const dataLen = chartDataWithBenchmark.length;
  const lastIdx = Math.max(0, dataLen - 1);
  const plotLeftGutterPx = 40;
  const plotRightGutterPx = benchmark !== "none" ? 56 : 12;

  const dataBoundsKey =
    dataLen > 0
      ? `${chartDataWithBenchmark[0].date}:${chartDataWithBenchmark[dataLen - 1].date}:${dataLen}`
      : "";

  useEffect(() => {
    setBrushRange(null);
    setPeriodSelection(null);
    setRangeSelectDrag(null);
    rangeDragRef.current = null;
    setPeriodZeitgeistOpen(false);
  }, [dataBoundsKey]);

  const brushStart = brushRange?.startIndex ?? 0;
  const brushEnd = brushRange?.endIndex ?? lastIdx;

  const clampedBrushStart = Number.isFinite(brushStart)
    ? Math.max(0, Math.min(lastIdx, brushStart))
    : 0;
  const clampedBrushEnd = Number.isFinite(brushEnd)
    ? Math.max(0, Math.min(lastIdx, brushEnd))
    : lastIdx;
  const normalizedBrushStart = Math.min(clampedBrushStart, clampedBrushEnd);
  const normalizedBrushEnd = Math.max(clampedBrushStart, clampedBrushEnd);
  const hasValidControlledBrush =
    brushRange != null &&
    Number.isFinite(normalizedBrushStart) &&
    Number.isFinite(normalizedBrushEnd) &&
    normalizedBrushStart >= 0 &&
    normalizedBrushEnd <= lastIdx;

  const handleBrushChange = (next: { startIndex?: number; endIndex?: number } | null) => {
    if (!next) {
      setBrushRange(null);
      return;
    }
    const nextStartRaw = next.startIndex;
    const nextEndRaw = next.endIndex;
    if (!Number.isFinite(nextStartRaw) || !Number.isFinite(nextEndRaw)) return;
    const nextStart = Math.max(0, Math.min(lastIdx, nextStartRaw as number));
    const nextEnd = Math.max(0, Math.min(lastIdx, nextEndRaw as number));
    if (nextStart === 0 && nextEnd === lastIdx) {
      setBrushRange(null);
    } else {
      setBrushRange({ startIndex: nextStart, endIndex: nextEnd });
    }
  };

  const applyRangeDragClientX = useCallback(
    (clientX: number) => {
      const d = rangeDragRef.current;
      if (!d) return;
      const node = chartSelectAreaRef.current;
      if (!node || dataLen < 2) return;
      const idx = clientXToDataIndex(
        clientX,
        node.getBoundingClientRect(),
        dataLen,
        plotLeftGutterPx,
        plotRightGutterPx,
      );
      rangeDragRef.current = { start: d.start, cur: idx };
      setRangeSelectDrag((prev) => (prev ? { start: prev.start, cur: idx } : null));
    },
    [dataLen, plotLeftGutterPx, plotRightGutterPx],
  );

  const finishRangeDrag = useCallback(() => {
    const d = rangeDragRef.current;
    if (!d) return;
    rangeDragRef.current = null;
    setRangeSelectDrag(null);
    if (d.start === d.cur) {
      setPeriodSelection(null);
      setPeriodZeitgeistOpen(false);
      return;
    }
    const lo = Math.min(d.start, d.cur);
    const hi = Math.max(d.start, d.cur);
    setPeriodSelection({ start: lo, end: hi });
  }, []);

  useEffect(() => {
    window.addEventListener("mouseup", finishRangeDrag);
    return () => window.removeEventListener("mouseup", finishRangeDrag);
  }, [finishRangeDrag]);

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!rangeDragRef.current) return;
      applyRangeDragClientX(e.clientX);
    };
    window.addEventListener("mousemove", onMove);
    return () => window.removeEventListener("mousemove", onMove);
  }, [applyRangeDragClientX]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (periodZeitgeistOpen) {
        setPeriodZeitgeistOpen(false);
        return;
      }
      setPeriodSelection(null);
      setRangeSelectDrag(null);
      rangeDragRef.current = null;
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [periodZeitgeistOpen]);

  const handleChartMouseDown = (
    _state: MouseHandlerDataParam,
    event?: ReactMouseEvent<SVGGraphicsElement>,
  ) => {
    if (brushBlockRef.current) {
      brushBlockRef.current = false;
      return;
    }
    if (dataLen < 2 || !event) return;
    const node = chartSelectAreaRef.current;
    if (!node) return;
    const idx = clientXToDataIndex(
      event.clientX,
      node.getBoundingClientRect(),
      dataLen,
      plotLeftGutterPx,
      plotRightGutterPx,
    );
    rangeDragRef.current = { start: idx, cur: idx };
    setRangeSelectDrag({ start: idx, cur: idx });
  };

  const handleChartMouseMove = (
    _state: MouseHandlerDataParam,
    event?: ReactMouseEvent<SVGGraphicsElement>,
  ) => {
    if (!rangeDragRef.current || !event) return;
    applyRangeDragClientX(event.clientX);
  };

  const handleChartDoubleClick = (state: MouseHandlerDataParam) => {
    setBrushRange(null);
    const label = (state as { activeLabel?: unknown })?.activeLabel;
    if (typeof label === "string") {
      setArticleModalDate(label);
    }
  };

  const highlightLoHi = useMemo(() => {
    if (rangeSelectDrag) {
      return {
        lo: Math.min(rangeSelectDrag.start, rangeSelectDrag.cur),
        hi: Math.max(rangeSelectDrag.start, rangeSelectDrag.cur),
      };
    }
    if (periodSelection) {
      return {
        lo: Math.min(periodSelection.start, periodSelection.end),
        hi: Math.max(periodSelection.start, periodSelection.end),
      };
    }
    return null;
  }, [rangeSelectDrag, periodSelection]);

  const periodArticles = useMemo(() => {
    if (!periodSelection || chartDataWithBenchmark.length === 0) return [];
    const lo = Math.min(periodSelection.start, periodSelection.end);
    const hi = Math.max(periodSelection.start, periodSelection.end);
    const startBucket = String(chartDataWithBenchmark[lo]?.date ?? "");
    const endBucket = String(chartDataWithBenchmark[hi]?.date ?? "");
    if (!startBucket || !endBucket) return [];
    return articlesInBucketRange(filteredArticles, startBucket, endBucket, viewMode)
      .slice()
      .sort(
        (a, b) =>
          new Date(b.published_at).getTime() - new Date(a.published_at).getTime(),
      );
  }, [periodSelection, chartDataWithBenchmark, filteredArticles, viewMode]);

  const sortedPeriodArticles = useMemo(() => {
    if (periodArticles.length === 0) return periodArticles;
    const cid = periodModalSortCluster || CLUSTERS[0]?.id;
    if (!cid) return periodArticles;
    const dir = periodModalSortDir;
    return [...periodArticles].sort((a, b) => {
      const sa = clusterMeanImpact(a, cid);
      const sb = clusterMeanImpact(b, cid);
      const aNull = sa == null;
      const bNull = sb == null;
      if (aNull && bNull) return 0;
      if (aNull) return 1;
      if (bNull) return -1;
      const diff = sa - sb;
      if (diff !== 0) return dir === "desc" ? -diff : diff;
      return new Date(b.published_at).getTime() - new Date(a.published_at).getTime();
    });
  }, [periodArticles, periodModalSortCluster, periodModalSortDir]);

  const explainIconIndex =
    periodSelection && !rangeSelectDrag
      ? Math.max(periodSelection.start, periodSelection.end)
      : null;

  // Drill-down: dimension MA data for the selected cluster
  const drilldownDims = useMemo(() => {
    if (!drilldownId) return null;
    const cluster = CLUSTERS.find((c) => c.id === drilldownId);
    if (!cluster) return null;
    return cluster.dimensions;
  }, [drilldownId]);

  const dimensionChartDataBase = useMemo(() => {
    if (!drilldownDims) return [];
    return applyDimensionMA(
      daily,
      effectiveMaWindow,
      drilldownDims.map((d) => d.key),
    );
  }, [daily, effectiveMaWindow, drilldownDims]);
  const dimensionChartData = useMemo(() => {
    if (aggregationMode === "period" || !drilldownDims) return dimensionChartDataBase;
    return accumulateSeries(dimensionChartDataBase, drilldownDims.map((d) => d.key));
  }, [aggregationMode, dimensionChartDataBase, drilldownDims]);

  // Latest dimension scores for the drilled-down cluster
  const latestDimScores = useMemo(() => {
    if (!drilldownDims || dimensionChartData.length === 0) return {};
    const last = dimensionChartData[dimensionChartData.length - 1];
    return Object.fromEntries(
      drilldownDims.map((d) => [d.key, last[d.key] as number | null]),
    );
  }, [drilldownDims, dimensionChartData]);

  const latestScores = useMemo(() => {
    if (chartData.length === 0) return {} as Record<string, number | null>;
    const last = chartData[chartData.length - 1];
    return Object.fromEntries(
      CLUSTERS.map((c) => [c.id, last[c.id] as number | null]),
    );
  }, [chartData]);

  function focusCluster(id: string) {
    setSelected((prev) => {
      const allIds = new Set(CLUSTERS.map((c) => c.id));
      // If already focused on this one, restore all
      if (prev.size === 1 && prev.has(id)) return allIds;
      return new Set([id]);
    });
  }

  function toggleCluster(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        if (next.size === 1) return prev;
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }

  function toggleDrilldown(id: string) {
    setDrilldownId((prev) => (prev === id ? null : id));
  }

  if (articles.length === 0) {
    return (
      <div className="text-center py-16 text-muted-foreground">
        <p className="text-sm">No news impact data found.</p>
      </div>
    );
  }


  const totalArticles = daily.reduce((sum, d) => sum + d.count, 0);

  const clusterLabelMap = useMemo(
    () => ({
      ...Object.fromEntries(CLUSTERS.map((c) => [c.id, c.label])),
      __clusterMean: "Mean (all clusters)",
      __articleCount: "Articles",
    }),
    [],
  );

  return (
    <div className="flex flex-col gap-6">
      {/* Controls toolbar */}
      <div className="flex items-stretch rounded-xl border border-border bg-card overflow-x-auto">
        {/* Date range + granularity first */}
        <div className="flex items-center px-3 py-2 border-r border-border shrink-0">
          <span className="text-[10px] font-medium text-muted-foreground/60 uppercase tracking-wide">Range</span>
        </div>
        {(["7d", "30d", "90d", "1y"] as QuickRange[]).map((r) => (
          <button
            key={r}
            onClick={() => applyQuickRange(r)}
            className={`text-[11px] px-3 py-2 transition-colors cursor-pointer border-r border-border ${
              quickRange === r
                ? "bg-foreground text-background"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            {r}
          </button>
        ))}
        <div className="flex items-center gap-1.5 px-3 py-2 border-r border-border shrink-0">
          <input
            type="date"
            value={dateFrom}
            min={minDate}
            max={dateTo || maxDate}
            onChange={(e) => {
              setDateFrom(e.target.value);
              setQuickRange("custom");
            }}
            className="text-[11px] bg-transparent text-foreground focus:outline-none cursor-pointer"
          />
          <span className="text-[10px] text-muted-foreground/40">—</span>
          <input
            type="date"
            value={dateTo}
            min={dateFrom || minDate}
            max={maxDate}
            onChange={(e) => {
              setDateTo(e.target.value);
              setQuickRange("custom");
            }}
            className="text-[11px] bg-transparent text-foreground focus:outline-none cursor-pointer"
          />
        </div>
        <div className="flex items-center gap-2 px-3 py-2 border-r border-border shrink-0">
          <span className="text-[10px] font-medium text-muted-foreground/60 uppercase tracking-wide">View</span>
          <div className="flex rounded border border-border overflow-hidden">
            {(["daily", "hourly"] as ViewMode[]).map((mode) => (
              <button
                key={mode}
                onClick={() => switchMode(mode)}
                className={`text-[11px] px-3 py-1 capitalize transition-colors cursor-pointer ${
                  viewMode === mode
                    ? "bg-foreground text-background"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                {mode}
              </button>
            ))}
          </div>
        </div>

        {/* MA smoothing */}
        <div className="flex items-center gap-2 px-3 py-2 border-r border-border shrink-0">
          <span className="text-[10px] font-medium text-muted-foreground/60 shrink-0">MA</span>
          <div className="flex items-center gap-0.5">
            {MA_OPTIONS[viewMode].map((opt) => (
              <button
                key={opt.value}
                onClick={() => setMaWindow(opt.value)}
                className={`text-[11px] px-2 py-1 rounded transition-colors cursor-pointer ${
                  maWindow === opt.value
                    ? "bg-foreground text-background"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>

        {/* Toggle overlays */}
        <div className="flex items-center px-3 py-2 shrink-0">
          <details className="group relative">
            <summary className="inline-flex list-none items-center rounded border border-border px-2.5 py-1 text-[11px] text-muted-foreground transition-colors hover:text-foreground cursor-pointer [&::-webkit-details-marker]:hidden">
              Advanced
              <ChevronRight className="ml-1 h-3 w-3 transition-transform group-open:rotate-90" />
            </summary>
            <div className="absolute right-0 top-full z-20 mt-1.5 hidden min-w-[180px] rounded-md border border-border bg-background p-1.5 shadow-lg group-open:block">
              <div className="px-2.5 py-1">
                <p className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground/60">
                  Series
                </p>
                <div className="mt-1.5 flex rounded border border-border overflow-hidden">
                  <button
                    onClick={() => setAggregationMode("period")}
                    className={`text-[11px] px-2.5 py-1 transition-colors cursor-pointer ${
                      aggregationMode === "period"
                        ? "bg-foreground text-background"
                        : "text-muted-foreground hover:text-foreground"
                    }`}
                  >
                    Period
                  </button>
                  <button
                    onClick={() => setAggregationMode("cumulative")}
                    className={`text-[11px] px-2.5 py-1 transition-colors cursor-pointer ${
                      aggregationMode === "cumulative"
                        ? "bg-foreground text-background"
                        : "text-muted-foreground hover:text-foreground"
                    }`}
                  >
                    Cumul.
                  </button>
                </div>
              </div>
              <div className="px-2.5 py-1">
                <p className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground/60">
                  Index
                </p>
                <select
                  value={benchmark}
                  onChange={(e) => setBenchmark(e.target.value as BenchmarkId)}
                  className="mt-1.5 w-full text-[11px] border border-border rounded px-1.5 py-1 bg-background cursor-pointer focus:outline-none focus:ring-1 focus:ring-ring"
                >
                  {BENCHMARK_OPTIONS.map((b) => (
                    <option key={b.id} value={b.id}>{b.label}</option>
                  ))}
                </select>
              </div>
              <button
                onClick={() => setShowClusterMean((v) => !v)}
                className={`w-full text-left text-[11px] px-2.5 py-1.5 rounded transition-colors cursor-pointer ${
                  showClusterMean
                    ? "bg-foreground/10 text-foreground"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground"
                }`}
              >
                Mean
              </button>
              <button
                onClick={() => setShowArticleCount((v) => !v)}
                className={`w-full text-left text-[11px] px-2.5 py-1.5 rounded transition-colors cursor-pointer ${
                  showArticleCount
                    ? "bg-foreground/10 text-foreground"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground"
                }`}
              >
                Volume
              </button>
              <button
                onClick={() => viewMode === "hourly" && setShowUsSessionMarkers((v) => !v)}
                disabled={viewMode !== "hourly"}
                className={`w-full text-left text-[11px] px-2.5 py-1.5 rounded transition-colors cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed ${
                  showUsSessionMarkers && viewMode === "hourly"
                    ? "bg-foreground/10 text-foreground"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground"
                }`}
              >
                Sessions
              </button>
            </div>
          </details>
        </div>

        {/* Article count */}
        <div className="ml-auto flex items-center px-4 py-2 border-l border-border shrink-0 bg-muted/20">
          <div className="text-right">
            <p className="text-[9px] font-medium uppercase tracking-wide text-muted-foreground/50 leading-none">Articles</p>
            <p className="text-sm font-semibold tabular-nums leading-tight">{totalArticles.toLocaleString()}</p>
          </div>
        </div>
      </div>

      <div className="flex gap-4">
        {/* Main cluster chart */}
        <div className="flex-1 min-w-0">
          <div className="border rounded-xl p-4">
            <div className="flex items-start justify-between mb-3">
              <div>
                <p className="text-sm font-medium text-foreground/90">
                  {aggregationMode === "cumulative" ? "Cumulative Impact" : "Period Impact"}
                  {maWindow > 0 && (
                    <span className="ml-2 text-[11px] font-normal text-muted-foreground">
                      {maWindow}{viewMode === "hourly" ? "h" : "d"} MA
                    </span>
                  )}
                  {maWindow === 0 && (
                    <span className="ml-2 text-[11px] font-normal text-muted-foreground">no smoothing</span>
                  )}
                </p>
                <p className="text-[11px] text-muted-foreground/70 mt-0.5">
                  −1 bearish → +1 bullish · drag chart to select range · dbl-click for articles
                  {benchmark !== "none" ? " · OHLC ticks = benchmark" : ""}
                </p>
              </div>
            </div>
            <div
              ref={chartSelectAreaRef}
              className="relative select-none [&_.recharts-wrapper]:cursor-crosshair [&_.recharts-brush]:cursor-grab"
              onMouseDownCapture={(e) => {
                const t = e.target as HTMLElement | null;
                brushBlockRef.current = !!t?.closest?.(".recharts-brush");
              }}
            >
              {viewMode === "hourly" && showUsSessionMarkers ? (
                <div className="pointer-events-none absolute left-2 top-2 z-10 rounded-md border border-border bg-background/90 px-2 py-1 text-[10px] text-muted-foreground shadow-sm">
                  <span className="inline-flex items-center gap-1">
                    <span className="inline-block h-2 w-2 rounded-full bg-[hsl(var(--chart-2))]" />
                    Open 09:30 ET
                  </span>
                  <span className="mx-1.5 opacity-50">|</span>
                  <span className="inline-flex items-center gap-1">
                    <span className="inline-block h-2 w-2 rounded-full bg-[hsl(var(--chart-5))]" />
                    Close 16:00 ET
                  </span>
                </div>
              ) : null}
              {explainIconIndex !== null &&
                dataLen > 1 &&
                !Number.isNaN(explainIconIndex) && (
                  <div
                    className="pointer-events-none absolute z-10"
                    style={{
                      top: 6,
                      bottom: 42,
                      left: 0,
                      right: 0,
                    }}
                  >
                    <div
                      className="pointer-events-auto absolute top-1 flex items-center gap-0.5"
                      style={{
                        left: `calc(${plotLeftGutterPx}px + (100% - ${plotLeftGutterPx + plotRightGutterPx}px) * ${explainIconIndex / Math.max(1, dataLen - 1)})`,
                        transform: "translateX(-50%)",
                      }}
                    >
                      <button
                        type="button"
                        className="rounded-full border border-border bg-background/95 p-1.5 shadow-sm text-primary hover:bg-muted transition-colors"
                        title="Period context — articles in this range (AI zeitgeist summary coming later)"
                        aria-label="Open articles for selected period"
                        onClick={() => setPeriodZeitgeistOpen(true)}
                      >
                        <Sparkles className="h-3.5 w-3.5" aria-hidden />
                      </button>
                      <button
                        type="button"
                        className="rounded-full border border-border bg-background/95 p-1 shadow-sm text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
                        title="Clear selection"
                        aria-label="Clear period selection"
                        onClick={() => {
                          setPeriodSelection(null);
                          setPeriodZeitgeistOpen(false);
                        }}
                      >
                        <X className="h-3 w-3" aria-hidden />
                      </button>
                    </div>
                  </div>
                )}
              <ResponsiveContainer width="100%" height={chartHeight}>
              <ComposedChart
                  data={chartDataWithBenchmark}
                  margin={{ top: 5, right: 10, left: 0, bottom: 8 }}
                  onMouseDown={handleChartMouseDown}
                  onMouseMove={handleChartMouseMove}
                  onDoubleClick={handleChartDoubleClick}
                >
                <CartesianGrid
                  strokeDasharray="3 3"
                  stroke="currentColor"
                  strokeOpacity={0.1}
                />
                <XAxis
                  dataKey="date"
                  tick={{ fontSize: 10, fill: "currentColor", opacity: 0.5 }}
                  tickLine={false}
                  tickFormatter={(v: string) => formatBucket(v, viewMode)}
                  interval="preserveStartEnd"
                />
                <YAxis
                  domain={["auto", "auto"]}
                  allowDataOverflow={false}
                  tick={{ fontSize: 10, fill: "currentColor", opacity: 0.5 }}
                  tickLine={false}
                  axisLine={false}
                  tickFormatter={(v: number) =>
                    (v >= 0 ? "+" : "") + v.toFixed(1)
                  }
                  width={38}
                />
                {benchmark !== "none" && (
                  <YAxis
                    yAxisId="benchmark"
                    orientation="right"
                    domain={["auto", "auto"]}
                    tick={{ fontSize: 10, fill: "currentColor", opacity: 0.5 }}
                    tickLine={false}
                    axisLine={false}
                    tickFormatter={(v: number) => `${v >= 0 ? "+" : ""}${(v * 100).toFixed(0)}%`}
                    width={44}
                  />
                )}
                {showArticleCount && benchmark === "none" && (
                  <YAxis
                    yAxisId="count"
                    orientation="right"
                    domain={[0, "auto"]}
                    allowDataOverflow={false}
                    tick={{ fontSize: 10, fill: "currentColor", opacity: 0.45 }}
                    tickLine={false}
                    axisLine={false}
                    width={34}
                  />
                )}
                <ReferenceLine
                  y={0}
                  stroke="currentColor"
                  strokeOpacity={0.3}
                  strokeWidth={1}
                />
                {highlightLoHi &&
                dataLen > 1 &&
                chartDataWithBenchmark[highlightLoHi.lo]?.date != null &&
                chartDataWithBenchmark[highlightLoHi.hi]?.date != null ? (
                  <ReferenceArea
                    x1={chartDataWithBenchmark[highlightLoHi.lo]!.date}
                    x2={chartDataWithBenchmark[highlightLoHi.hi]!.date}
                    stroke="hsl(var(--primary) / 0.4)"
                    strokeWidth={1}
                    fill="hsl(var(--primary) / 0.1)"
                    fillOpacity={1}
                    ifOverflow="visible"
                    zIndex={0}
                  />
                ) : null}
                <Tooltip
                  content={<CustomTooltip labelMap={clusterLabelMap} />}
                />
                {showClusterMean ? (
                  <Line
                    type="monotone"
                    dataKey="__clusterMean"
                    name="__clusterMean"
                    stroke="hsl(var(--muted-foreground))"
                    dot={false}
                    strokeWidth={2}
                    strokeDasharray="6 4"
                    connectNulls
                  />
                ) : null}
                {viewMode === "hourly" &&
                  showUsSessionMarkers &&
                  usSessionMarkers.sessions.map((session) => (
                    <ReferenceArea
                      key={`us-session-${session.start}`}
                      x1={session.start}
                      x2={session.end}
                      fill="hsl(var(--chart-2) / 0.07)"
                      ifOverflow="visible"
                      zIndex={0}
                    />
                  ))}
                {viewMode === "hourly" &&
                  showUsSessionMarkers &&
                  usSessionMarkers.openBuckets.map((bucket) => (
                    <ReferenceLine
                      key={`us-open-${bucket}`}
                      x={bucket}
                      stroke="hsl(var(--chart-2))"
                      strokeOpacity={0.75}
                      strokeDasharray="4 3"
                      strokeWidth={1.4}
                    />
                  ))}
                {viewMode === "hourly" &&
                  showUsSessionMarkers &&
                  usSessionMarkers.closeBuckets.map((bucket) => (
                    <ReferenceLine
                      key={`us-close-${bucket}`}
                      x={bucket}
                      stroke="hsl(var(--chart-5))"
                      strokeOpacity={0.75}
                      strokeDasharray="4 3"
                      strokeWidth={1.4}
                    />
                  ))}
                {CLUSTERS.filter((c) => selected.has(c.id)).map((cluster) => (
                  <Line
                    key={cluster.id}
                    type="monotone"
                    dataKey={cluster.id}
                    name={cluster.id}
                    stroke={CLUSTER_COLORS[cluster.id]}
                    dot={false}
                    strokeWidth={drilldownId === cluster.id ? 2.5 : 1.5}
                    strokeOpacity={
                      drilldownId && drilldownId !== cluster.id ? 0.3 : 1
                    }
                    connectNulls
                  />
                ))}
                {benchmark !== "none" && (
                  <Scatter
                    yAxisId="benchmark"
                    dataKey="__benchmarkMid"
                    name={
                      BENCHMARK_OPTIONS.find((b) => b.id === benchmark)?.label ?? "Benchmark"
                    }
                    fill="hsl(var(--muted-foreground))"
                    shape={() => null}
                  >
                    <ErrorBar
                      dataKey={(
                        entry: {
                          __benchmarkRangeLow?: number | null;
                          __benchmarkRangeHigh?: number | null;
                        },
                      ) => [
                        entry.__benchmarkRangeLow ?? 0,
                        entry.__benchmarkRangeHigh ?? 0,
                      ]}
                      direction="y"
                      width={0}
                      stroke="hsl(var(--muted-foreground))"
                      strokeWidth={1.1}
                      opacity={0.8}
                    />
                  </Scatter>
                )}
                {benchmark !== "none" && (
                  <Scatter
                    yAxisId="benchmark"
                    dataKey="__benchmarkOpen"
                    name="Benchmark open"
                    shape={<BenchmarkOpenTick />}
                    fill="hsl(var(--chart-2))"
                  />
                )}
                {benchmark !== "none" && (
                  <Scatter
                    yAxisId="benchmark"
                    dataKey="__benchmarkClose"
                    name="Benchmark close"
                    shape={<BenchmarkCloseTick />}
                    fill="hsl(var(--chart-5))"
                  />
                )}
                {showArticleCount && (
                  <Bar
                    yAxisId="count"
                    dataKey="__articleCount"
                    name="__articleCount"
                    fill="hsl(var(--muted-foreground))"
                    fillOpacity={0.28}
                    stroke="hsl(var(--muted-foreground))"
                    strokeOpacity={0.45}
                    barSize={10}
                  />
                )}
                {dataLen > 1 ? (
                  <Brush
                    dataKey="date"
                    height={32}
                    stroke="hsl(var(--border))"
                    fill="hsl(var(--muted))"
                    travellerWidth={6}
                    startIndex={hasValidControlledBrush ? normalizedBrushStart : undefined}
                    endIndex={hasValidControlledBrush ? normalizedBrushEnd : undefined}
                    onChange={handleBrushChange}
                    tickFormatter={(v: string) => formatBucket(v, viewMode)}
                  />
                ) : null}
              </ComposedChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>

        {/* Leaderboard */}
        <div className="w-52 shrink-0">
          <div className="border rounded-xl p-3">
            <Leaderboard
              latest={latestScores}
              selected={selected}
              drilldownId={drilldownId}
              onToggle={toggleCluster}
              onFocus={focusCluster}
              onDrilldown={toggleDrilldown}
              maOff={maWindow === 0}
              cumulative={aggregationMode === "cumulative"}
            />
          </div>
        </div>
      </div>

      {/* Dimension drill-down panel */}
      {drilldownId && drilldownDims && (
        <DimensionDrilldown
          clusterId={drilldownId}
          chartData={dimensionChartData}
          maWindow={maWindow}
          latestDimScores={latestDimScores}
          mode={viewMode}
          chartHeight={Math.round(chartHeight * 0.65)}
        />
      )}

      {/* Articles modal */}
      {articleModalDate && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
          onClick={() => setArticleModalDate(null)}
        >
          <div
            className="bg-background border rounded-xl shadow-xl w-full max-w-2xl max-h-[80vh] flex flex-col mx-4"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-5 py-4 border-b shrink-0">
              <h2 className="font-semibold text-sm">
                Articles · {formatBucket(articleModalDate, viewMode)}
              </h2>
              <span className="text-xs text-muted-foreground mr-auto ml-3">
                {modalArticles.length} article{modalArticles.length !== 1 ? "s" : ""}
              </span>
              <button
                onClick={() => setArticleModalDate(null)}
                className="text-muted-foreground hover:text-foreground transition-colors"
                aria-label="Close"
              >
                <X size={16} />
              </button>
            </div>
            <div className="overflow-y-auto p-4">
              <ArticlesGrid
                articles={modalArticles.map((a) => ({
                  id: a.id ?? 0,
                  slug: a.slug ?? null,
                  title: a.title ?? null,
                  url: a.url ?? null,
                  image_url: a.image_url ?? null,
                  source: a.source ?? null,
                  published_at: a.published_at,
                  created_at: a.created_at ?? a.published_at,
                }))}
              />
            </div>
          </div>
        </div>
      )}

      {/* Selected period — article list (placeholder for future AI zeitgeist + citations) */}
      {periodZeitgeistOpen && periodSelection && chartDataWithBenchmark.length > 0 && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
          onClick={() => setPeriodZeitgeistOpen(false)}
        >
          <div
            className="bg-background border rounded-xl shadow-xl w-full max-w-2xl max-h-[80vh] flex flex-col mx-4"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-5 py-4 border-b shrink-0 gap-3">
              <div className="min-w-0 flex-1">
                <h2 className="font-semibold text-sm flex items-center gap-2">
                  <Sparkles className="h-4 w-4 shrink-0 text-primary" aria-hidden />
                  Period context
                </h2>
                <p className="text-xs text-muted-foreground mt-1">
                  {formatBucket(
                    String(
                      chartDataWithBenchmark[
                        Math.min(periodSelection.start, periodSelection.end)
                      ]?.date ?? "",
                    ),
                    viewMode,
                  )}
                  {" → "}
                  {formatBucket(
                    String(
                      chartDataWithBenchmark[
                        Math.max(periodSelection.start, periodSelection.end)
                      ]?.date ?? "",
                    ),
                    viewMode,
                  )}
                  {" · "}
                  {periodArticles.length} article
                  {periodArticles.length !== 1 ? "s" : ""}
                </p>
                <p className="text-[11px] text-muted-foreground/90 mt-2 leading-snug">
                  For now this lists headlines in the selected range. Later, an AI
                  summary of the period&apos;s zeitgeist will appear here with links back
                  to these articles.
                </p>
              </div>
              <button
                onClick={() => setPeriodZeitgeistOpen(false)}
                className="text-muted-foreground hover:text-foreground transition-colors shrink-0"
                aria-label="Close"
              >
                <X size={16} />
              </button>
            </div>
            {periodArticles.length > 0 && (
              <div className="flex flex-wrap items-center gap-3 px-5 py-3 border-b bg-muted/20 text-xs">
                <span className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                  Sort by impact
                </span>
                <label className="flex items-center gap-1.5 text-muted-foreground">
                  <span className="sr-only">Cluster</span>
                  <select
                    className="rounded-md border border-border bg-background px-2 py-1.5 text-xs text-foreground max-w-[200px]"
                    value={periodModalSortCluster}
                    onChange={(e) => setPeriodModalSortCluster(e.target.value)}
                  >
                    {CLUSTERS.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="flex items-center gap-1.5 text-muted-foreground">
                  <span className="sr-only">Direction</span>
                  <select
                    className="rounded-md border border-border bg-background px-2 py-1.5 text-xs text-foreground"
                    value={periodModalSortDir}
                    onChange={(e) =>
                      setPeriodModalSortDir(e.target.value === "asc" ? "asc" : "desc")
                    }
                  >
                    <option value="desc">High → low</option>
                    <option value="asc">Low → high</option>
                  </select>
                </label>
              </div>
            )}
            <div className="overflow-y-auto p-4">
              {periodArticles.length === 0 ? (
                <p className="text-sm text-muted-foreground text-center py-8">
                  No articles in this period (try a wider range or different date
                  filters).
                </p>
              ) : (
                <ArticlesGrid
                  articles={sortedPeriodArticles.map((a) => ({
                    id: a.id ?? 0,
                    slug: a.slug ?? null,
                    title: a.title ?? null,
                    url: a.url ?? null,
                    image_url: a.image_url ?? null,
                    source: a.source ?? null,
                    published_at: a.published_at,
                    created_at: a.created_at ?? a.published_at,
                  }))}
                />
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
