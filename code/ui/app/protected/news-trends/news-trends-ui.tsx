"use client";

import { useMemo, useState } from "react";
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
import { TrendingUp, TrendingDown, Minus } from "lucide-react";
import { CLUSTERS } from "../vectors/dimensions";

export interface ArticleImpact {
  created_at: string;
  impact: Record<string, number>;
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

// ── helpers ──────────────────────────────────────────────────────────────────

function toDateStr(iso: string): string {
  return iso.slice(0, 10);
}

/** Compute daily average impact per cluster key */
function buildDailyClusterData(articles: ArticleImpact[]): Array<{
  date: string;
  clusters: Record<string, number | null>;
  count: number;
}> {
  // Group articles by date
  const byDate = new Map<string, ArticleImpact[]>();
  for (const a of articles) {
    const d = toDateStr(a.created_at);
    if (!byDate.has(d)) byDate.set(d, []);
    byDate.get(d)!.push(a);
  }

  const sorted = Array.from(byDate.entries()).sort((a, b) => a[0].localeCompare(b[0]));

  return sorted.map(([date, rows]) => {
    const clusterSums: Record<string, number[]> = {};

    for (const cluster of CLUSTERS) {
      clusterSums[cluster.id] = [];
    }

    for (const row of rows) {
      for (const cluster of CLUSTERS) {
        const dimKeys = cluster.dimensions.map((d) => d.key);
        const scores = dimKeys
          .map((k) => row.impact[k])
          .filter((v) => v != null && !isNaN(v)) as number[];
        if (scores.length > 0) {
          const avg = scores.reduce((a, b) => a + b, 0) / scores.length;
          clusterSums[cluster.id].push(avg);
        }
      }
    }

    const clusters: Record<string, number | null> = {};
    for (const cluster of CLUSTERS) {
      const arr = clusterSums[cluster.id];
      clusters[cluster.id] = arr.length > 0 ? arr.reduce((a, b) => a + b, 0) / arr.length : null;
    }

    return { date, clusters, count: rows.length };
  });
}

/** Apply rolling window moving average */
function applyMA(
  daily: ReturnType<typeof buildDailyClusterData>,
  window: number
): Array<{ date: string; [key: string]: number | string | null }> {
  return daily.map((point, i) => {
    const start = Math.max(0, i - window + 1);
    const slice = daily.slice(start, i + 1);

    const result: { date: string; [key: string]: number | string | null } = { date: point.date };

    for (const cluster of CLUSTERS) {
      const vals = slice
        .map((d) => d.clusters[cluster.id])
        .filter((v): v is number => v != null);
      result[cluster.id] = vals.length > 0 ? vals.reduce((a, b) => a + b, 0) / vals.length : null;
    }

    return result;
  });
}

// ── sub-components ───────────────────────────────────────────────────────────

function Leaderboard({
  latest,
  selected,
  onToggle,
}: {
  latest: Record<string, number | null>;
  selected: Set<string>;
  onToggle: (id: string) => void;
}) {
  const sorted = CLUSTERS
    .map((c) => ({ cluster: c, score: latest[c.id] ?? null }))
    .sort((a, b) => {
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
        const isPos = score != null && score > 0.05;
        const isNeg = score != null && score < -0.05;

        return (
          <button
            key={cluster.id}
            onClick={() => onToggle(cluster.id)}
            className={`flex items-center gap-2 px-2 py-1.5 rounded-lg text-left transition-colors ${
              isSelected ? "bg-muted" : "hover:bg-muted/50 opacity-60"
            }`}
          >
            <span
              className="w-2.5 h-2.5 rounded-full shrink-0"
              style={{ backgroundColor: color }}
            />
            <span className="flex-1 text-xs font-medium truncate">{cluster.label}</span>
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
                  isPos ? "text-emerald-500" : isNeg ? "text-rose-500" : "text-muted-foreground"
                }
              >
                {score != null ? (score >= 0 ? "+" : "") + score.toFixed(2) : "—"}
              </span>
            </span>
          </button>
        );
      })}
    </div>
  );
}

function CustomTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: Array<{ name: string; value: number | null; color: string }>;
  label?: string;
}) {
  if (!active || !payload?.length) return null;

  const sorted = [...payload]
    .filter((p) => p.value != null)
    .sort((a, b) => (b.value ?? 0) - (a.value ?? 0));

  return (
    <div className="bg-background border rounded-lg shadow-lg p-3 text-xs max-w-[200px]">
      <p className="font-semibold mb-2 text-muted-foreground">{label}</p>
      {sorted.map((p) => {
        const clusterLabel = CLUSTERS.find((c) => c.id === p.name)?.label ?? p.name;
        const isPos = (p.value ?? 0) > 0.05;
        const isNeg = (p.value ?? 0) < -0.05;
        return (
          <div key={p.name} className="flex items-center gap-1.5 py-0.5">
            <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: p.color }} />
            <span className="flex-1 truncate text-foreground/80">{clusterLabel}</span>
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

// ── main component ───────────────────────────────────────────────────────────

const MA_OPTIONS = [
  { label: "3d MA", value: 3 },
  { label: "7d MA", value: 7 },
  { label: "14d MA", value: 14 },
  { label: "30d MA", value: 30 },
];

export function NewsTrendsUI({ articles }: { articles: ArticleImpact[] }) {
  const [maWindow, setMaWindow] = useState(7);
  const [selected, setSelected] = useState<Set<string>>(
    new Set(CLUSTERS.map((c) => c.id))
  );

  const daily = useMemo(() => buildDailyClusterData(articles), [articles]);
  const chartData = useMemo(() => applyMA(daily, maWindow), [daily, maWindow]);

  const latestScores = useMemo(() => {
    if (chartData.length === 0) return {} as Record<string, number | null>;
    const last = chartData[chartData.length - 1];
    return Object.fromEntries(
      CLUSTERS.map((c) => [c.id, last[c.id] as number | null])
    );
  }, [chartData]);

  function toggleCluster(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        if (next.size === 1) return prev; // keep at least one
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
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

  // Format x-axis dates
  const dateRange =
    chartData.length > 0
      ? `${chartData[0].date} → ${chartData[chartData.length - 1].date}`
      : "";

  const totalArticles = daily.reduce((sum, d) => sum + d.count, 0);

  return (
    <div className="flex flex-col gap-6">
      {/* Controls */}
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-xs text-muted-foreground">Moving average:</span>
        {MA_OPTIONS.map((opt) => (
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
        <span className="ml-auto text-xs text-muted-foreground">
          {totalArticles} articles · {dateRange}
        </span>
      </div>

      <div className="flex gap-6">
        {/* Chart */}
        <div className="flex-1 min-w-0">
          <div className="border rounded-xl p-4">
            <p className="text-xs text-muted-foreground mb-4">
              Impact score −1 (bearish) → +1 (bullish) · Click legend items to show/hide
            </p>
            <ResponsiveContainer width="100%" height={400}>
              <LineChart data={chartData} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="currentColor" strokeOpacity={0.1} />
                <XAxis
                  dataKey="date"
                  tick={{ fontSize: 10, fill: "currentColor", opacity: 0.5 }}
                  tickLine={false}
                  tickFormatter={(v: string) => v.slice(5)} // MM-DD
                  interval="preserveStartEnd"
                />
                <YAxis
                  domain={[-1, 1]}
                  tick={{ fontSize: 10, fill: "currentColor", opacity: 0.5 }}
                  tickLine={false}
                  axisLine={false}
                  tickFormatter={(v: number) => (v >= 0 ? "+" : "") + v.toFixed(1)}
                  width={38}
                />
                <ReferenceLine y={0} stroke="currentColor" strokeOpacity={0.3} strokeWidth={1} />
                <Tooltip content={<CustomTooltip />} />
                {CLUSTERS.filter((c) => selected.has(c.id)).map((cluster) => (
                  <Line
                    key={cluster.id}
                    type="monotone"
                    dataKey={cluster.id}
                    name={cluster.id}
                    stroke={CLUSTER_COLORS[cluster.id]}
                    dot={false}
                    strokeWidth={1.5}
                    connectNulls
                  />
                ))}
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
              onToggle={toggleCluster}
            />
          </div>
        </div>
      </div>

      {/* Guide */}
      <div className="flex items-center gap-4 text-[11px] text-muted-foreground flex-wrap">
        <span className="font-medium text-foreground/70">Reading this chart:</span>
        <span className="flex items-center gap-1">
          <TrendingUp size={10} className="text-emerald-500" /> positive = news favors companies
          with high scores on this dimension
        </span>
        <span className="flex items-center gap-1">
          <TrendingDown size={10} className="text-rose-500" /> negative = news is a headwind for
          this dimension
        </span>
      </div>
    </div>
  );
}
