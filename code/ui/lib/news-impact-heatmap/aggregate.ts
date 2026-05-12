export const HEATMAP_CLUSTERS = [
  "MACRO_SENSITIVITY",
  "MARKET_BEHAVIOUR",
  "SECTOR_ROTATION",
  "GEOGRAPHY_TRADE",
  "BUSINESS_MODEL",
  "FINANCIAL_STRUCTURE",
  "GROWTH_PROFILE",
  "VALUATION_POSITIONING",
  "SUPPLY_CHAIN_EXPOSURE",
  "TICKER_RELATIONSHIPS",
  "TICKER_SENTIMENT",
] as const;

export type HeatmapCluster = (typeof HEATMAP_CLUSTERS)[number];

export const HEATMAP_BANDS: ReadonlyArray<{
  label: string;
  clusters: ReadonlyArray<HeatmapCluster>;
}> = [
  {
    label: "Market & macro",
    clusters: [
      "MACRO_SENSITIVITY",
      "MARKET_BEHAVIOUR",
      "SECTOR_ROTATION",
      "GEOGRAPHY_TRADE",
    ],
  },
  {
    label: "Company fundamentals",
    clusters: [
      "BUSINESS_MODEL",
      "FINANCIAL_STRUCTURE",
      "GROWTH_PROFILE",
      "VALUATION_POSITIONING",
    ],
  },
  {
    label: "Operational & ticker",
    clusters: [
      "SUPPLY_CHAIN_EXPOSURE",
      "TICKER_RELATIONSHIPS",
      "TICKER_SENTIMENT",
    ],
  },
];

export const CLUSTER_LABELS: Record<HeatmapCluster, string> = {
  MACRO_SENSITIVITY: "Macro",
  MARKET_BEHAVIOUR: "Market behaviour",
  SECTOR_ROTATION: "Sector rotation",
  GEOGRAPHY_TRADE: "Geography & trade",
  BUSINESS_MODEL: "Business model",
  FINANCIAL_STRUCTURE: "Financials",
  GROWTH_PROFILE: "Growth",
  VALUATION_POSITIONING: "Valuation",
  SUPPLY_CHAIN_EXPOSURE: "Supply chain",
  TICKER_RELATIONSHIPS: "Ticker links",
  TICKER_SENTIMENT: "Ticker sentiment",
};

/** Backwards-compat default (single-day hourly heatmap). */
export const HEATMAP_BUCKET_COUNT = 24;

export type HeatmapGranularity = "1h" | "4h" | "1d";

export const GRANULARITY_MS: Record<HeatmapGranularity, number> = {
  "1h": 3_600_000,
  "4h": 4 * 3_600_000,
  "1d": 24 * 3_600_000,
};

export const HEATMAP_GRANULARITIES: HeatmapGranularity[] = ["1h", "4h", "1d"];

export const GRANULARITY_LABELS: Record<HeatmapGranularity, string> = {
  "1h": "1h",
  "4h": "4h",
  "1d": "1d",
};

export const HEATMAP_RANGES = ["24h", "7d", "30d", "90d"] as const;
export type HeatmapRange = (typeof HEATMAP_RANGES)[number];

const RANGE_HOURS: Record<HeatmapRange, number> = {
  "24h": 24,
  "7d": 7 * 24,
  "30d": 30 * 24,
  "90d": 90 * 24,
};

const RANGE_LABELS: Record<HeatmapRange, string> = {
  "24h": "24h",
  "7d": "7d",
  "30d": "30d",
  "90d": "90d",
};

const DEFAULT_GRANULARITY_FOR_RANGE: Record<HeatmapRange, HeatmapGranularity> = {
  "24h": "1h",
  "7d": "4h",
  "30d": "1d",
  "90d": "1d",
};

const MAX_BUCKETS = 200;

/** Best-fit granularity for a range — used when the user changes range. */
export function defaultGranularityForRange(range: HeatmapRange): HeatmapGranularity {
  return DEFAULT_GRANULARITY_FOR_RANGE[range];
}

/** Number of buckets a (range, granularity) combo produces. Capped at MAX_BUCKETS. */
export function bucketCountFor(
  range: HeatmapRange,
  granularity: HeatmapGranularity,
): number {
  const rangeHours = RANGE_HOURS[range];
  const granHours = GRANULARITY_MS[granularity] / 3_600_000;
  return Math.max(1, Math.min(MAX_BUCKETS, Math.round(rangeHours / granHours)));
}

/** Combos that would produce too few or too many buckets to be useful. */
export function isCombinationViable(
  range: HeatmapRange,
  granularity: HeatmapGranularity,
): boolean {
  const count = bucketCountFor(range, granularity);
  return count >= 4 && count <= MAX_BUCKETS;
}

export type RangeSpecBackcompat = {
  granularity: HeatmapGranularity;
  bucketCount: number;
  label: string;
};

/** Default (granularity, bucketCount) for a range — preserved for callers. */
export const RANGE_SPEC: Record<HeatmapRange, RangeSpecBackcompat> = {
  "24h": { granularity: "1h", bucketCount: 24, label: "24h" },
  "7d": { granularity: "4h", bucketCount: 42, label: "7d" },
  "30d": { granularity: "1d", bucketCount: 30, label: "30d" },
  "90d": { granularity: "1d", bucketCount: 90, label: "90d" },
};

export function rangeLabel(range: HeatmapRange): string {
  return RANGE_LABELS[range];
}

/**
 * ISO timestamp marking the earliest article we need to fetch.
 *
 * Overloads:
 *   rangeToSinceIso(range, now)                          — uses default granularity for the range
 *   rangeToSinceIso(range, granularity, now)             — explicit granularity
 */
export function rangeToSinceIso(range: HeatmapRange, now: Date): string;
export function rangeToSinceIso(
  range: HeatmapRange,
  granularity: HeatmapGranularity,
  now: Date,
): string;
export function rangeToSinceIso(
  range: HeatmapRange,
  arg2: HeatmapGranularity | Date,
  arg3?: Date,
): string {
  const granularity: HeatmapGranularity =
    arg2 instanceof Date ? defaultGranularityForRange(range) : arg2;
  const now: Date = arg2 instanceof Date ? arg2 : (arg3 as Date);
  const stepMs = GRANULARITY_MS[granularity];
  const count = bucketCountFor(range, granularity);
  // Pad by one bucket so floor-to-boundary never shaves articles.
  const since = new Date(now.getTime() - stepMs * (count + 1));
  return since.toISOString();
}

export type HeatmapInputRow = {
  article_id: number;
  cluster: string;
  scores_json: Record<string, number> | null;
  confidence: number | null;
  published_at: string;
};

export type TopTicker = { ticker: string; score: number };

export type HeatmapCell = {
  /** Confidence-weighted mean across articles whose scores_json is non-empty. Null when no such articles. */
  score: number | null;
  /** non-empty article count / total article count in this bucket, in [0, 1]. */
  coverage: number;
  /** Total unique articles published in this hour bucket, regardless of cluster. */
  totalArticles: number;
  /** Articles where this cluster fired (non-empty scores_json). */
  nonEmptyArticles: number;
  /** Top tickers contributing to this cell, sorted by |aggregated sentiment| desc. */
  topTickers: TopTicker[];
};

export type HeatmapResult = {
  /** ISO timestamps marking the start of each bucket (oldest → current). */
  bucketStarts: string[];
  /** Granularity used to bucket — drives column labels and tooltip formatting. */
  granularity: HeatmapGranularity;
  cells: Record<HeatmapCluster, HeatmapCell[]>;
  totalArticlesPerBucket: number[];
};

function floorToGranularity(d: Date, g: HeatmapGranularity): Date {
  const out = new Date(d);
  if (g === "1h") {
    out.setUTCMinutes(0, 0, 0);
  } else if (g === "4h") {
    out.setUTCMinutes(0, 0, 0);
    out.setUTCHours(Math.floor(out.getUTCHours() / 4) * 4);
  } else {
    out.setUTCHours(0, 0, 0, 0);
  }
  return out;
}

export function buildHeatmapBuckets(
  now: Date,
  granularity: HeatmapGranularity = "1h",
  count: number = HEATMAP_BUCKET_COUNT,
): Date[] {
  const stepMs = GRANULARITY_MS[granularity];
  const currentBucketStart = floorToGranularity(now, granularity);
  const buckets: Date[] = [];
  for (let i = count - 1; i >= 0; i--) {
    buckets.push(new Date(currentBucketStart.getTime() - i * stepMs));
  }
  return buckets;
}

function isHeatmapCluster(s: string): s is HeatmapCluster {
  return (HEATMAP_CLUSTERS as readonly string[]).includes(s);
}

function meanOfScores(scores: Record<string, number>): number | null {
  let sum = 0;
  let n = 0;
  for (const v of Object.values(scores)) {
    if (typeof v === "number" && Number.isFinite(v)) {
      sum += v;
      n += 1;
    }
  }
  return n === 0 ? null : sum / n;
}

function isNonEmptyScoreObject(s: Record<string, number> | null): boolean {
  if (!s) return false;
  for (const v of Object.values(s)) {
    if (typeof v === "number" && Number.isFinite(v)) return true;
  }
  return false;
}

/**
 * Per-dimension heatmap cells for a single cluster. Used when the user expands
 * a cluster row to inspect its sub-factor breakdown.
 *
 * Score per (dimension, bucket) = confidence-weighted mean over articles where
 * that dimension is present (finite number) in `scores_json`. Empty / missing
 * means "this dimension did not fire" and is excluded. Coverage uses the same
 * bucket-wide article total as the cluster aggregator so the two are comparable.
 *
 * Dimension keys are case-insensitive: the data action uppercases all keys, but
 * callers may pass the canonical lowercase form from `vectors/dimensions.ts`.
 */
export function aggregateClusterDimensions(
  rows: HeatmapInputRow[],
  cluster: HeatmapCluster,
  dimensionKeys: string[],
  now: Date,
  granularity: HeatmapGranularity = "1h",
  bucketCount: number = HEATMAP_BUCKET_COUNT,
): Record<string, HeatmapCell[]> {
  const stepMs = GRANULARITY_MS[granularity];
  const bucketStarts = buildHeatmapBuckets(now, granularity, bucketCount);
  const firstBucketStartMs = bucketStarts[0].getTime();
  const windowEndMs =
    bucketStarts[bucketStarts.length - 1].getTime() + stepMs;

  type Accum = {
    sumScoreWeighted: number;
    sumConfidence: number;
    nonEmptyArticleIds: Set<number>;
  };
  const accums: Record<string, Accum[]> = {};
  for (const key of dimensionKeys) {
    accums[key] = Array.from({ length: bucketCount }, () => ({
      sumScoreWeighted: 0,
      sumConfidence: 0,
      nonEmptyArticleIds: new Set<number>(),
    }));
  }

  const articlesPerBucket: Array<Set<number>> = Array.from(
    { length: bucketCount },
    () => new Set<number>(),
  );

  for (const row of rows) {
    const ts = Date.parse(row.published_at);
    if (!Number.isFinite(ts)) continue;
    if (ts < firstBucketStartMs || ts >= windowEndMs) continue;
    const bucketIdx = Math.floor((ts - firstBucketStartMs) / stepMs);
    if (bucketIdx < 0 || bucketIdx >= bucketCount) continue;

    articlesPerBucket[bucketIdx].add(row.article_id);

    if (row.cluster !== cluster) continue;
    if (!row.scores_json) continue;

    const confRaw = row.confidence;
    const conf =
      typeof confRaw === "number" && Number.isFinite(confRaw)
        ? Math.max(0, Math.min(1, confRaw))
        : 1;
    if (conf <= 0) continue;

    for (const key of dimensionKeys) {
      const v = row.scores_json[key] ?? row.scores_json[key.toUpperCase()];
      if (typeof v !== "number" || !Number.isFinite(v)) continue;
      const accum = accums[key][bucketIdx];
      accum.sumScoreWeighted += v * conf;
      accum.sumConfidence += conf;
      accum.nonEmptyArticleIds.add(row.article_id);
    }
  }

  const totalArticlesPerBucket = articlesPerBucket.map((s) => s.size);
  const out: Record<string, HeatmapCell[]> = {};
  for (const key of dimensionKeys) {
    out[key] = [];
    for (let i = 0; i < bucketCount; i++) {
      const accum = accums[key][i];
      const total = totalArticlesPerBucket[i];
      const nonEmpty = accum.nonEmptyArticleIds.size;
      out[key].push({
        score:
          accum.sumConfidence > 0
            ? accum.sumScoreWeighted / accum.sumConfidence
            : null,
        coverage: total > 0 ? nonEmpty / total : 0,
        totalArticles: total,
        nonEmptyArticles: nonEmpty,
        topTickers: [],
      });
    }
  }
  return out;
}

export function aggregateNewsImpactHeatmap(
  rows: HeatmapInputRow[],
  now: Date,
  granularity: HeatmapGranularity = "1h",
  bucketCount: number = HEATMAP_BUCKET_COUNT,
): HeatmapResult {
  const stepMs = GRANULARITY_MS[granularity];
  const bucketStarts = buildHeatmapBuckets(now, granularity, bucketCount);
  const firstBucketStartMs = bucketStarts[0].getTime();
  const windowEndMs =
    bucketStarts[bucketStarts.length - 1].getTime() + stepMs;

  type Accum = {
    sumScoreWeighted: number;
    sumConfidence: number;
    nonEmptyArticleIds: Set<number>;
  };
  const accums: Record<HeatmapCluster, Accum[]> = {} as Record<
    HeatmapCluster,
    Accum[]
  >;
  for (const c of HEATMAP_CLUSTERS) {
    accums[c] = Array.from({ length: bucketCount }, () => ({
      sumScoreWeighted: 0,
      sumConfidence: 0,
      nonEmptyArticleIds: new Set<number>(),
    }));
  }

  /** Articles published in each bucket — unique across all clusters. */
  const articlesPerBucket: Array<Set<number>> = Array.from(
    { length: bucketCount },
    () => new Set<number>(),
  );

  /** article_id → ticker → sentiment_score (from TICKER_SENTIMENT cluster rows). */
  const tickersByArticle = new Map<number, Record<string, number>>();

  for (const row of rows) {
    const ts = Date.parse(row.published_at);
    if (!Number.isFinite(ts)) continue;
    if (ts < firstBucketStartMs || ts >= windowEndMs) continue;

    const bucketIdx = Math.floor((ts - firstBucketStartMs) / stepMs);
    if (bucketIdx < 0 || bucketIdx >= bucketCount) continue;

    articlesPerBucket[bucketIdx].add(row.article_id);

    if (!isHeatmapCluster(row.cluster)) continue;

    const accum = accums[row.cluster][bucketIdx];

    // Empty scores_json means "cluster did not fire for this article" — exclude from mean.
    if (!isNonEmptyScoreObject(row.scores_json)) continue;

    const articleScore = meanOfScores(row.scores_json!);
    if (articleScore == null) continue;

    const confRaw = row.confidence;
    const conf =
      typeof confRaw === "number" && Number.isFinite(confRaw)
        ? Math.max(0, Math.min(1, confRaw))
        : 1;
    if (conf <= 0) continue;

    accum.sumScoreWeighted += articleScore * conf;
    accum.sumConfidence += conf;
    accum.nonEmptyArticleIds.add(row.article_id);

    if (row.cluster === "TICKER_SENTIMENT") {
      tickersByArticle.set(row.article_id, row.scores_json!);
    }
  }

  const totalArticlesPerBucket = articlesPerBucket.map((s) => s.size);

  const cells: Record<HeatmapCluster, HeatmapCell[]> = {} as Record<
    HeatmapCluster,
    HeatmapCell[]
  >;
  for (const cluster of HEATMAP_CLUSTERS) {
    cells[cluster] = [];
    for (let i = 0; i < bucketCount; i++) {
      const accum = accums[cluster][i];
      const total = totalArticlesPerBucket[i];
      const nonEmpty = accum.nonEmptyArticleIds.size;
      const score =
        accum.sumConfidence > 0
          ? accum.sumScoreWeighted / accum.sumConfidence
          : null;
      const coverage = total > 0 ? nonEmpty / total : 0;

      // Top tickers across non-empty articles in this cell.
      const aggTickers: Record<string, number> = {};
      for (const aid of accum.nonEmptyArticleIds) {
        const t = tickersByArticle.get(aid);
        if (!t) continue;
        for (const [ticker, s] of Object.entries(t)) {
          if (typeof s !== "number" || !Number.isFinite(s)) continue;
          aggTickers[ticker] = (aggTickers[ticker] ?? 0) + s;
        }
      }
      const topTickers = Object.entries(aggTickers)
        .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
        .slice(0, 3)
        .map(([ticker, s]) => ({ ticker, score: s }));

      cells[cluster].push({
        score,
        coverage,
        totalArticles: total,
        nonEmptyArticles: nonEmpty,
        topTickers,
      });
    }
  }

  return {
    bucketStarts: bucketStarts.map((d) => d.toISOString()),
    granularity,
    cells,
    totalArticlesPerBucket,
  };
}

/** Trailing simple-moving-average smoother for one cluster's cells. Each
 *  output bucket averages the current bucket plus up to `window - 1` previous
 *  buckets — partial windows at the start (not enough history) just use what's
 *  available. Smoothing applies to `score` and `coverage` only; per-bucket
 *  metadata (`totalArticles`, `nonEmptyArticles`, `topTickers`) is preserved
 *  so the drill-down still surfaces *that* bucket's articles, not a window. */
export function smoothHeatmapCells(
  cells: HeatmapCell[],
  window: number,
): HeatmapCell[] {
  if (window <= 1 || cells.length === 0) return cells;
  const out: HeatmapCell[] = new Array(cells.length);
  for (let i = 0; i < cells.length; i++) {
    const start = Math.max(0, i - window + 1);
    let scoreSum = 0;
    let scoreN = 0;
    let covSum = 0;
    let covN = 0;
    for (let j = start; j <= i; j++) {
      const c = cells[j];
      if (c.score != null && Number.isFinite(c.score)) {
        scoreSum += c.score;
        scoreN += 1;
      }
      if (c.totalArticles > 0) {
        covSum += c.coverage;
        covN += 1;
      }
    }
    const cur = cells[i];
    out[i] = {
      ...cur,
      score: scoreN > 0 ? scoreSum / scoreN : null,
      coverage: covN > 0 ? covSum / covN : cur.coverage,
    };
  }
  return out;
}

/** Applies `smoothHeatmapCells` to every cluster in the result. Pass-through
 *  when window <= 1. */
export function smoothHeatmapResult(
  result: HeatmapResult,
  window: number,
): HeatmapResult {
  if (window <= 1) return result;
  const cells = {} as Record<HeatmapCluster, HeatmapCell[]>;
  for (const c of HEATMAP_CLUSTERS) {
    cells[c] = smoothHeatmapCells(result.cells[c], window);
  }
  return { ...result, cells };
}

/** Ranks the articles that fired the given cluster inside the bucket starting
 *  at `bucketStartIso` (width = one `granularity` step). Impact = signed
 *  confidence-weighted score; rows are sorted by |impact| descending so the
 *  most influential stories surface first regardless of direction. */
export function articlesForCell(
  rows: HeatmapInputRow[],
  cluster: HeatmapCluster,
  bucketStartIso: string,
  granularity: HeatmapGranularity = "1h",
  /** Trailing window width in bucket units. When the heatmap is smoothed with
   *  window N, callers pass N here so the drill-down surfaces every article
   *  that fed the smoothed cell — i.e. the clicked bucket plus the preceding
   *  N-1 buckets. */
  windowBuckets: number = 1,
): Array<{ article_id: number; impact: number }> {
  const startMs = Date.parse(bucketStartIso);
  if (!Number.isFinite(startMs)) return [];
  const stepMs = GRANULARITY_MS[granularity];
  const span = Math.max(1, Math.floor(windowBuckets));
  const windowStartMs = startMs - (span - 1) * stepMs;
  const endMs = startMs + stepMs;

  const byId = new Map<number, number>();
  for (const r of rows) {
    if (r.cluster !== cluster) continue;
    if (!r.scores_json) continue;
    const ts = Date.parse(r.published_at);
    if (!Number.isFinite(ts) || ts < windowStartMs || ts >= endMs) continue;

    let sum = 0;
    let n = 0;
    for (const v of Object.values(r.scores_json)) {
      if (typeof v === "number" && Number.isFinite(v)) {
        sum += v;
        n += 1;
      }
    }
    if (n === 0) continue;
    const mean = sum / n;

    const confRaw = r.confidence;
    const conf =
      typeof confRaw === "number" && Number.isFinite(confRaw)
        ? Math.max(0, Math.min(1, confRaw))
        : 1;
    if (conf <= 0) continue;

    const impact = mean * conf;
    // Keep the largest-magnitude entry if the same article appears more than once.
    const prev = byId.get(r.article_id);
    if (prev == null || Math.abs(impact) > Math.abs(prev)) {
      byId.set(r.article_id, impact);
    }
  }

  return Array.from(byId.entries())
    .map(([article_id, impact]) => ({ article_id, impact }))
    .sort((a, b) => Math.abs(b.impact) - Math.abs(a.impact));
}

/**
 * Articles ranked by their impact on a SPECIFIC sub-factor dimension within a
 * cluster + bucket. Impact = dimension value × confidence. Keys are matched
 * case-insensitively because the data action uppercases all scores_json keys.
 */
export function articlesForDimensionCell(
  rows: HeatmapInputRow[],
  cluster: HeatmapCluster,
  dimensionKey: string,
  bucketStartIso: string,
  granularity: HeatmapGranularity = "1h",
  windowBuckets: number = 1,
): Array<{ article_id: number; impact: number }> {
  const startMs = Date.parse(bucketStartIso);
  if (!Number.isFinite(startMs)) return [];
  const stepMs = GRANULARITY_MS[granularity];
  const span = Math.max(1, Math.floor(windowBuckets));
  const windowStartMs = startMs - (span - 1) * stepMs;
  const endMs = startMs + stepMs;
  const dimKeyUpper = dimensionKey.toUpperCase();

  const byId = new Map<number, number>();
  for (const r of rows) {
    if (r.cluster !== cluster) continue;
    if (!r.scores_json) continue;
    const ts = Date.parse(r.published_at);
    if (!Number.isFinite(ts) || ts < windowStartMs || ts >= endMs) continue;

    const v =
      r.scores_json[dimensionKey] ?? r.scores_json[dimKeyUpper];
    if (typeof v !== "number" || !Number.isFinite(v)) continue;

    const confRaw = r.confidence;
    const conf =
      typeof confRaw === "number" && Number.isFinite(confRaw)
        ? Math.max(0, Math.min(1, confRaw))
        : 1;
    if (conf <= 0) continue;

    const impact = v * conf;
    const prev = byId.get(r.article_id);
    if (prev == null || Math.abs(impact) > Math.abs(prev)) {
      byId.set(r.article_id, impact);
    }
  }

  return Array.from(byId.entries())
    .map(([article_id, impact]) => ({ article_id, impact }))
    .sort((a, b) => Math.abs(b.impact) - Math.abs(a.impact));
}

/** Column label for a bucket, sized to fit the heatmap header. */
export function formatBucketLabel(
  iso: string,
  granularity: HeatmapGranularity,
): string {
  const d = new Date(iso);
  if (granularity === "1d") {
    return d.toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      timeZone: "UTC",
    });
  }
  return String(d.getUTCHours()).padStart(2, "0");
}

/** Tooltip-friendly bucket label including date for non-hourly views. */
export function formatBucketTooltip(
  iso: string,
  granularity: HeatmapGranularity,
): string {
  const d = new Date(iso);
  if (granularity === "1d") {
    return d.toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
      timeZone: "UTC",
    });
  }
  const hour = String(d.getUTCHours()).padStart(2, "0");
  const date = d.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
  if (granularity === "4h") {
    const endHour = String((d.getUTCHours() + 4) % 24).padStart(2, "0");
    return `${hour}:00–${endHour}:00 UTC · ${date}`;
  }
  return `${hour}:00 UTC · ${date}`;
}

// ── Visual encoding ────────────────────────────────────────────────────────────

export function colorForScore(score: number | null): string | null {
  if (score == null || score === 0) return null;
  if (score <= -0.5) return "rgb(220, 38, 38)"; // strong negative — red-600
  if (score <= -0.25) return "rgb(239, 68, 68)"; // mid negative — red-500
  if (score < 0) return "rgb(248, 113, 113)"; // weak negative — red-400
  if (score < 0.25) return "rgb(74, 222, 128)"; // weak positive — green-400
  if (score < 0.5) return "rgb(34, 197, 94)"; // mid positive — green-500
  return "rgb(22, 163, 74)"; // strong positive — green-600
}

/** Coverage → opacity with a 0.15 floor so low-coverage cells still register. */
export function opacityForCoverage(
  coverage: number,
  hasArticles: boolean,
): number {
  if (!hasArticles) return 0;
  const c = Math.max(0, Math.min(1, coverage));
  return 0.15 + c * 0.85;
}

// ── Caption ────────────────────────────────────────────────────────────────────

/** Pure-template caption — no LLM. Picks the strongest positive and negative cells. */
export function buildHeatmapCaption(result: HeatmapResult): string {
  let topPos: { cluster: HeatmapCluster; bucket: number; score: number } | null =
    null;
  let topNeg: { cluster: HeatmapCluster; bucket: number; score: number } | null =
    null;

  const bucketCount = result.bucketStarts.length;

  for (const cluster of HEATMAP_CLUSTERS) {
    for (let i = 0; i < bucketCount; i++) {
      const cell = result.cells[cluster][i];
      if (cell.score == null) continue;
      // Ignore micro-coverage signals (< 5%) so a single-article fluke doesn't dominate.
      if (cell.coverage < 0.05) continue;
      if (cell.score > 0 && (topPos == null || cell.score > topPos.score)) {
        topPos = { cluster, bucket: i, score: cell.score };
      }
      if (cell.score < 0 && (topNeg == null || cell.score < topNeg.score)) {
        topNeg = { cluster, bucket: i, score: cell.score };
      }
    }
  }

  const peakLabel = (bucketIdx: number) =>
    formatBucketTooltip(result.bucketStarts[bucketIdx], result.granularity);

  const parts: string[] = [];
  if (topPos) {
    parts.push(
      `${CLUSTER_LABELS[topPos.cluster]} firing positive (peak ${peakLabel(topPos.bucket)})`,
    );
  }
  if (topNeg) {
    parts.push(
      `${CLUSTER_LABELS[topNeg.cluster]} weighing negative (peak ${peakLabel(topNeg.bucket)})`,
    );
  }
  if (parts.length === 0) {
    return "No strong cluster signals in this window.";
  }
  return `${parts.join("; ")}.`;
}
