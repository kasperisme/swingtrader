/**
 * Local-timezone bucketing + per-article rollups used when DB aggregate views
 * are not provided (e.g. embedded NewsTrendsUI with a synthetic article subset).
 */
import { CLUSTERS } from "../vectors/dimensions";
import type { TrendsPeriodRow } from "./news-trends-series";

type ArticleForAgg = {
  published_at: string;
  impact_json: Record<string, number>;
  confidence?: number | null;
};

export type ViewMode = "daily" | "hourly";

const pad2 = (n: number) => String(n).padStart(2, "0");

function localDateStr(d: Date): string {
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
}

export function dateToLocalChartBucket(d: Date, mode: ViewMode): string {
  const base = localDateStr(d);
  return mode === "hourly" ? `${base}T${pad2(d.getHours())}` : base;
}

function toBucket(iso: string, mode: ViewMode): string {
  const d = new Date(iso);
  if (!Number.isNaN(d.getTime())) return dateToLocalChartBucket(d, mode);
  return mode === "hourly" ? iso.slice(0, 13) : iso.slice(0, 10);
}

function impactConfidenceWeight(confidence: number | null | undefined): number {
  if (confidence == null || !Number.isFinite(confidence)) return 1;
  return Math.max(0, confidence);
}

function weightedMeanPairs(
  pairs: { value: number; weight: number }[],
): number | null {
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

/** Legacy client rollup (local wall-clock buckets). */
export function buildPeriodDataFromArticlesLocal(
  articles: ArticleForAgg[],
  mode: ViewMode,
): TrendsPeriodRow[] {
  const byDate = new Map<string, ArticleForAgg[]>();
  for (const a of articles) {
    const d = toBucket(a.published_at, mode);
    if (!byDate.has(d)) byDate.set(d, []);
    byDate.get(d)!.push(a);
  }

  const sorted = Array.from(byDate.entries()).sort((a, b) => a[0].localeCompare(b[0]));
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
        pairs.push({
          value: v,
          weight: impactConfidenceWeight(row.confidence),
        });
      }
      dimensions[key] = weightedMeanPairs(pairs);
    }

    return {
      date,
      dateLabel: date,
      clusters,
      dimensions,
      count: rows.length,
    };
  });
}

function emptyPeriodRowLocal(date: string, mode: ViewMode): TrendsPeriodRow {
  const clusters: Record<string, number | null> = {};
  for (const c of CLUSTERS) clusters[c.id] = null;
  const dimensions: Record<string, number | null> = {};
  const allDimKeys = CLUSTERS.flatMap((c) => c.dimensions.map((d) => d.key));
  for (const k of allDimKeys) dimensions[k] = null;
  return { date, dateLabel: date, clusters, dimensions, count: 0 };
}

/** Fill missing local calendar buckets between start and end (inclusive). */
export function fillDateGapsLocal(
  data: TrendsPeriodRow[],
  mode: ViewMode,
  startBucket: string,
  endBucket: string,
): TrendsPeriodRow[] {
  if (!startBucket || !endBucket) return data;

  const allDimKeys = CLUSTERS.flatMap((c) => c.dimensions.map((d) => d.key));
  const dataMap = new Map(data.map((d) => [d.date, d]));
  const result: TrendsPeriodRow[] = [];

  const emptyEntry = (date: string) => emptyPeriodRowLocal(date, mode);

  const toHourlyBucket = (bucket: string, endOfDay: boolean): string | null => {
    if (/^\d{4}-\d{2}-\d{2}T\d{2}$/.test(bucket)) return bucket;
    if (/^\d{4}-\d{2}-\d{2}$/.test(bucket))
      return `${bucket}T${endOfDay ? "23" : "00"}`;
    return null;
  };

  if (mode === "daily") {
    let current = startBucket.slice(0, 10);
    const end = endBucket.slice(0, 10);
    while (current <= end) {
      result.push(dataMap.get(current) ?? emptyEntry(current));
      const [y, m, day] = current.split("-").map(Number);
      const d = new Date(y, m - 1, day);
      d.setDate(d.getDate() + 1);
      if (Number.isNaN(d.getTime())) break;
      current = localDateStr(d);
    }
  } else {
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
      const d = new Date(y, m - 1, day, hour);
      d.setHours(d.getHours() + 1);
      if (Number.isNaN(d.getTime())) break;
      current = dateToLocalChartBucket(d, "hourly");
    }
  }

  return result;
}

export function articleLocalBucket(iso: string, mode: ViewMode): string {
  return toBucket(iso, mode);
}

/** Align FMP benchmark dates with local-chart bucket strings. */
export function benchmarkDateToLocalChartBucket(
  dateLike: string,
  mode: ViewMode,
): string | null {
  if (!dateLike) return null;
  const parsed = new Date(dateLike.replace(" ", "T"));
  if (Number.isNaN(parsed.getTime())) return null;
  return dateToLocalChartBucket(parsed, mode);
}
