import { describe, it, expect } from "vitest";
import {
  PRESSURE_THRESHOLD,
  articleIdsMentioningTicker,
  bucketPressure,
  buildDimPressureMap,
  dimSignedScore,
} from "@/lib/company-fingerprint/news-pressure";
import type { HeatmapInputRow } from "@/lib/news-impact-heatmap/aggregate";

const NOW_ISO = "2026-05-12T12:00:00Z";

function row(
  partial: Partial<HeatmapInputRow> & { article_id: number; cluster: string },
): HeatmapInputRow {
  return {
    confidence: 1,
    published_at: NOW_ISO,
    scores_json: null,
    ...partial,
  } as HeatmapInputRow;
}

describe("bucketPressure thresholding", () => {
  it("null + non-finite → null", () => {
    expect(bucketPressure(null)).toBeNull();
    expect(bucketPressure(Number.NaN)).toBeNull();
    expect(bucketPressure(Number.POSITIVE_INFINITY)).toBeNull();
  });

  it("|score| just below threshold → neutral", () => {
    expect(bucketPressure(PRESSURE_THRESHOLD - 1e-9)).toBe("neutral");
    expect(bucketPressure(-(PRESSURE_THRESHOLD - 1e-9))).toBe("neutral");
    expect(bucketPressure(0)).toBe("neutral");
  });

  it("|score| exactly at threshold → directional (not neutral)", () => {
    expect(bucketPressure(PRESSURE_THRESHOLD)).toBe("up");
    expect(bucketPressure(-PRESSURE_THRESHOLD)).toBe("down");
  });

  it("|score| just above threshold → directional", () => {
    expect(bucketPressure(0.16)).toBe("up");
    expect(bucketPressure(-0.16)).toBe("down");
  });
});

describe("articleIdsMentioningTicker", () => {
  const rows: HeatmapInputRow[] = [
    row({
      article_id: 1,
      cluster: "TICKER_SENTIMENT",
      scores_json: { AAPL: 0.4, MSFT: -0.2 },
    }),
    row({
      article_id: 2,
      cluster: "TICKER_SENTIMENT",
      scores_json: { GOOG: 0.1 },
    }),
    row({
      article_id: 3,
      cluster: "GROWTH_PROFILE",
      scores_json: { AAPL: 0.5 }, // not a TICKER_SENTIMENT row — should be ignored here
    }),
    row({
      article_id: 4,
      cluster: "TICKER_SENTIMENT",
      scores_json: { AAPL: 0 }, // zero sentiment doesn't count as a mention
    }),
  ];

  it("returns only article ids whose TICKER_SENTIMENT row mentions the ticker non-zero", () => {
    expect([...articleIdsMentioningTicker(rows, "AAPL")]).toEqual([1]);
  });

  it("upper-cases the ticker", () => {
    expect([...articleIdsMentioningTicker(rows, "aapl")]).toEqual([1]);
  });

  it("empty/whitespace ticker → empty set", () => {
    expect(articleIdsMentioningTicker(rows, "").size).toBe(0);
    expect(articleIdsMentioningTicker(rows, "   ").size).toBe(0);
  });
});

describe("dimSignedScore (cluster-level mapping)", () => {
  const rows: HeatmapInputRow[] = [
    row({
      article_id: 1,
      cluster: "TICKER_SENTIMENT",
      scores_json: { AAPL: 0.3 },
    }),
    row({
      article_id: 2,
      cluster: "TICKER_SENTIMENT",
      scores_json: { AAPL: -0.2 },
    }),
    row({
      article_id: 1,
      cluster: "GROWTH_PROFILE",
      scores_json: { eps: 0.6, rev: 0.4 }, // mean = 0.5
      confidence: 1,
    }),
    row({
      article_id: 2,
      cluster: "GROWTH_PROFILE",
      scores_json: { eps: -0.3 }, // mean = -0.3
      confidence: 1,
    }),
    row({
      article_id: 99,
      cluster: "GROWTH_PROFILE",
      scores_json: { eps: 1.0 }, // article 99 has no TICKER_SENTIMENT mention of AAPL — must be excluded
      confidence: 1,
    }),
  ];

  it("filters by ticker mentions and confidence-weights the cluster mean", () => {
    const s = dimSignedScore(rows, "AAPL", "eps_growth_rate");
    // Only articles 1 (0.5) and 2 (-0.3) count; both have conf=1 → mean = 0.1
    expect(s).not.toBeNull();
    expect(s!).toBeCloseTo(0.1, 5);
  });

  it("returns null when the ticker isn't mentioned anywhere", () => {
    expect(dimSignedScore(rows, "TSLA", "eps_growth_rate")).toBeNull();
  });

  it("returns null for unknown dim", () => {
    expect(dimSignedScore(rows, "AAPL", "no_such_dim")).toBeNull();
  });
});

describe("dimSignedScore (sector sub-key mapping)", () => {
  const rows: HeatmapInputRow[] = [
    row({
      article_id: 1,
      cluster: "TICKER_SENTIMENT",
      scores_json: { AAPL: 0.5 },
    }),
    row({
      article_id: 1,
      cluster: "SECTOR_ROTATION",
      scores_json: { sector_technology: 0.4, sector_energy: -0.3 },
    }),
  ];

  it("pulls only the matching sub-key, not the cluster-wide mean", () => {
    const tech = dimSignedScore(rows, "AAPL", "sector_technology");
    const energy = dimSignedScore(rows, "AAPL", "sector_energy");
    expect(tech!).toBeCloseTo(0.4, 5);
    expect(energy!).toBeCloseTo(-0.3, 5);
  });

  it("missing sub-key → null", () => {
    const fin = dimSignedScore(rows, "AAPL", "sector_financials");
    expect(fin).toBeNull();
  });
});

describe("buildDimPressureMap", () => {
  it("returns empty map when no news at all", () => {
    expect(buildDimPressureMap([], "AAPL").size).toBe(0);
  });

  it("returns empty map when ticker not mentioned", () => {
    const rows = [
      row({
        article_id: 1,
        cluster: "TICKER_SENTIMENT",
        scores_json: { MSFT: 0.3 },
      }),
    ];
    expect(buildDimPressureMap(rows, "AAPL").size).toBe(0);
  });

  it("buckets each mapped dim into up/down/neutral", () => {
    const rows: HeatmapInputRow[] = [
      row({
        article_id: 1,
        cluster: "TICKER_SENTIMENT",
        scores_json: { AAPL: 0.5 },
      }),
      row({
        article_id: 1,
        cluster: "GROWTH_PROFILE",
        scores_json: { x: 0.4 },
      }),
      row({
        article_id: 1,
        cluster: "MARKET_BEHAVIOUR",
        scores_json: { y: -0.4 },
      }),
      row({
        article_id: 1,
        cluster: "VALUATION_POSITIONING",
        scores_json: { z: 0.05 },
      }),
    ];
    const m = buildDimPressureMap(rows, "AAPL");
    expect(m.get("eps_growth_rate")).toBe("up");
    expect(m.get("short_interest_ratio")).toBe("down");
    expect(m.get("price_momentum")).toBe("neutral");
  });
});
