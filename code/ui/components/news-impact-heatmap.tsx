"use client";

import { Fragment, useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronRight, Loader2 } from "lucide-react";
import {
  computeSessionMarkers,
  type SessionMarkers,
} from "@/lib/news-impact-heatmap/us-trading-sessions";
import {
  aggregateClusterDimensions,
  aggregateNewsImpactHeatmap,
  bucketCountFor,
  buildHeatmapCaption,
  CLUSTER_LABELS,
  colorForScore,
  defaultGranularityForRange,
  formatBucketLabel,
  formatBucketTooltip,
  GRANULARITY_LABELS,
  HEATMAP_BANDS,
  HEATMAP_GRANULARITIES,
  HEATMAP_RANGES,
  isCombinationViable,
  opacityForCoverage,
  rangeLabel,
  smoothHeatmapCells,
  smoothHeatmapResult,
  type HeatmapCell,
  type HeatmapCluster,
  type HeatmapGranularity,
  type HeatmapInputRow,
  type HeatmapRange,
  type HeatmapResult,
} from "@/lib/news-impact-heatmap/aggregate";
import { CLUSTERS as DIMENSION_REGISTRY } from "@/app/protected/vectors/dimensions";
import { HeatmapCellDrilldown } from "./heatmap-cell-drilldown";

/** Cell selection — either the rolled-up cluster cell or a specific sub-factor. */
type SelectedCell =
  | { kind: "cluster"; cluster: HeatmapCluster; bucketIso: string }
  | {
      kind: "dimension";
      cluster: HeatmapCluster;
      dimKey: string;
      dimLabel: string;
      bucketIso: string;
    };

function isSameSelection(
  a: SelectedCell | null,
  b: SelectedCell | null,
): boolean {
  if (!a || !b) return false;
  if (a.kind !== b.kind) return false;
  if (a.cluster !== b.cluster) return false;
  if (a.bucketIso !== b.bucketIso) return false;
  if (a.kind === "dimension" && b.kind === "dimension") {
    return a.dimKey === b.dimKey;
  }
  return true;
}

/** Cluster id → ordered list of its sub-factor dimensions. */
const DIMENSIONS_BY_CLUSTER: Partial<
  Record<HeatmapCluster, Array<{ key: string; label: string }>>
> = (() => {
  const map: Partial<
    Record<HeatmapCluster, Array<{ key: string; label: string }>>
  > = {};
  for (const c of DIMENSION_REGISTRY) {
    map[c.id as HeatmapCluster] = c.dimensions.map((d) => ({
      key: d.key,
      label: d.label,
    }));
  }
  return map;
})();

export type NewsImpactHeatmapProps = {
  rows: HeatmapInputRow[] | null;
  nowIso: string | null;
  loading?: boolean;
  error?: string | null;
  title?: string | null;
  showLegend?: boolean;
  /** Selected range pill. */
  range?: HeatmapRange;
  onRangeChange?: (range: HeatmapRange) => void;
  /** Selected bucket granularity. Defaults to the best fit for the range. */
  granularity?: HeatmapGranularity;
  onGranularityChange?: (granularity: HeatmapGranularity) => void;
};

export function NewsImpactHeatmap({
  rows,
  nowIso,
  loading = false,
  error = null,
  title = "News impact",
  showLegend = true,
  range = "24h",
  onRangeChange,
  granularity,
  onGranularityChange,
}: NewsImpactHeatmapProps) {
  const effectiveGranularity: HeatmapGranularity =
    granularity ?? defaultGranularityForRange(range);
  const bucketCount = bucketCountFor(range, effectiveGranularity);
  const sessionMarkersSupported =
    effectiveGranularity === "1h" || effectiveGranularity === "4h";
  const [showSessions, setShowSessions] = useState(true);
  const [smoothing, setSmoothing] = useState<number>(3);
  const [selectedCell, setSelectedCell] = useState<SelectedCell | null>(null);
  const [expandedClusters, setExpandedClusters] = useState<Set<HeatmapCluster>>(
    () => new Set(),
  );

  function toggleClusterExpansion(c: HeatmapCluster) {
    setExpandedClusters((prev) => {
      const next = new Set(prev);
      if (next.has(c)) next.delete(c);
      else next.add(c);
      return next;
    });
  }

  // Reset selection whenever the underlying dataset changes (range / granularity / new rows).
  useEffect(() => {
    setSelectedCell(null);
  }, [rows, effectiveGranularity, bucketCount]);

  const rawResult: HeatmapResult | null = useMemo(() => {
    if (!rows || !nowIso) return null;
    return aggregateNewsImpactHeatmap(
      rows,
      new Date(nowIso),
      effectiveGranularity,
      bucketCount,
    );
  }, [rows, nowIso, effectiveGranularity, bucketCount]);

  /** Smoothed result drives the visual + caption; raw bucket metadata
   *  (totalArticles / nonEmptyArticles / topTickers) is preserved so the
   *  drill-down still surfaces that bucket's actual stories. */
  const result: HeatmapResult | null = useMemo(() => {
    if (!rawResult) return null;
    return smoothHeatmapResult(rawResult, smoothing);
  }, [rawResult, smoothing]);

  const sessionMarkers: SessionMarkers = useMemo(() => {
    if (!result || !showSessions || !sessionMarkersSupported) {
      return {
        openBucketIdxs: new Set(),
        closeBucketIdxs: new Set(),
        sessionBucketIdxs: new Set(),
      };
    }
    return computeSessionMarkers(result.bucketStarts, result.granularity);
  }, [result, showSessions, sessionMarkersSupported]);

  /** Per-dimension cells for each expanded cluster, computed only on demand.
   *  Smoothing is applied per-dimension with the same window as the top-level
   *  heatmap so the two views stay visually consistent. */
  const dimensionCells: Partial<
    Record<HeatmapCluster, Record<string, HeatmapCell[]>>
  > = useMemo(() => {
    if (!rows || !nowIso || expandedClusters.size === 0) return {};
    const out: Partial<
      Record<HeatmapCluster, Record<string, HeatmapCell[]>>
    > = {};
    for (const c of expandedClusters) {
      const dims = DIMENSIONS_BY_CLUSTER[c];
      if (!dims || dims.length === 0) continue;
      const raw = aggregateClusterDimensions(
        rows,
        c,
        dims.map((d) => d.key),
        new Date(nowIso),
        effectiveGranularity,
        bucketCount,
      );
      const smoothed: Record<string, HeatmapCell[]> = {};
      for (const [k, cells] of Object.entries(raw)) {
        smoothed[k] = smoothHeatmapCells(cells, smoothing);
      }
      out[c] = smoothed;
    }
    return out;
  }, [
    rows,
    nowIso,
    expandedClusters,
    effectiveGranularity,
    bucketCount,
    smoothing,
  ]);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        {title ? (
          <h3 className="text-sm font-semibold tracking-tight">
            {title}
            <span className="ml-2 text-xs font-normal text-muted-foreground/70">
              · {rangeLabel(range)} · {GRANULARITY_LABELS[effectiveGranularity]}
            </span>
          </h3>
        ) : (
          <span />
        )}
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <div
            className="flex items-center gap-1.5"
            title="How far back the heatmap reaches — pick a window."
          >
            <span className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground/70">
              Range
            </span>
            <HeatmapRangePicker
              range={range}
              onChange={onRangeChange}
              disabled={loading}
            />
          </div>
          <div
            className="flex items-center gap-1.5"
            title="Width of each column — smaller buckets show finer timing, larger buckets smooth the signal."
          >
            <span className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground/70">
              Bucket
            </span>
            <HeatmapGranularityPicker
              range={range}
              granularity={effectiveGranularity}
              onChange={onGranularityChange}
              disabled={loading}
            />
          </div>
          <div
            className="flex items-center gap-1.5"
            title="Trailing moving average window — averages each cell with previous buckets to surface the underlying trend."
          >
            <span className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground/70">
              Smooth
            </span>
            <HeatmapSmoothingPicker
              window={smoothing}
              onChange={setSmoothing}
              disabled={loading}
            />
          </div>
          {sessionMarkersSupported && (
            <button
              type="button"
              onClick={() => setShowSessions((v) => !v)}
              disabled={loading}
              className={`rounded-full border px-2.5 py-1 text-[10px] font-semibold transition-colors ${
                showSessions
                  ? "border-amber-500/40 bg-amber-500/10 text-amber-300"
                  : "border-border bg-background/60 text-muted-foreground hover:text-foreground"
              } ${loading ? "cursor-not-allowed opacity-60" : ""}`}
              title="Outline US market open → close hours (NYSE, 9:30–16:00 ET)"
            >
              NYSE hours
            </button>
          )}
          {showLegend && <HeatmapLegend />}
        </div>
      </div>

      {loading ? (
        <div className="flex items-center gap-2 py-8 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading news impact…
        </div>
      ) : error ? (
        <p className="py-4 text-sm text-rose-500">{error}</p>
      ) : !result ? (
        <p className="py-8 text-center text-sm text-muted-foreground">
          No data.
        </p>
      ) : (
        <>
          <HeatmapGrid
            result={result}
            sessionMarkers={sessionMarkers}
            selectedCell={selectedCell}
            onCellSelect={(cluster, bucketIso) => {
              const next: SelectedCell = {
                kind: "cluster",
                cluster,
                bucketIso,
              };
              setSelectedCell((prev) =>
                isSameSelection(prev, next) ? null : next,
              );
            }}
            onDimensionSelect={(cluster, dimKey, dimLabel, bucketIso) => {
              const next: SelectedCell = {
                kind: "dimension",
                cluster,
                dimKey,
                dimLabel,
                bucketIso,
              };
              setSelectedCell((prev) =>
                isSameSelection(prev, next) ? null : next,
              );
            }}
            expandedClusters={expandedClusters}
            onToggleCluster={toggleClusterExpansion}
            dimensionCells={dimensionCells}
          />
          <p className="text-xs leading-5 text-muted-foreground">
            {buildHeatmapCaption(result)}
          </p>
          {selectedCell && rows && (
            <HeatmapCellDrilldown
              rows={rows}
              cluster={selectedCell.cluster}
              bucketIso={selectedCell.bucketIso}
              granularity={result.granularity}
              smoothingWindow={smoothing}
              dimensionKey={
                selectedCell.kind === "dimension"
                  ? selectedCell.dimKey
                  : undefined
              }
              dimensionLabel={
                selectedCell.kind === "dimension"
                  ? selectedCell.dimLabel
                  : undefined
              }
              onClose={() => setSelectedCell(null)}
            />
          )}
        </>
      )}
    </div>
  );
}

function HeatmapRangePicker({
  range,
  onChange,
  disabled,
}: {
  range: HeatmapRange;
  onChange?: (range: HeatmapRange) => void;
  disabled?: boolean;
}) {
  return (
    <div className="inline-flex gap-0.5 rounded-full border border-border bg-background/60 p-0.5">
      {HEATMAP_RANGES.map((r) => {
        const selected = r === range;
        return (
          <button
            key={r}
            type="button"
            disabled={disabled || !onChange}
            onClick={() => onChange?.(r)}
            className={`rounded-full px-2.5 py-1 text-[10px] font-semibold transition-colors ${
              selected
                ? "bg-foreground text-background"
                : "text-muted-foreground hover:text-foreground"
            } ${disabled ? "cursor-not-allowed opacity-60" : ""}`}
          >
            {rangeLabel(r)}
          </button>
        );
      })}
    </div>
  );
}

function HeatmapGranularityPicker({
  range,
  granularity,
  onChange,
  disabled,
}: {
  range: HeatmapRange;
  granularity: HeatmapGranularity;
  onChange?: (granularity: HeatmapGranularity) => void;
  disabled?: boolean;
}) {
  return (
    <div className="inline-flex gap-0.5 rounded-full border border-border bg-background/60 p-0.5">
      {HEATMAP_GRANULARITIES.map((g) => {
        const viable = isCombinationViable(range, g);
        const selected = g === granularity;
        return (
          <button
            key={g}
            type="button"
            disabled={disabled || !onChange || !viable}
            onClick={() => onChange?.(g)}
            title={
              viable
                ? `${GRANULARITY_LABELS[g]} buckets`
                : `${GRANULARITY_LABELS[g]} is not a useful bucket size for ${rangeLabel(range)}`
            }
            className={`rounded-full px-2.5 py-1 text-[10px] font-semibold transition-colors ${
              selected
                ? "bg-violet-600 text-white"
                : "text-muted-foreground hover:text-foreground"
            } ${disabled || !viable ? "cursor-not-allowed opacity-40" : ""}`}
          >
            {GRANULARITY_LABELS[g]}
          </button>
        );
      })}
    </div>
  );
}

const SMOOTHING_OPTIONS: Array<{ value: number; label: string; title: string }> = [
  { value: 1, label: "Off", title: "No smoothing — raw per-bucket values" },
  { value: 3, label: "3", title: "Trailing 3-bucket moving average" },
  { value: 5, label: "5", title: "Trailing 5-bucket moving average" },
  { value: 7, label: "7", title: "Trailing 7-bucket moving average" },
];

function HeatmapSmoothingPicker({
  window,
  onChange,
  disabled,
}: {
  window: number;
  onChange?: (window: number) => void;
  disabled?: boolean;
}) {
  return (
    <div className="inline-flex gap-0.5 rounded-full border border-border bg-background/60 p-0.5">
      {SMOOTHING_OPTIONS.map((opt) => {
        const selected = opt.value === window;
        return (
          <button
            key={opt.value}
            type="button"
            disabled={disabled || !onChange}
            onClick={() => onChange?.(opt.value)}
            title={opt.title}
            className={`rounded-full px-2.5 py-1 text-[10px] font-semibold transition-colors ${
              selected
                ? "bg-emerald-600 text-white"
                : "text-muted-foreground hover:text-foreground"
            } ${disabled ? "cursor-not-allowed opacity-60" : ""}`}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}

function HeatmapLegend() {
  const swatches = [
    { c: "rgb(220, 38, 38)", l: "≤ -0.5" },
    { c: "rgb(239, 68, 68)", l: "-0.25" },
    { c: "rgb(248, 113, 113)", l: "< 0" },
    { c: "rgb(74, 222, 128)", l: "< 0.25" },
    { c: "rgb(34, 197, 94)", l: "< 0.5" },
    { c: "rgb(22, 163, 74)", l: "≥ 0.5" },
  ];
  return (
    <div className="hidden items-center gap-1 text-[10px] text-muted-foreground sm:flex">
      <span>negative</span>
      {swatches.map((s) => (
        <span
          key={s.l}
          className="inline-block h-3 w-3 rounded-[2px]"
          style={{ backgroundColor: s.c }}
          title={s.l}
        />
      ))}
      <span>positive</span>
    </div>
  );
}

function contiguousRuns(
  set: Set<number>,
  count: number,
): Array<{ start: number; end: number }> {
  const runs: Array<{ start: number; end: number }> = [];
  let runStart = -1;
  for (let i = 0; i < count; i++) {
    if (set.has(i)) {
      if (runStart === -1) runStart = i;
    } else if (runStart !== -1) {
      runs.push({ start: runStart, end: i - 1 });
      runStart = -1;
    }
  }
  if (runStart !== -1) runs.push({ start: runStart, end: count - 1 });
  return runs;
}

const ALL_CLUSTERS_IN_ORDER: HeatmapCluster[] = HEATMAP_BANDS.flatMap(
  (b) => b.clusters as HeatmapCluster[],
);
const FIRST_CLUSTER = ALL_CLUSTERS_IN_ORDER[0];
const LAST_CLUSTER =
  ALL_CLUSTERS_IN_ORDER[ALL_CLUSTERS_IN_ORDER.length - 1];

function HeatmapGrid({
  result,
  sessionMarkers,
  selectedCell,
  onCellSelect,
  onDimensionSelect,
  expandedClusters,
  onToggleCluster,
  dimensionCells,
}: {
  result: HeatmapResult;
  sessionMarkers: SessionMarkers;
  selectedCell: SelectedCell | null;
  onCellSelect: (cluster: HeatmapCluster, bucketIso: string) => void;
  onDimensionSelect: (
    cluster: HeatmapCluster,
    dimKey: string,
    dimLabel: string,
    bucketIso: string,
  ) => void;
  expandedClusters: Set<HeatmapCluster>;
  onToggleCluster: (c: HeatmapCluster) => void;
  dimensionCells: Partial<
    Record<HeatmapCluster, Record<string, HeatmapCell[]>>
  >;
}) {
  // For wide ranges (90 buckets), thin the column labels so they don't overlap.
  const labelStride =
    result.bucketStarts.length > 30
      ? Math.ceil(result.bucketStarts.length / 14)
      : 1;
  const sessionRuns = useMemo(
    () =>
      contiguousRuns(
        sessionMarkers.sessionBucketIdxs,
        result.bucketStarts.length,
      ),
    [sessionMarkers.sessionBucketIdxs, result.bucketStarts.length],
  );
  const bucketRun: Array<{ start: number; end: number } | null> = useMemo(() => {
    const arr: Array<{ start: number; end: number } | null> = new Array(
      result.bucketStarts.length,
    ).fill(null);
    for (const run of sessionRuns) {
      for (let i = run.start; i <= run.end; i += 1) arr[i] = run;
    }
    return arr;
  }, [sessionRuns, result.bucketStarts.length]);

  return (
    <div className="w-full overflow-x-auto">
      <table className="min-w-max border-separate border-spacing-0 text-[11px]">
        <thead>
          <tr>
            <th className="sticky left-0 z-10 bg-background px-2 py-1 text-left font-medium text-muted-foreground/70">
              Cluster
            </th>
            {result.bucketStarts.map((iso, i) => (
              <th
                key={i}
                className="px-1 py-1 text-center font-mono font-normal text-muted-foreground/50"
              >
                {i % labelStride === 0
                  ? formatBucketLabel(iso, result.granularity)
                  : ""}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {HEATMAP_BANDS.map((band, bandIdx) => {
            const isLastBand = bandIdx === HEATMAP_BANDS.length - 1;
            return band.clusters.map((cluster, ci) => {
              const isLastInBand = ci === band.clusters.length - 1;
              const showDivider = isLastInBand && !isLastBand;
              const expanded = expandedClusters.has(cluster);
              const dims = expanded
                ? (DIMENSIONS_BY_CLUSTER[cluster] ?? [])
                : [];
              const dimCellMap = expanded
                ? (dimensionCells[cluster] ?? {})
                : {};
              const clusterIsBottomOfBox =
                cluster === LAST_CLUSTER && !expanded;
              return (
                <Fragment key={cluster}>
                  <tr>
                  <td
                    className={`sticky left-0 z-10 bg-background px-2 py-1 whitespace-nowrap text-foreground/80 ${
                      showDivider && !expanded ? "border-b border-border" : ""
                    }`}
                    title={band.label}
                  >
                    <button
                      type="button"
                      onClick={() => onToggleCluster(cluster)}
                      className="inline-flex w-full items-center gap-1.5 text-left text-foreground/80 hover:text-foreground"
                      aria-expanded={expanded}
                      aria-label={
                        expanded
                          ? `Collapse ${CLUSTER_LABELS[cluster]} dimensions`
                          : `Expand ${CLUSTER_LABELS[cluster]} dimensions`
                      }
                    >
                      {expanded ? (
                        <ChevronDown className="h-3 w-3 shrink-0 text-muted-foreground" />
                      ) : (
                        <ChevronRight className="h-3 w-3 shrink-0 text-muted-foreground" />
                      )}
                      <span>{CLUSTER_LABELS[cluster]}</span>
                    </button>
                  </td>
                  {result.cells[cluster].map((cell, h) => {
                    const run = bucketRun[h];
                    const isTop = run != null && cluster === FIRST_CLUSTER;
                    const isBottom = run != null && clusterIsBottomOfBox;
                    const isLeft = run != null && h === run.start;
                    const isRight = run != null && h === run.end;
                    const sessionEdges = [
                      isTop ? "border-t-2 border-t-amber-500/60" : "",
                      isBottom ? "border-b-2 border-b-amber-500/60" : "",
                      isLeft ? "border-l-2 border-l-amber-500/60" : "",
                      isRight ? "border-r-2 border-r-amber-500/60" : "",
                    ]
                      .filter(Boolean)
                      .join(" ");
                    const bucketIso = result.bucketStarts[h];
                    const isSelected =
                      selectedCell?.kind === "cluster" &&
                      selectedCell.cluster === cluster &&
                      selectedCell.bucketIso === bucketIso;
                    return (
                      <td
                        key={h}
                        className={`p-0 ${
                          showDivider && !expanded && !isBottom
                            ? "border-b border-border"
                            : ""
                        } ${sessionEdges}`}
                      >
                        <HeatmapCellView
                          cell={cell}
                          cluster={cluster}
                          bucketIso={bucketIso}
                          granularity={result.granularity}
                          selected={isSelected}
                          onClick={() => onCellSelect(cluster, bucketIso)}
                        />
                      </td>
                    );
                  })}
                </tr>
                {expanded &&
                  dims.map((dim, di) => {
                    const isLastDimRow = di === dims.length - 1;
                    const isDimBottomOfBox =
                      cluster === LAST_CLUSTER && isLastDimRow;
                    const dimCells = dimCellMap[dim.key] ?? [];
                    return (
                      <tr
                        key={`${cluster}-${dim.key}`}
                        className="bg-muted/20"
                      >
                        <td
                          className={`sticky left-0 z-10 bg-background pl-7 pr-2 py-0.5 whitespace-nowrap text-[10px] text-muted-foreground ${
                            showDivider && isLastDimRow
                              ? "border-b border-border"
                              : ""
                          }`}
                        >
                          {dim.label}
                        </td>
                        {result.bucketStarts.map((bucketIso, h) => {
                          const run = bucketRun[h];
                          const isLeft = run != null && h === run.start;
                          const isRight = run != null && h === run.end;
                          const isBottom = run != null && isDimBottomOfBox;
                          const sessionEdges = [
                            isBottom ? "border-b-2 border-b-amber-500/60" : "",
                            isLeft ? "border-l-2 border-l-amber-500/60" : "",
                            isRight ? "border-r-2 border-r-amber-500/60" : "",
                          ]
                            .filter(Boolean)
                            .join(" ");
                          const cell = dimCells[h];
                          return (
                            <td
                              key={h}
                              className={`p-0 ${
                                showDivider && isLastDimRow && !isBottom
                                  ? "border-b border-border"
                                  : ""
                              } ${sessionEdges}`}
                            >
                              {cell ? (
                                <DimensionCellView
                                  cell={cell}
                                  dimLabel={dim.label}
                                  bucketIso={bucketIso}
                                  granularity={result.granularity}
                                  selected={
                                    selectedCell?.kind === "dimension" &&
                                    selectedCell.cluster === cluster &&
                                    selectedCell.dimKey === dim.key &&
                                    selectedCell.bucketIso === bucketIso
                                  }
                                  onClick={() =>
                                    onDimensionSelect(
                                      cluster,
                                      dim.key,
                                      dim.label,
                                      bucketIso,
                                    )
                                  }
                                />
                              ) : (
                                <div className="m-[2px] h-5 w-5 sm:h-6 sm:w-6" />
                              )}
                            </td>
                          );
                        })}
                      </tr>
                    );
                  })}
                </Fragment>
              );
            });
          })}
        </tbody>
      </table>
    </div>
  );
}

function HeatmapCellView({
  cell,
  cluster,
  bucketIso,
  granularity,
  selected,
  onClick,
}: {
  cell: HeatmapCell;
  cluster: HeatmapCluster;
  bucketIso: string;
  granularity: HeatmapResult["granularity"];
  selected: boolean;
  onClick: () => void;
}) {
  const fill = colorForScore(cell.score);
  const hasArticles = cell.totalArticles > 0;
  const opacity = opacityForCoverage(cell.coverage, hasArticles);

  const tooltipLines = [
    `${CLUSTER_LABELS[cluster]} @ ${formatBucketTooltip(bucketIso, granularity)}`,
    `Articles: ${cell.nonEmptyArticles}/${cell.totalArticles}`,
    cell.score != null ? `Score: ${cell.score.toFixed(2)}` : `Score: —`,
    `Coverage: ${(cell.coverage * 100).toFixed(0)}%`,
  ];
  if (cell.topTickers.length > 0) {
    tooltipLines.push(
      `Top: ${cell.topTickers
        .map(
          (t) =>
            `${t.ticker} ${t.score >= 0 ? "+" : ""}${t.score.toFixed(2)}`,
        )
        .join(", ")}`,
    );
  }
  if (cell.nonEmptyArticles > 0) {
    tooltipLines.push("Click to see top stories");
  }

  const interactive = cell.nonEmptyArticles > 0;
  const outline = selected
    ? "2px solid rgb(245, 158, 11)" // amber-500 ring for selection
    : hasArticles
      ? "none"
      : "1px solid rgba(255,255,255,0.04)";

  return (
    <button
      type="button"
      onClick={interactive ? onClick : undefined}
      disabled={!interactive}
      className={`m-[2px] block h-5 w-5 rounded-[3px] sm:h-6 sm:w-6 ${
        interactive
          ? "cursor-pointer transition-transform hover:scale-110 focus:outline-none focus:ring-1 focus:ring-amber-500/70"
          : "cursor-default"
      }`}
      style={{
        backgroundColor: fill ?? "transparent",
        opacity: fill ? opacity : 0,
        outline,
      }}
      title={tooltipLines.join("\n")}
      aria-label={tooltipLines.join(". ")}
      aria-pressed={selected}
    />
  );
}

/** Dimension-level cell. Same visual + interaction model as the cluster cell —
 *  clicking surfaces the top stories that fired this specific sub-factor. */
function DimensionCellView({
  cell,
  dimLabel,
  bucketIso,
  granularity,
  selected,
  onClick,
}: {
  cell: HeatmapCell;
  dimLabel: string;
  bucketIso: string;
  granularity: HeatmapResult["granularity"];
  selected: boolean;
  onClick: () => void;
}) {
  const fill = colorForScore(cell.score);
  const hasArticles = cell.totalArticles > 0;
  const opacity = opacityForCoverage(cell.coverage, hasArticles);
  const tooltipLines = [
    `${dimLabel} @ ${formatBucketTooltip(bucketIso, granularity)}`,
    `Articles firing: ${cell.nonEmptyArticles}/${cell.totalArticles}`,
    cell.score != null ? `Score: ${cell.score.toFixed(2)}` : `Score: —`,
    `Coverage: ${(cell.coverage * 100).toFixed(0)}%`,
  ];
  if (cell.nonEmptyArticles > 0) tooltipLines.push("Click to see top stories");

  const interactive = cell.nonEmptyArticles > 0;
  const outline = selected
    ? "2px solid rgb(245, 158, 11)"
    : hasArticles
      ? "none"
      : "1px solid rgba(255,255,255,0.04)";

  return (
    <button
      type="button"
      onClick={interactive ? onClick : undefined}
      disabled={!interactive}
      className={`m-[2px] block h-5 w-5 rounded-[3px] sm:h-6 sm:w-6 ${
        interactive
          ? "cursor-pointer transition-transform hover:scale-110 focus:outline-none focus:ring-1 focus:ring-amber-500/70"
          : "cursor-default"
      }`}
      style={{
        backgroundColor: fill ?? "transparent",
        opacity: fill ? opacity : 0,
        outline,
      }}
      title={tooltipLines.join("\n")}
      aria-label={tooltipLines.join(". ")}
      aria-pressed={selected}
    />
  );
}
