import { CLUSTERS } from "../vectors/dimensions";

export type ViewMode = "daily" | "hourly";

/** Row from `news_trends_cluster_*_v` (subset of columns). */
export type ClusterTrendRow = {
  bucket_day?: string | null;
  bucket_hour?: string | null;
  cluster_id: string;
  cluster_weighted_avg: number | null;
  cluster_avg?: number | null;
  article_count: number;
  bucket_article_count: number;
};

/** Row from `news_trends_dimension_*_v` (subset of columns). */
export type DimensionTrendRow = {
  bucket_day?: string | null;
  bucket_hour?: string | null;
  dimension_key: string;
  dimension_weighted_avg: number | null;
  dimension_avg?: number | null;
  article_count: number;
  bucket_article_count: number;
};

/** One chart period: UTC bucket key + values aligned with SQL aggregates. */
export type TrendsPeriodRow = {
  /** UTC bucket id: `YYYY-MM-DD` (daily) or `YYYY-MM-DDTHH` (hourly, UTC hour). Lex-sortable. */
  date: string;
  /** Human-readable tick/tooltip label in the viewer's local timezone. */
  dateLabel: string;
  clusters: Record<string, number | null>;
  dimensions: Record<string, number | null>;
  /** `bucket_article_count` from the view (articles in bucket in DB sense). */
  count: number;
};

const pad2 = (n: number) => String(n).padStart(2, "0");

export function utcSortKeyFromDbBucket(iso: string | null | undefined, mode: ViewMode): string | null {
  if (iso == null || iso === "") return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  if (mode === "daily") return d.toISOString().slice(0, 10);
  return d.toISOString().slice(0, 13);
}

export function utcKeyToDate(utcKey: string, mode: ViewMode): Date {
  if (mode === "hourly") {
    const base = utcKey.length >= 13 ? utcKey.slice(0, 13) : utcKey;
    return new Date(`${base}:00:00.000Z`);
  }
  return new Date(`${utcKey.slice(0, 10)}T00:00:00.000Z`);
}

export function utcBucketFromPublishedAt(iso: string, mode: ViewMode): string | null {
  const d = new Date(iso.replace(" ", "T"));
  if (Number.isNaN(d.getTime())) return null;
  if (mode === "daily") return d.toISOString().slice(0, 10);
  return d.toISOString().slice(0, 13);
}

export function formatUtcBucketForDisplay(utcKey: string, mode: ViewMode): string {
  const d = utcKeyToDate(utcKey, mode);
  if (mode === "hourly") {
    const parts = new Intl.DateTimeFormat(undefined, {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      hour12: false,
    }).formatToParts(d);
    const mo = parts.find((p) => p.type === "month")?.value ?? "";
    const da = parts.find((p) => p.type === "day")?.value ?? "";
    const hr = parts.find((p) => p.type === "hour")?.value ?? "";
    return `${mo}-${da} ${hr}h`;
  }
  return d.toLocaleDateString(undefined, { month: "2-digit", day: "2-digit" });
}

function localDateStr(d: Date): string {
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
}

/** Compare bucket start instant to local calendar `YYYY-MM-DD` filter (inclusive). */
export function trendsRowMatchesLocalDateRange(
  row: TrendsPeriodRow,
  mode: ViewMode,
  dateFrom: string,
  dateTo: string,
): boolean {
  const start = utcKeyToDate(row.date, mode);
  const localDay = localDateStr(start);
  if (dateFrom && localDay < dateFrom) return false;
  if (dateTo && localDay > dateTo) return false;
  return true;
}

function emptyPeriodRow(date: string, mode: ViewMode): TrendsPeriodRow {
  const clusters: Record<string, number | null> = {};
  for (const c of CLUSTERS) clusters[c.id] = null;
  const dimensions: Record<string, number | null> = {};
  const allDimKeys = CLUSTERS.flatMap((c) => c.dimensions.map((d) => d.key));
  for (const k of allDimKeys) dimensions[k] = null;
  return {
    date,
    dateLabel: formatUtcBucketForDisplay(date, mode),
    clusters,
    dimensions,
    count: 0,
  };
}

export function pivotTrendAggregates(
  clusterRows: ClusterTrendRow[],
  dimensionRows: DimensionTrendRow[],
  mode: ViewMode,
): TrendsPeriodRow[] {
  const allDimKeys = CLUSTERS.flatMap((c) => c.dimensions.map((d) => d.key));
  const bucketKeys = new Set<string>();
  const clusterMap = new Map<string, Map<string, ClusterTrendRow>>();
  const dimensionMap = new Map<string, Map<string, DimensionTrendRow>>();

  for (const r of clusterRows) {
    const raw = mode === "daily" ? r.bucket_day : r.bucket_hour;
    const k = utcSortKeyFromDbBucket(raw, mode);
    if (!k) continue;
    bucketKeys.add(k);
    if (!clusterMap.has(k)) clusterMap.set(k, new Map());
    clusterMap.get(k)!.set(r.cluster_id, r);
  }
  for (const r of dimensionRows) {
    const raw = mode === "daily" ? r.bucket_day : r.bucket_hour;
    const k = utcSortKeyFromDbBucket(raw, mode);
    if (!k) continue;
    bucketKeys.add(k);
    if (!dimensionMap.has(k)) dimensionMap.set(k, new Map());
    dimensionMap.get(k)!.set(r.dimension_key, r);
  }

  const sorted = Array.from(bucketKeys).sort((a, b) => a.localeCompare(b));

  return sorted.map((date) => {
    const clusters: Record<string, number | null> = {};
    const cm = clusterMap.get(date);
    if (cm) {
      for (const c of CLUSTERS) {
        const row = cm.get(c.id);
        clusters[c.id] =
          row != null && row.cluster_weighted_avg != null && Number.isFinite(Number(row.cluster_weighted_avg))
            ? Number(row.cluster_weighted_avg)
            : null;
      }
    } else {
      for (const c of CLUSTERS) clusters[c.id] = null;
    }

    const dimensions: Record<string, number | null> = {};
    const dm = dimensionMap.get(date);
    for (const key of allDimKeys) {
      const row = dm?.get(key);
      dimensions[key] =
        row != null &&
        row.dimension_weighted_avg != null &&
        Number.isFinite(Number(row.dimension_weighted_avg))
          ? Number(row.dimension_weighted_avg)
          : null;
    }

    let count = 0;
    if (cm && cm.size > 0) {
      const any = [...cm.values()][0];
      if (any) count = Number(any.bucket_article_count) || 0;
    }
    if (count === 0 && dm && dm.size > 0) {
      const anyD = [...dm.values()][0];
      if (anyD) count = Number(anyD.bucket_article_count) || 0;
    }

    return {
      date,
      dateLabel: formatUtcBucketForDisplay(date, mode),
      clusters,
      dimensions,
      count,
    };
  });
}

function addUtcStep(d: Date, mode: ViewMode): Date {
  const x = new Date(d.getTime());
  if (mode === "daily") x.setUTCDate(x.getUTCDate() + 1);
  else x.setUTCHours(x.getUTCHours() + 1);
  return x;
}

function dateToUtcKey(d: Date, mode: ViewMode): string {
  if (mode === "daily") return d.toISOString().slice(0, 10);
  return d.toISOString().slice(0, 13);
}

/** Fill missing UTC buckets between `startKey` and `endKey` (inclusive). */
export function fillUtcBucketGaps(
  data: TrendsPeriodRow[],
  mode: ViewMode,
  startKey: string,
  endKey: string,
): TrendsPeriodRow[] {
  if (!startKey || !endKey) return data;
  const lo = startKey <= endKey ? startKey : endKey;
  const hi = startKey <= endKey ? endKey : startKey;
  const dataMap = new Map(data.map((d) => [d.date, d]));
  const result: TrendsPeriodRow[] = [];

  let cur = utcKeyToDate(lo, mode);
  const end = utcKeyToDate(hi, mode);
  if (Number.isNaN(cur.getTime()) || Number.isNaN(end.getTime())) return data;

  while (cur.getTime() <= end.getTime()) {
    const key = dateToUtcKey(cur, mode);
    result.push(dataMap.get(key) ?? emptyPeriodRow(key, mode));
    cur = addUtcStep(cur, mode);
  }
  return result;
}

/** Map FMP / benchmark `date` string onto the same UTC bucket key used by trend rows. */
export function benchmarkDateToUtcKey(dateLike: string, mode: ViewMode): string | null {
  const raw = dateLike.trim();
  if (!raw) return null;
  const d = new Date(raw.includes("T") ? raw : `${raw.slice(0, 10)}T00:00:00.000Z`);
  if (Number.isNaN(d.getTime())) return null;
  if (mode === "daily") return d.toISOString().slice(0, 10);
  return d.toISOString().slice(0, 13);
}
