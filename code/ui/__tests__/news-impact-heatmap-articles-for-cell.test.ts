import { describe, it, expect } from "vitest";
import {
  articlesForCell,
  type HeatmapInputRow,
} from "@/lib/news-impact-heatmap/aggregate";

const BUCKET_START = "2026-05-12T10:00:00Z";
const INSIDE = "2026-05-12T10:30:00Z";
const BEFORE = "2026-05-12T09:30:00Z";
const AFTER = "2026-05-12T11:30:00Z";

function row(p: Partial<HeatmapInputRow> & { article_id: number }): HeatmapInputRow {
  return {
    cluster: "GROWTH_PROFILE",
    confidence: 1,
    published_at: INSIDE,
    scores_json: { x: 0.5 },
    ...p,
  } as HeatmapInputRow;
}

describe("articlesForCell", () => {
  it("returns articles inside the bucket sorted by |impact| desc", () => {
    const rows: HeatmapInputRow[] = [
      row({ article_id: 1, scores_json: { a: 0.2 }, confidence: 1 }), // impact 0.2
      row({ article_id: 2, scores_json: { a: -0.6 }, confidence: 1 }), // impact -0.6
      row({ article_id: 3, scores_json: { a: 0.4 }, confidence: 0.5 }), // impact 0.2
    ];
    const out = articlesForCell(rows, "GROWTH_PROFILE", BUCKET_START);
    expect(out.map((r) => r.article_id)).toEqual([2, 1, 3]);
    expect(out[0].impact).toBeCloseTo(-0.6, 5);
  });

  it("ignores rows outside the bucket window", () => {
    const rows: HeatmapInputRow[] = [
      row({ article_id: 1, published_at: BEFORE, scores_json: { a: 0.9 } }),
      row({ article_id: 2, published_at: AFTER, scores_json: { a: 0.9 } }),
      row({ article_id: 3, published_at: INSIDE, scores_json: { a: 0.3 } }),
    ];
    const out = articlesForCell(rows, "GROWTH_PROFILE", BUCKET_START);
    expect(out.map((r) => r.article_id)).toEqual([3]);
  });

  it("ignores rows with the wrong cluster", () => {
    const rows: HeatmapInputRow[] = [
      row({ article_id: 1, cluster: "MARKET_BEHAVIOUR", scores_json: { a: 0.9 } }),
      row({ article_id: 2, scores_json: { a: 0.3 } }),
    ];
    const out = articlesForCell(rows, "GROWTH_PROFILE", BUCKET_START);
    expect(out.map((r) => r.article_id)).toEqual([2]);
  });

  it("ignores rows with empty or null scores_json", () => {
    const rows: HeatmapInputRow[] = [
      row({ article_id: 1, scores_json: {} }),
      row({ article_id: 2, scores_json: null }),
      row({ article_id: 3, scores_json: { a: 0.4 } }),
    ];
    const out = articlesForCell(rows, "GROWTH_PROFILE", BUCKET_START);
    expect(out.map((r) => r.article_id)).toEqual([3]);
  });

  it("dedups by article_id, keeping the larger-magnitude impact", () => {
    const rows: HeatmapInputRow[] = [
      row({ article_id: 1, scores_json: { a: 0.2 } }),
      row({ article_id: 1, scores_json: { a: -0.5 } }),
    ];
    const out = articlesForCell(rows, "GROWTH_PROFILE", BUCKET_START);
    expect(out).toHaveLength(1);
    expect(out[0].impact).toBeCloseTo(-0.5, 5);
  });

  it("handles 4h granularity window correctly", () => {
    const rows: HeatmapInputRow[] = [
      row({ article_id: 1, published_at: "2026-05-12T10:30:00Z", scores_json: { a: 0.3 } }),
      row({ article_id: 2, published_at: "2026-05-12T13:30:00Z", scores_json: { a: 0.3 } }),
      // Outside the 4h window starting 10:00 — should be excluded.
      row({ article_id: 3, published_at: "2026-05-12T14:30:00Z", scores_json: { a: 0.3 } }),
    ];
    const out = articlesForCell(rows, "GROWTH_PROFILE", BUCKET_START, "4h");
    expect(out.map((r) => r.article_id).sort()).toEqual([1, 2]);
  });

  it("trailing windowBuckets pulls in previous-bucket articles", () => {
    // Bucket starts at 10:00 UTC, 1h granularity. With windowBuckets=3 the
    // active window is [08:00, 11:00). Articles at 08:30 / 09:30 / 10:30 all
    // qualify; one at 07:30 must be excluded.
    const rows: HeatmapInputRow[] = [
      row({ article_id: 1, published_at: "2026-05-12T07:30:00Z", scores_json: { a: 0.5 } }),
      row({ article_id: 2, published_at: "2026-05-12T08:30:00Z", scores_json: { a: 0.3 } }),
      row({ article_id: 3, published_at: "2026-05-12T09:30:00Z", scores_json: { a: 0.4 } }),
      row({ article_id: 4, published_at: "2026-05-12T10:30:00Z", scores_json: { a: -0.6 } }),
    ];
    const out = articlesForCell(rows, "GROWTH_PROFILE", BUCKET_START, "1h", 3);
    expect(out.map((r) => r.article_id).sort()).toEqual([2, 3, 4]);
  });

  it("windowBuckets <= 1 collapses to single-bucket behaviour", () => {
    const rows: HeatmapInputRow[] = [
      row({ article_id: 1, published_at: "2026-05-12T09:30:00Z", scores_json: { a: 0.5 } }),
      row({ article_id: 2, published_at: BUCKET_START, scores_json: { a: 0.3 } }),
    ];
    expect(
      articlesForCell(rows, "GROWTH_PROFILE", BUCKET_START, "1h", 1).map(
        (r) => r.article_id,
      ),
    ).toEqual([2]);
    expect(
      articlesForCell(rows, "GROWTH_PROFILE", BUCKET_START, "1h", 0).map(
        (r) => r.article_id,
      ),
    ).toEqual([2]);
  });
});
