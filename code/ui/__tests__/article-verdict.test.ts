import { describe, expect, it } from "vitest";

import {
  buildVerdict,
  claimMetaOf,
  parseHeadlineStance,
  percentileAnchor,
  rationaleAddsInformation,
  splitClaim,
  type ScoreHistogram,
} from "@/lib/news/article-verdict";

describe("parseHeadlineStance", () => {
  it.each([
    ["Duluth Holdings: The 'Build To Last' Strategy Is Pushing Profits Higher, Buy", "call", "bullish", "Buy"],
    ["Intel: Foundry Losses Keep Mounting, Strong Sell", "call", "bearish", "Strong Sell"],
    ["Target: Margins Are Fine But Growth Isn't, Hold", "call", "neutral", "Hold"],
    ["PayPal: Rating Downgrade On Stalled Buyout", "call", "bearish", "Downgrade"],
    ["Morgan Stanley upgrades Nike to Overweight on inventory reset", "call", "bullish", "Upgrade to Overweight"],
    ["3 Dividend Stocks to Buy in September", "call", "bullish", "Buy"],
    ["NuScale Has One Overlooked Quality Worth Buying Into", "call", "bullish", "Buy"],
    ["Don't Buy Carnival Before Earnings", "call", "bearish", "Don't buy"],
    ["Snowflake Plunges After Guidance Cut", "tone", "bearish", "bearish"],
    ["Vertiv Sees Data Center Demand Strengthen as Pipeline Expands", "tone", "bullish", "bullish"],
  ])("%s", (title, kind, direction, label) => {
    expect(parseHeadlineStance(title)).toEqual({ kind, direction, label });
  });

  it("takes no side on a question", () => {
    expect(parseHeadlineStance("Is Nvidia a Buy After Earnings?").kind).toBe("none");
  });

  it("does not read product news as an analyst call", () => {
    expect(parseHeadlineStance("Microsoft upgrades Windows security stack").kind).not.toBe("call");
  });

  it("does not read buy-and-hold as a Hold rating", () => {
    expect(parseHeadlineStance("Why I Like This Stock for Buy-and-Hold").kind).not.toBe("call");
  });

  it("takes no side on a neutral headline", () => {
    expect(parseHeadlineStance("Space42 and Viasat Sign Binding Agreement to co-found Equatys").kind).toBe("none");
  });
});

describe("buildVerdict", () => {
  const duluth = "Duluth Holdings: The 'Build To Last' Strategy Is Pushing Profits Higher, Buy";

  it("flags a headline the score contradicts", () => {
    const v = buildVerdict({
      title: duluth,
      primary: { ticker: "DLTH", score: -0.2 },
      claimImpacts: [-0.6, -0.5, -0.4, 0.3],
    })!;
    expect(v.headline).toBe("Source says Buy.");
    expect(v.score).toBe("We score DLTH −0.20 across four claims.");
    expect(v.agreement).toBe("contradicts");
    expect(v.conclusion).toBe("Score contradicts the headline.");
  });

  it("says so when the score confirms", () => {
    const v = buildVerdict({ title: duluth, primary: { ticker: "DLTH", score: 0.4 }, claimImpacts: [0.4] })!;
    expect(v.conclusion).toBe("Score confirms the headline.");
  });

  it("still gives a stance when the headline takes none", () => {
    const v = buildVerdict({ title: "Company Announces Board Changes", primary: null, claimImpacts: [-0.4, -0.2] })!;
    expect(v.headline).toBe("Headline takes no side.");
    expect(v.score).toBe("Two claims average −0.30.");
    expect(v.conclusion).toBe("Our read: bearish.");
  });

  it("returns null with nothing to stand on", () => {
    expect(buildVerdict({ title: duluth, primary: null, claimImpacts: [] })).toBeNull();
  });
});

describe("percentileAnchor", () => {
  const hist: ScoreHistogram = [
    { score: -0.8, n: 10 },
    { score: -0.2, n: 20 },
    { score: 0, n: 10 },
    { score: 0.3, n: 40 },
    { score: 0.6, n: 20 },
  ];

  it("counts ties half for a negative score", () => {
    // above −0.2: 70, equal: 20 → (70 + 10) / 100
    expect(percentileAnchor(hist, -0.2, "claim")).toEqual({
      side: "negative",
      pct: 80,
      text: "More negative than 80% of claims this week",
    });
  });

  it("anchors a positive score from below", () => {
    // below 0.6: 80, equal: 20 → (80 + 10) / 100
    expect(percentileAnchor(hist, 0.6, "ticker")?.text).toBe("More positive than 90% of ticker scores this week");
  });

  it("refuses to anchor on a thin sample", () => {
    expect(percentileAnchor([{ score: 0.1, n: 5 }], 0.1, "claim")).toBeNull();
  });
});

describe("claims", () => {
  it("splits on the last separator", () => {
    expect(splitClaim("Revenue fell 7.8% — the fourth decline. — Q4 comps now carry the year.")).toEqual({
      claim: "Revenue fell 7.8% — the fourth decline.",
      rationale: "Q4 comps now carry the year.",
    });
  });

  it("rejects the live Duluth restatements", () => {
    expect(
      rationaleAddsInformation(
        "Quarterly revenue decreased by 7.8% in Q2.",
        "Recent top-line decline indicates ongoing operational struggle.",
      ),
    ).toBe(false);
    expect(
      rationaleAddsInformation(
        "The company maintains a strong balance sheet with low debt, robust liquidity, and optimized inventory.",
        "Strong financial health provides a safety buffer against short-term revenue declines.",
      ),
    ).toBe(false);
  });

  it("keeps a rationale that adds a number, horizon or consequence", () => {
    expect(
      rationaleAddsInformation(
        "Duluth's Q2 profit was helped by a one-time tariff refund of $16.3 million.",
        "Excluding this $16.3M non-recurring benefit, underlying operating income was significantly weaker, pressuring next quarter's comparable EPS growth.",
      ),
    ).toBe(true);
  });

  it("reads novelty from meta_json, never guessing", () => {
    const meta = { kp_1: { novelty: "priced_in", novelty_basis: "Q2 reported earlier" }, kp_2: { novelty: "maybe" } };
    expect(claimMetaOf(meta, "kp_1")).toEqual({ novelty: "priced_in", basis: "Q2 reported earlier" });
    expect(claimMetaOf(meta, "kp_2").novelty).toBeNull();
    expect(claimMetaOf(null, "kp_1").novelty).toBeNull();
  });
});
