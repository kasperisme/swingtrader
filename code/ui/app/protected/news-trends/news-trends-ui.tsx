"use client";

import { useEffect, useMemo, useState } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ReferenceLine,
  ResponsiveContainer,
} from "recharts";
import { TrendingUp, TrendingDown, Minus, ChevronRight, X } from "lucide-react";
import { CLUSTERS } from "../vectors/dimensions";

export interface ArticleImpact {
  published_at: string;
  impact_json: Record<string, number>;
}

// ── cluster palette ──────────────────────────────────────────────────────────
const CLUSTER_COLORS: Record<string, string> = {
  MACRO_SENSITIVITY: "#ef4444",
  SECTOR_ROTATION: "#8b5cf6",
  BUSINESS_MODEL: "#3b82f6",
  FINANCIAL_STRUCTURE: "#06b6d4",
  GROWTH_PROFILE: "#10b981",
  VALUATION_POSITIONING: "#f59e0b",
  GEOGRAPHY_TRADE: "#f97316",
  SUPPLY_CHAIN_EXPOSURE: "#84cc16",
  MARKET_BEHAVIOUR: "#ec4899",
};

// Distinct colors for individual dimensions within a drilled-down cluster
const DIM_PALETTE = [
  "#ef4444",
  "#f97316",
  "#f59e0b",
  "#84cc16",
  "#10b981",
  "#06b6d4",
  "#3b82f6",
  "#8b5cf6",
  "#ec4899",
  "#14b8a6",
];

// ── helpers ──────────────────────────────────────────────────────────────────

type ViewMode = "daily" | "hourly";
type BenchmarkId = "none" | "sp500" | "nasdaq100";

type OhlcPoint = {
  date: string;
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

/** Compute per-period average impact per cluster and dimension */
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
    // Cluster averages
    const clusterSums: Record<string, number[]> = {};
    for (const cluster of CLUSTERS) clusterSums[cluster.id] = [];

    // Dimension averages
    const dimSums: Record<string, number[]> = {};
    for (const key of allDimKeys) dimSums[key] = [];

    for (const row of rows) {
      // Cluster
      for (const cluster of CLUSTERS) {
        const dimKeys = cluster.dimensions.map((d) => d.key);
        const scores = dimKeys
          .map((k) => row.impact_json[k])
          .filter((v) => v != null && !isNaN(v)) as number[];
        if (scores.length > 0) {
          clusterSums[cluster.id].push(
            scores.reduce((a, b) => a + b, 0) / scores.length,
          );
        }
      }
      // Dimensions
      for (const key of allDimKeys) {
        const v = row.impact_json[key];
        if (v != null && !isNaN(v)) dimSums[key].push(v);
      }
    }

    const clusters: Record<string, number | null> = {};
    for (const cluster of CLUSTERS) {
      const arr = clusterSums[cluster.id];
      clusters[cluster.id] =
        arr.length > 0 ? arr.reduce((a, b) => a + b, 0) / arr.length : null;
    }

    const dimensions: Record<string, number | null> = {};
    for (const key of allDimKeys) {
      const arr = dimSums[key];
      dimensions[key] =
        arr.length > 0 ? arr.reduce((a, b) => a + b, 0) / arr.length : null;
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
    };
    for (const cluster of CLUSTERS) {
      const vals = slice
        .map((d) => d.clusters[cluster.id])
        .filter((v): v is number => v != null);
      result[cluster.id] =
        vals.length > 0 ? vals.reduce((a, b) => a + b, 0) / vals.length : null;
    }
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

// ── sub-components ───────────────────────────────────────────────────────────

function Leaderboard({
  latest,
  selected,
  drilldownId,
  onToggle,
  onDrilldown,
}: {
  latest: Record<string, number | null>;
  selected: Set<string>;
  drilldownId: string | null;
  onToggle: (id: string) => void;
  onDrilldown: (id: string) => void;
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
    <div className="flex flex-col gap-1">
      <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2">
        Latest MA Score
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
            className={`flex items-center gap-1 px-2 py-1.5 rounded-lg transition-colors ${
              isDrilled ? "bg-muted ring-1 ring-border" : "hover:bg-muted/50"
            }`}
          >
            {/* Toggle visibility */}
            <button
              onClick={() => onToggle(cluster.id)}
              className={`flex items-center gap-2 flex-1 text-left min-w-0 ${!isSelected ? "opacity-50" : ""}`}
              title="Toggle visibility in chart"
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
              className={`shrink-0 p-0.5 rounded transition-colors ${
                isDrilled
                  ? "text-foreground bg-background"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {isDrilled ? <X size={12} /> : <ChevronRight size={12} />}
            </button>
          </div>
        );
      })}
      <p className="text-[10px] text-muted-foreground mt-1 px-2">
        Click score to toggle · <ChevronRight size={8} className="inline" /> to
        drill down
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

  const sorted = [...payload]
    .filter((p) => p.value != null)
    .sort((a, b) => (b.value ?? 0) - (a.value ?? 0));

  return (
    <div className="bg-background border rounded-lg shadow-lg p-3 text-xs max-w-[220px]">
      <p className="font-semibold mb-2 text-muted-foreground">{label}</p>
      {sorted.map((p) => {
        const displayLabel = labelMap[p.name] ?? p.name;
        const isPos = (p.value ?? 0) > 0.05;
        const isNeg = (p.value ?? 0) < -0.05;
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
              {(p.value ?? 0) >= 0 ? "+" : ""}
              {(p.value ?? 0).toFixed(3)}
            </span>
          </div>
        );
      })}
    </div>
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
      <div>
        <p className="text-sm font-semibold">
          {cluster.label} — Dimension Breakdown
        </p>
        <p className="text-xs text-muted-foreground mt-0.5">
          {maWindow}{mode === "hourly" ? "h" : "d"} MA of individual dimension impact scores · {dims.length}{" "}
          dimensions
        </p>
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
            return (
              <div
                key={dim.key}
                className="flex items-center gap-2 px-2 py-1 rounded text-xs"
                title={dim.description}
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
              </div>
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
    { label: "3d", value: 3 },
    { label: "7d", value: 7 },
    { label: "14d", value: 14 },
    { label: "30d", value: 30 },
  ],
  hourly: [
    { label: "3h", value: 3 },
    { label: "6h", value: 6 },
    { label: "12h", value: 12 },
    { label: "24h", value: 24 },
  ],
};

const DEFAULT_MA: Record<ViewMode, number> = { daily: 7, hourly: 6 };

type QuickRange = "7d" | "30d" | "90d" | "all";

function toDateInputValue(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso.slice(0, 10) : localDateStr(d);
}

export function NewsTrendsUI({ articles, chartHeight = 400 }: { articles: ArticleImpact[]; chartHeight?: number }) {
  const [viewMode, setViewMode] = useState<ViewMode>("daily");
  const [maWindow, setMaWindow] = useState(7);
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
  const [quickRange, setQuickRange] = useState<QuickRange>("all");
  const [benchmark, setBenchmark] = useState<BenchmarkId>("none");
  const [benchmarkData, setBenchmarkData] = useState<OhlcPoint[]>([]);

  function applyQuickRange(range: QuickRange) {
    setQuickRange(range);
    if (range === "all") {
      setDateFrom("");
      setDateTo("");
    } else {
      const days = range === "7d" ? 7 : range === "30d" ? 30 : 90;
      const [ey, em, ed] = (maxDate || localDateStr(new Date())).split("-").map(Number);
      const end = new Date(ey, em - 1, ed); // local midnight
      const start = new Date(end);
      start.setDate(start.getDate() - days);
      setDateFrom(localDateStr(start));
      setDateTo(localDateStr(end));
    }
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
    setMaWindow(DEFAULT_MA[mode]);
  }

  const daily = useMemo(() => {
    const raw = buildPeriodData(filteredArticles, viewMode);
    const start = dateFrom || minDate;
    const end = dateTo || maxDate;
    return fillDateGaps(raw, viewMode, start, end);
  }, [filteredArticles, viewMode, dateFrom, dateTo, minDate, maxDate]);
  const chartData = useMemo(
    () => applyClusterMA(daily, maWindow),
    [daily, maWindow],
  );

  useEffect(() => {
    const symbol = BENCHMARK_OPTIONS.find((b) => b.id === benchmark)?.symbol;
    if (!symbol) {
      setBenchmarkData([]);
      return;
    }

    let cancelled = false;
    const interval = viewMode === "hourly" ? "1hour" : "1day";
    fetch(`/api/fmp/ohlc?symbol=${encodeURIComponent(symbol)}&interval=${interval}`)
      .then(async (res) => {
        if (!res.ok) throw new Error("Failed benchmark fetch");
        const raw = (await res.json()) as Array<{ date?: string; close?: number }>;
        return raw
          .map((r) => ({
            date: String(r.date ?? ""),
            close: Number(r.close),
          }))
          .filter((r) => r.date && Number.isFinite(r.close));
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
      return new Map<string, number>();
    }

    const startBucket = daily[0]?.date;
    const endBucket = daily[daily.length - 1]?.date;
    if (!startBucket || !endBucket) return new Map<string, number>();

    const bucketValues = new Map<string, number>();
    for (const p of benchmarkData) {
      const bucket = normalizeToBucket(p.date, viewMode);
      if (!bucket) continue;
      if (bucket < startBucket || bucket > endBucket) continue;
      bucketValues.set(bucket, p.close);
    }

    const sortedBuckets = Array.from(bucketValues.keys()).sort((a, b) => a.localeCompare(b));
    if (sortedBuckets.length === 0) return new Map<string, number>();

    const base = bucketValues.get(sortedBuckets[0]) ?? Number.NaN;
    if (!Number.isFinite(base) || Math.abs(base) < 1e-9) return new Map<string, number>();

    return new Map(
      sortedBuckets.map((bucket) => {
        const close = bucketValues.get(bucket)!;
        return [bucket, (close - base) / base] as const;
      }),
    );
  }, [benchmark, benchmarkData, daily, viewMode]);

  const chartDataWithBenchmark = useMemo(() => {
    if (benchmark === "none" || benchmarkByBucket.size === 0) return chartData;
    return chartData.map((point) => {
      const benchmarkValue = benchmarkByBucket.get(String(point.date)) ?? null;
      return {
        ...point,
        __benchmark: benchmarkValue,
      };
    });
  }, [benchmark, benchmarkByBucket, chartData]);

  // Drill-down: dimension MA data for the selected cluster
  const drilldownDims = useMemo(() => {
    if (!drilldownId) return null;
    const cluster = CLUSTERS.find((c) => c.id === drilldownId);
    if (!cluster) return null;
    return cluster.dimensions;
  }, [drilldownId]);

  const dimensionChartData = useMemo(() => {
    if (!drilldownDims) return [];
    return applyDimensionMA(
      daily,
      maWindow,
      drilldownDims.map((d) => d.key),
    );
  }, [daily, maWindow, drilldownDims]);

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
        <p className="text-xs mt-1">
          Run{" "}
          <code className="font-mono bg-muted px-1 rounded">
            python -m news_impact.score_news_cli
          </code>{" "}
          to score articles.
        </p>
      </div>
    );
  }

  const dateRange =
    chartData.length > 0
      ? `${chartData[0].date} → ${chartData[chartData.length - 1].date}`
      : "";

  const totalArticles = daily.reduce((sum, d) => sum + d.count, 0);

  const clusterLabelMap = Object.fromEntries(
    CLUSTERS.map((c) => [c.id, c.label]),
  );

  return (
    <div className="flex flex-col gap-6">
      {/* Controls */}
      <div className="flex flex-wrap items-center gap-3">
        {/* View mode toggle */}
        <div className="flex rounded-md border border-border overflow-hidden text-xs">
          {(["daily", "hourly"] as ViewMode[]).map((mode) => (
            <button
              key={mode}
              onClick={() => switchMode(mode)}
              className={`px-3 py-1 capitalize transition-colors ${
                viewMode === mode
                  ? "bg-foreground text-background"
                  : "bg-background text-muted-foreground hover:text-foreground"
              }`}
            >
              {mode}
            </button>
          ))}
        </div>

        <span className="text-xs text-muted-foreground">MA:</span>
        {MA_OPTIONS[viewMode].map((opt) => (
          <button
            key={opt.value}
            onClick={() => setMaWindow(opt.value)}
            className={`text-xs px-2.5 py-1 rounded-md border transition-colors ${
              maWindow === opt.value
                ? "bg-foreground text-background border-foreground"
                : "bg-background text-muted-foreground border-border hover:border-foreground/40"
            }`}
          >
            {opt.label}
          </button>
        ))}
        <span className="text-xs text-muted-foreground ml-2">Overlay:</span>
        <select
          value={benchmark}
          onChange={(e) => setBenchmark(e.target.value as BenchmarkId)}
          className="text-xs border rounded-md px-2 py-1 bg-background focus:outline-none focus:ring-2 focus:ring-ring"
        >
          {BENCHMARK_OPTIONS.map((b) => (
            <option key={b.id} value={b.id}>
              {b.label}
            </option>
          ))}
        </select>
        <span className="ml-auto text-xs text-muted-foreground">
          {totalArticles} articles · {dateRange}
        </span>
      </div>

      {/* Date range filter */}
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-xs text-muted-foreground">Range:</span>
        {(["7d", "30d", "90d", "all"] as QuickRange[]).map((r) => (
          <button
            key={r}
            onClick={() => applyQuickRange(r)}
            className={`text-xs px-2.5 py-1 rounded-md border transition-colors ${
              quickRange === r
                ? "bg-foreground text-background border-foreground"
                : "bg-background text-muted-foreground border-border hover:border-foreground/40"
            }`}
          >
            {r === "all" ? "All" : r}
          </button>
        ))}
        <div className="flex items-center gap-1.5 ml-2">
          <input
            type="date"
            value={dateFrom}
            min={minDate}
            max={dateTo || maxDate}
            onChange={(e) => {
              setDateFrom(e.target.value);
              setQuickRange("all");
            }}
            className="text-xs px-2 py-1 rounded-md border border-border bg-background text-foreground"
          />
          <span className="text-xs text-muted-foreground">→</span>
          <input
            type="date"
            value={dateTo}
            min={dateFrom || minDate}
            max={maxDate}
            onChange={(e) => {
              setDateTo(e.target.value);
              setQuickRange("all");
            }}
            className="text-xs px-2 py-1 rounded-md border border-border bg-background text-foreground"
          />
        </div>
      </div>

      <div className="flex gap-6">
        {/* Main cluster chart */}
        <div className="flex-1 min-w-0">
          <div className="border rounded-xl p-4">
            <p className="text-xs text-muted-foreground mb-4">
              Impact score −1 (bearish) → +1 (bullish) · Click score to
              show/hide · <ChevronRight size={10} className="inline" /> to drill
              into dimensions
            </p>
            <ResponsiveContainer width="100%" height={chartHeight}>
              <LineChart
                data={chartDataWithBenchmark}
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
                <ReferenceLine
                  y={0}
                  stroke="currentColor"
                  strokeOpacity={0.3}
                  strokeWidth={1}
                />
                <Tooltip
                  content={<CustomTooltip labelMap={clusterLabelMap} />}
                />
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
                  <Line
                    yAxisId="benchmark"
                    type="monotone"
                    dataKey="__benchmark"
                    name={
                      BENCHMARK_OPTIONS.find((b) => b.id === benchmark)?.label ?? "Benchmark"
                    }
                    stroke="#9ca3af"
                    dot={false}
                    strokeWidth={2}
                    strokeDasharray="6 4"
                    connectNulls
                  />
                )}
              </LineChart>
            </ResponsiveContainer>
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
              onDrilldown={toggleDrilldown}
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

      {/* Guide */}
      <div className="flex items-center gap-4 text-[11px] text-muted-foreground flex-wrap">
        <span className="font-medium text-foreground/70">
          Reading this chart:
        </span>
        <span className="flex items-center gap-1">
          <TrendingUp size={10} className="text-emerald-500" /> positive = news
          favors companies with high scores on this dimension
        </span>
        <span className="flex items-center gap-1">
          <TrendingDown size={10} className="text-rose-500" /> negative = news
          is a headwind for this dimension
        </span>
      </div>
    </div>
  );
}
