import { describe, it, expect } from "vitest";
import {
  HEATMAP_CLUSTERS,
  smoothHeatmapCells,
  smoothHeatmapResult,
  type HeatmapCell,
  type HeatmapResult,
} from "@/lib/news-impact-heatmap/aggregate";

function cell(score: number | null, opts: Partial<HeatmapCell> = {}): HeatmapCell {
  return {
    score,
    coverage: opts.coverage ?? (score == null ? 0 : 0.5),
    totalArticles: opts.totalArticles ?? (score == null ? 0 : 4),
    nonEmptyArticles: opts.nonEmptyArticles ?? (score == null ? 0 : 2),
    topTickers: opts.topTickers ?? [],
  };
}

describe("smoothHeatmapCells", () => {
  it("returns input unchanged for window <= 1", () => {
    const cells = [cell(0.2), cell(-0.4)];
    expect(smoothHeatmapCells(cells, 1)).toBe(cells);
    expect(smoothHeatmapCells(cells, 0)).toBe(cells);
  });

  it("returns input unchanged for empty cells array", () => {
    expect(smoothHeatmapCells([], 3)).toEqual([]);
  });

  it("trailing window: bucket i averages buckets [i-window+1..i]", () => {
    const cells = [
      cell(0.2),
      cell(0.6),
      cell(0.0),
      cell(-0.3),
      cell(-0.9),
    ];
    const out = smoothHeatmapCells(cells, 3);
    // Index 0: only itself (partial window) — 0.2
    expect(out[0].score!).toBeCloseTo(0.2, 5);
    // Index 1: mean(0.2, 0.6) = 0.4
    expect(out[1].score!).toBeCloseTo(0.4, 5);
    // Index 2: mean(0.2, 0.6, 0.0) = 0.2666...
    expect(out[2].score!).toBeCloseTo(0.8 / 3, 5);
    // Index 3: mean(0.6, 0.0, -0.3) = 0.1
    expect(out[3].score!).toBeCloseTo(0.3 / 3, 5);
    // Index 4: mean(0.0, -0.3, -0.9) = -0.4
    expect(out[4].score!).toBeCloseTo(-0.4, 5);
  });

  it("excludes null-score buckets from the score average", () => {
    const cells = [cell(0.4), cell(null), cell(0.6)];
    const out = smoothHeatmapCells(cells, 3);
    // Window {0.4, null, 0.6} → mean of {0.4, 0.6} = 0.5
    expect(out[2].score!).toBeCloseTo(0.5, 5);
  });

  it("null score across the whole window → smoothed score is null", () => {
    const cells = [cell(null), cell(null), cell(null)];
    const out = smoothHeatmapCells(cells, 3);
    expect(out[2].score).toBeNull();
  });

  it("smooths coverage too — excludes zero-article buckets", () => {
    const cells = [
      cell(0.5, { coverage: 0.8, totalArticles: 10 }),
      cell(null, { coverage: 0, totalArticles: 0 }),
      cell(0.3, { coverage: 0.4, totalArticles: 5 }),
    ];
    const out = smoothHeatmapCells(cells, 3);
    // Coverage avg of {0.8, 0.4} = 0.6
    expect(out[2].coverage).toBeCloseTo(0.6, 5);
  });

  it("preserves per-bucket metadata (totalArticles / nonEmptyArticles / topTickers)", () => {
    const tickers = [{ ticker: "AAPL", score: 0.4 }];
    const cells = [
      cell(0.5, { totalArticles: 10, nonEmptyArticles: 4, topTickers: tickers }),
      cell(0.3, { totalArticles: 7, nonEmptyArticles: 3 }),
    ];
    const out = smoothHeatmapCells(cells, 3);
    expect(out[0].totalArticles).toBe(10);
    expect(out[0].nonEmptyArticles).toBe(4);
    expect(out[0].topTickers).toEqual(tickers);
    expect(out[1].totalArticles).toBe(7);
    expect(out[1].nonEmptyArticles).toBe(3);
  });
});

describe("smoothHeatmapResult", () => {
  function buildResult(): HeatmapResult {
    const cells = {} as HeatmapResult["cells"];
    for (const c of HEATMAP_CLUSTERS) {
      cells[c] = [cell(0.2), cell(0.4), cell(0.6)];
    }
    return {
      bucketStarts: [
        "2026-05-12T08:00:00Z",
        "2026-05-12T09:00:00Z",
        "2026-05-12T10:00:00Z",
      ],
      granularity: "1h",
      cells,
      totalArticlesPerBucket: [10, 10, 10],
    };
  }

  it("is a pass-through for window <= 1", () => {
    const r = buildResult();
    expect(smoothHeatmapResult(r, 1)).toBe(r);
  });

  it("smooths every cluster independently", () => {
    const r = buildResult();
    const out = smoothHeatmapResult(r, 3);
    for (const c of HEATMAP_CLUSTERS) {
      // (0.2 + 0.4 + 0.6) / 3 = 0.4
      expect(out.cells[c][2].score!).toBeCloseTo(0.4, 5);
    }
    // Top-level metadata (bucketStarts, granularity) unchanged.
    expect(out.bucketStarts).toEqual(r.bucketStarts);
    expect(out.granularity).toBe("1h");
  });
});
