import { describe, expect, it } from "vitest";

import { parseImpactSummary } from "@/lib/news/impact-summary";

describe("parseImpactSummary", () => {
  it("returns null without a summary line", () => {
    expect(parseImpactSummary(null)).toBeNull();
    expect(
      parseImpactSummary({ scores_json: { NVDA: 0.2 }, reasoning_json: { NVDA: "x" } }),
    ).toBeNull();
  });

  it("parses tickers and puts reconstruction-backed reads first", () => {
    const s = parseImpactSummary({
      scores_json: { MGC: -0.6, AKAM: -0.3 },
      reasoning_json: { _summary: "Net negative.", AKAM: "Capex hits FCF.", MGC: "Rich." },
      meta_json: {
        AKAM: { relation: "challenges", assumption: "16.6% FCF margin", priced_in_as_of: "2026-09-24" },
        MGC: { relation: "new_information" },
      },
    });
    expect(s?.summary).toBe("Net negative.");
    expect(s?.tickers.map((t) => t.ticker)).toEqual(["AKAM", "MGC"]);
    expect(s?.tickers[0]).toMatchObject({
      relation: "challenges",
      assumption: "16.6% FCF margin",
      pricedInAsOf: "2026-09-24",
    });
    expect(s?.tickers[1]).toMatchObject({ relation: "no_reconstruction", assumption: null });
  });

  it("treats legacy rows without a reconstruction date as no_reconstruction", () => {
    const s = parseImpactSummary({
      scores_json: { MGC: 0 },
      reasoning_json: { _summary: "s", MGC: "r" },
      meta_json: JSON.stringify({ MGC: { relation: "not_material", assumption: "unknown" } }),
    });
    expect(s?.tickers[0]).toMatchObject({ relation: "no_reconstruction", assumption: null });
  });

  it("clamps scores and drops non-numeric ones", () => {
    const s = parseImpactSummary({
      scores_json: { A: 4, B: "x" },
      reasoning_json: { _summary: "s" },
      meta_json: { A: { relation: "confirms", priced_in_as_of: "2026-09-01" } },
    });
    expect(s?.tickers).toHaveLength(1);
    expect(s?.tickers[0].score).toBe(1);
  });
});
