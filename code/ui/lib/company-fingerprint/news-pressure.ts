import {
  HEATMAP_CLUSTERS,
  type HeatmapCluster,
  type HeatmapInputRow,
} from "@/lib/news-impact-heatmap/aggregate";
import { DIM_TO_CLUSTERS, type DimMapping } from "./dimensions";

export type NewsPressure = "up" | "down" | "neutral";

/** Anything below this absolute score is treated as no signal. */
export const PRESSURE_THRESHOLD = 0.15;

export function bucketPressure(signedScore: number | null): NewsPressure | null {
  if (signedScore == null || !Number.isFinite(signedScore)) return null;
  if (Math.abs(signedScore) < PRESSURE_THRESHOLD) return "neutral";
  return signedScore > 0 ? "up" : "down";
}

function isHeatmapCluster(s: string): s is HeatmapCluster {
  return (HEATMAP_CLUSTERS as readonly string[]).includes(s);
}

function clampConfidence(raw: number | null): number {
  if (raw == null || !Number.isFinite(raw)) return 1;
  return Math.max(0, Math.min(1, raw));
}

/** Returns the set of article_ids whose TICKER_SENTIMENT row mentions the
 *  given ticker with a finite (non-zero) score. */
export function articleIdsMentioningTicker(
  rows: HeatmapInputRow[],
  ticker: string,
): Set<number> {
  const t = ticker.trim().toUpperCase();
  const ids = new Set<number>();
  if (!t) return ids;
  for (const r of rows) {
    if (r.cluster !== "TICKER_SENTIMENT") continue;
    const s = r.scores_json;
    if (!s || typeof s !== "object") continue;
    const v = s[t];
    if (typeof v === "number" && Number.isFinite(v) && v !== 0) {
      ids.add(r.article_id);
    }
  }
  return ids;
}

/** Confidence-weighted mean of one cluster's signal across the rows whose
 *  article_id is in `articleIds`. `subKey`: if provided, pulls only that key
 *  out of each row's scores_json. Otherwise the row's mean is used. Returns
 *  null when no rows contribute. */
function clusterSignal(
  rows: HeatmapInputRow[],
  cluster: HeatmapCluster,
  articleIds: Set<number>,
  subKey: string | null,
): number | null {
  let weighted = 0;
  let totalConf = 0;
  for (const r of rows) {
    if (r.cluster !== cluster) continue;
    if (!articleIds.has(r.article_id)) continue;
    const s = r.scores_json;
    if (!s) continue;

    let value: number;
    if (subKey != null) {
      const sv = s[subKey];
      if (typeof sv !== "number" || !Number.isFinite(sv)) continue;
      value = sv;
    } else {
      let sum = 0;
      let n = 0;
      for (const v of Object.values(s)) {
        if (typeof v === "number" && Number.isFinite(v)) {
          sum += v;
          n += 1;
        }
      }
      if (n === 0) continue;
      value = sum / n;
    }

    const conf = clampConfidence(r.confidence);
    if (conf <= 0) continue;
    weighted += value * conf;
    totalConf += conf;
  }
  return totalConf > 0 ? weighted / totalConf : null;
}

/** Returns the signed score for a single dimension after collapsing all its
 *  mapped clusters/sub-keys into a single number. Null when no mapped cluster
 *  carries any signal for this ticker over the window. */
export function dimSignedScore(
  rows: HeatmapInputRow[],
  ticker: string,
  dim: string,
  cachedArticleIds?: Set<number>,
): number | null {
  const mappings = DIM_TO_CLUSTERS[dim];
  if (!mappings || mappings.length === 0) return null;
  const articleIds = cachedArticleIds ?? articleIdsMentioningTicker(rows, ticker);
  if (articleIds.size === 0) return null;

  const parts: number[] = [];
  for (const m of mappings) {
    const [cluster, subKey] = normalizeMapping(m);
    if (!isHeatmapCluster(cluster)) continue;
    const sig = clusterSignal(rows, cluster, articleIds, subKey);
    if (sig != null) parts.push(sig);
  }
  if (parts.length === 0) return null;
  return parts.reduce((a, b) => a + b, 0) / parts.length;
}

function normalizeMapping(m: DimMapping): [HeatmapCluster, string | null] {
  if (Array.isArray(m)) return [m[0], m[1]];
  return [m, null];
}

/** Convenience: pre-compute pressure for every mapped dim. Returned map only
 *  contains entries with a non-null signal — neutral is included, but a dim
 *  with no underlying news at all is omitted. */
export function buildDimPressureMap(
  rows: HeatmapInputRow[],
  ticker: string,
): Map<string, NewsPressure> {
  const out = new Map<string, NewsPressure>();
  const articleIds = articleIdsMentioningTicker(rows, ticker);
  if (articleIds.size === 0) return out;
  for (const dim of Object.keys(DIM_TO_CLUSTERS)) {
    const score = dimSignedScore(rows, ticker, dim, articleIds);
    const bucket = bucketPressure(score);
    if (bucket != null) out.set(dim, bucket);
  }
  return out;
}
