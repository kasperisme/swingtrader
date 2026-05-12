import { describe, it, expect } from "vitest";
import {
  aggregateNewsImpactHeatmap,
  buildHeatmapCaption,
  HEATMAP_BUCKET_COUNT,
  HEATMAP_CLUSTERS,
  type HeatmapInputRow,
} from "@/lib/news-impact-heatmap/aggregate";

// Fixed "now" so bucket math is deterministic. Buckets span [2026-05-11T15:00Z, 2026-05-12T15:00Z).
const NOW = new Date("2026-05-12T14:35:00Z");
const OLDEST_BUCKET_START = new Date("2026-05-11T15:00:00Z");

function inBucket(bucketIdx: number, minute = 30): string {
  const d = new Date(OLDEST_BUCKET_START);
  d.setUTCHours(d.getUTCHours() + bucketIdx);
  d.setUTCMinutes(minute);
  return d.toISOString();
}

describe("aggregateNewsImpactHeatmap", () => {
  it("returns 24 buckets and all 11 clusters", () => {
    const r = aggregateNewsImpactHeatmap([], NOW);
    expect(r.bucketStarts).toHaveLength(HEATMAP_BUCKET_COUNT);
    expect(Object.keys(r.cells).sort()).toEqual([...HEATMAP_CLUSTERS].sort());
    expect(r.cells.MACRO_SENSITIVITY).toHaveLength(HEATMAP_BUCKET_COUNT);
  });

  it("all-empty bucket: every article has scores_json={} → score=null, coverage=0, count preserved", () => {
    // Two articles, both with empty scores for BUSINESS_MODEL. Empty must mean
    // "cluster did not fire" — not "neutral zero" — so the cell stays null.
    const rows: HeatmapInputRow[] = [
      {
        article_id: 10,
        cluster: "BUSINESS_MODEL",
        scores_json: {},
        confidence: 0.9,
        published_at: inBucket(3),
      },
      {
        article_id: 11,
        cluster: "BUSINESS_MODEL",
        scores_json: null,
        confidence: 0.5,
        published_at: inBucket(3),
      },
    ];
    const r = aggregateNewsImpactHeatmap(rows, NOW);
    const cell = r.cells.BUSINESS_MODEL[3];
    expect(cell.score).toBeNull();
    expect(cell.coverage).toBe(0);
    expect(cell.nonEmptyArticles).toBe(0);
    expect(cell.totalArticles).toBe(2);
  });

  it("mixed-confidence bucket: cell score is confidence-weighted across non-empty articles", () => {
    // a1: mean = 0.4, conf 0.2  →  contributes  0.08
    // a2: mean = -0.6, conf 0.8 →  contributes -0.48
    // a3: empty scores_json → EXCLUDED from mean (signal: cluster did not fire)
    // weighted = (0.08 - 0.48) / (0.2 + 0.8) = -0.4
    // coverage = 2 non-empty / 3 total
    const rows: HeatmapInputRow[] = [
      {
        article_id: 100,
        cluster: "MACRO_SENSITIVITY",
        scores_json: { a: 0.4 },
        confidence: 0.2,
        published_at: inBucket(10),
      },
      {
        article_id: 101,
        cluster: "MACRO_SENSITIVITY",
        scores_json: { a: -0.4, b: -0.8 },
        confidence: 0.8,
        published_at: inBucket(10),
      },
      {
        article_id: 102,
        cluster: "MACRO_SENSITIVITY",
        scores_json: {},
        confidence: 0.95,
        published_at: inBucket(10),
      },
    ];
    const r = aggregateNewsImpactHeatmap(rows, NOW);
    const cell = r.cells.MACRO_SENSITIVITY[10];
    expect(cell.score).toBeCloseTo(-0.4, 5);
    expect(cell.nonEmptyArticles).toBe(2);
    expect(cell.totalArticles).toBe(3);
    expect(cell.coverage).toBeCloseTo(2 / 3, 5);
  });

  it("single-article bucket: cell score equals that article's sub-factor mean", () => {
    const rows: HeatmapInputRow[] = [
      {
        article_id: 200,
        cluster: "GROWTH_PROFILE",
        scores_json: { a: 0.3, b: -0.1 },
        confidence: 0.7,
        published_at: inBucket(15),
      },
    ];
    const r = aggregateNewsImpactHeatmap(rows, NOW);
    const cell = r.cells.GROWTH_PROFILE[15];
    expect(cell.score).toBeCloseTo(0.1, 5); // (0.3 + -0.1) / 2
    expect(cell.nonEmptyArticles).toBe(1);
    expect(cell.totalArticles).toBe(1);
    expect(cell.coverage).toBe(1);
  });

  it("treating empty scores_json as zero would distort the signal — guard against it", () => {
    // If we (wrongly) treated empty as 0, the cell score would be (0.7 + 0) / 2 = 0.35.
    // Correct behaviour: empty is dropped, so cell score = 0.7.
    const rows: HeatmapInputRow[] = [
      {
        article_id: 1,
        cluster: "MACRO_SENSITIVITY",
        scores_json: {},
        confidence: 1,
        published_at: inBucket(5),
      },
      {
        article_id: 2,
        cluster: "MACRO_SENSITIVITY",
        scores_json: { x: 0.6, y: 0.8 },
        confidence: 1,
        published_at: inBucket(5),
      },
    ];
    const r = aggregateNewsImpactHeatmap(rows, NOW);
    expect(r.cells.MACRO_SENSITIVITY[5].score).toBeCloseTo(0.7, 5);
  });

  it("articles outside the 24h window are excluded entirely", () => {
    const rows: HeatmapInputRow[] = [
      {
        article_id: 1,
        cluster: "MACRO_SENSITIVITY",
        scores_json: { a: 0.9 },
        confidence: 1,
        published_at: "2026-05-10T10:00:00Z", // 2 days before NOW
      },
    ];
    const r = aggregateNewsImpactHeatmap(rows, NOW);
    expect(r.cells.MACRO_SENSITIVITY.every((c) => c.totalArticles === 0)).toBe(
      true,
    );
  });

  it("TICKER_SENTIMENT rows populate top-tickers on cells whose articles fired this cluster", () => {
    const rows: HeatmapInputRow[] = [
      {
        article_id: 300,
        cluster: "MACRO_SENSITIVITY",
        scores_json: { a: 0.5 },
        confidence: 1,
        published_at: inBucket(8),
      },
      {
        article_id: 300,
        cluster: "TICKER_SENTIMENT",
        scores_json: { NVDA: 0.7, AAPL: -0.2 },
        confidence: 1,
        published_at: inBucket(8),
      },
    ];
    const r = aggregateNewsImpactHeatmap(rows, NOW);
    const cell = r.cells.MACRO_SENSITIVITY[8];
    expect(cell.topTickers.map((t) => t.ticker)).toContain("NVDA");
  });
});

describe("buildHeatmapCaption", () => {
  it("returns a fallback string when no cells crossed the coverage threshold", () => {
    const r = aggregateNewsImpactHeatmap([], NOW);
    expect(buildHeatmapCaption(r)).toMatch(/no strong/i);
  });

  it("names the strongest positive and negative clusters with their UTC hour", () => {
    const rows: HeatmapInputRow[] = [
      {
        article_id: 1,
        cluster: "GROWTH_PROFILE",
        scores_json: { a: 0.9 },
        confidence: 1,
        published_at: inBucket(20),
      },
      {
        article_id: 2,
        cluster: "FINANCIAL_STRUCTURE",
        scores_json: { a: -0.8 },
        confidence: 1,
        published_at: inBucket(6),
      },
    ];
    const r = aggregateNewsImpactHeatmap(rows, NOW);
    const caption = buildHeatmapCaption(r);
    expect(caption).toContain("Growth");
    expect(caption).toContain("Financials");
    expect(caption).toMatch(/\d{2}:00 UTC/);
  });
});
