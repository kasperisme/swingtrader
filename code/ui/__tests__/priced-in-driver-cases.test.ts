/**
 * The driver-to-case join.
 *
 * `cases_json` used to hold one reconstruction per published analyst model and
 * now holds one investigation per DRIVER, keyed by `driver_index` into
 * `drivers_json` as the generator emitted it. Two things about that join can
 * break silently, and both are covered here with a real payload from a
 * `priced-in/3` run of PLNT:
 *
 *   1. The UI reorders drivers least-priced-first for display. Attaching the
 *      cases after that sort pairs each with whichever driver landed in its old
 *      slot — the fixture has two drivers at the same 10% band, so a
 *      positional slip lands on a plausible-looking wrong one.
 *   2. Legacy `priced-in/2` rows hold analyst-shaped cases in the same column.
 *      Those have no `driver_index` and must never attach to a driver.
 */
import { describe, expect, it } from "vitest";

import {
  parseAnalystCases,
  parseDrivers,
  parsePassages,
  parseSources,
  splitCitations,
} from "@/lib/quote/priced-in-vote";

import fixture from "./fixtures/priced-in-driver-cases.json";

const { drivers, cases } = fixture as {
  drivers: Record<string, unknown>[];
  cases: Record<string, unknown>[];
};

describe("per-driver cases", () => {
  it("keeps every driver, cased or not", () => {
    expect(parseDrivers(drivers, cases)).toHaveLength(drivers.length);
  });

  it("attaches a case only to the driver it was written about", () => {
    const parsed = parseDrivers(drivers, cases);
    const withCase = parsed.filter((d) => d.case);
    expect(withCase).toHaveLength(cases.length);

    // The case carries its own copy of the driver text. It is not the join key
    // — the index is — which is exactly what makes it usable to check the join.
    for (const c of cases) {
      const owner = parsed.find((d) => d.driver === c.driver);
      expect(owner, `no driver matches ${String(c.driver)}`).toBeDefined();
      expect(owner!.case?.whatCoverageSays).toBe(c.what_coverage_says);
    }
  });

  it("survives the least-priced-first reordering", () => {
    const parsed = parseDrivers(drivers, cases);
    const pcts = parsed.map((d) => d.pricedInPct);
    expect(pcts).toEqual([...pcts].sort((a, b) => a - b));
    // The fixture's two cased drivers share a band, so a positional slip would
    // still look ordered — the pairing above is what catches it.
    expect(new Set(parsed.filter((d) => d.case).map((d) => d.pricedInPct)).size)
      .toBeLessThanOrEqual(2);
  });

  it("carries the measured coverage read, not just the prose", () => {
    const cased = parseDrivers(drivers, cases).filter((d) => d.case);
    for (const d of cased) {
      const n = d.case!.narrative!;
      expect(n.scanned).toBeGreaterThan(0);
      expect(n.related).toBeGreaterThanOrEqual(0);
      expect(Math.abs(n.netImpact)).toBeLessThanOrEqual(1);
    }
  });

  it("records whether a series actually ran", () => {
    const byDriver = new Map(
      parseDrivers(drivers, cases).map((d) => [d.driver, d.case]),
    );
    for (const c of cases) {
      const m = byDriver.get(String(c.driver))!.measurement!;
      const raw = c.measurement as Record<string, unknown>;
      expect(m.ran).toBe(raw.result != null);
      // An unwired observable must say so rather than reporting a silent pass.
      if (!m.ran) expect(m.note).toBeTruthy();
    }
  });
});

describe("legacy priced-in/2 rows", () => {
  const analyst = [
    {
      firm: "Jefferies",
      analyst: "A. Name",
      target: 133,
      implied_move: 1.5,
      stance: "rejected_bull",
      case: "The bull case.",
      load_bearing: "One assumption.",
      market_objection: "Why not.",
      confidence: "high",
      n_passages: 12,
      sources: ["A headline"],
      retrieval: { selective: true, distinct_articles: 40 },
      model: "glm-5.1:cloud",
    },
  ];

  it("never attaches an analyst case to a driver", () => {
    for (const d of parseDrivers(drivers, analyst)) {
      expect(d.case).toBeNull();
    }
  });

  it("still parses the analyst shape for rows that predate the inversion", () => {
    const [c] = parseAnalystCases(analyst);
    expect(c.firm).toBe("Jefferies");
    expect(c.stance).toBe("rejected_bull");
  });

  it("does not read driver cases as analyst cases", () => {
    expect(parseAnalystCases(cases)).toHaveLength(0);
  });
});


describe("cited headlines", () => {
  it("reads the {title, slug} shape the generator writes", () => {
    expect(
      parseSources([{ title: "A headline", slug: "a-headline" }]),
    ).toEqual([{ title: "A headline", slug: "a-headline" }]);
  });

  it("reads the bare titles every row before priced-in/3 stored", () => {
    // These rows are the ones on the page until the batch regenerates them, so
    // dropping them would have blanked the citations on every live quote.
    expect(parseSources(["A headline"])).toEqual([
      { title: "A headline", slug: null },
    ]);
  });

  it("leaves an unresolvable source unlinked rather than guessing a slug", () => {
    const [s] = parseSources([{ title: "A headline", slug: "" }]);
    expect(s.slug).toBeNull();
  });

  it("drops entries with no title at all", () => {
    expect(parseSources(["", "  ", { slug: "orphan" }, null, 7])).toEqual([]);
  });

  it("survives a malformed column", () => {
    expect(parseSources(null)).toEqual([]);
    expect(parseSources("not an array")).toEqual([]);
  });

  it("carries titles through the real payload", () => {
    for (const d of parseDrivers(drivers, cases)) {
      for (const s of d.case?.sources ?? []) expect(s.title).toBeTruthy();
    }
  });
});

/**
 * The citation → article link.
 *
 * The reading cites its evidence as "(Passage 4)", and the number is only
 * resolvable through the numbered passage list the generator now records.
 * `sources` looks like it would do the job and must never be used for it: it is
 * deduplicated and sorted by title, so its fourth entry is not passage four and
 * linking through it would attribute the sentence to the wrong headline.
 */
describe("passage citations", () => {
  const passages = [
    { n: 1, title: "First headline", slug: "first-headline" },
    { n: 4, title: "Fourth headline", slug: "fourth-headline" },
  ];

  const cited = (text: string) =>
    splitCitations(text)
      .filter((t) => t.passage != null)
      .map((t) => t.passage);

  it("reads the numbered map the generator writes", () => {
    expect(parsePassages(passages)).toEqual(passages);
  });

  it("keys on the stored number, never on array position", () => {
    // Passage 4 is the second entry here — reading it positionally would point
    // a "(Passage 4)" citation at the first headline.
    const parsed = parsePassages(passages);
    expect(parsed.find((p) => p.n === 4)?.slug).toBe("fourth-headline");
  });

  it("is empty for every row written before the map existed", () => {
    expect(parsePassages(undefined)).toEqual([]);
    expect(parsePassages("not an array")).toEqual([]);
    expect(parsePassages([{ title: "No number" }, { n: 0 }, null])).toEqual([]);
  });

  it("finds the form the generator is now told to write", () => {
    expect(cited("Margins expand (Passage 4).")).toEqual([4]);
    expect(cited("Both say so (Passages 1, 4).")).toEqual([1, 4]);
    expect(cited("Both say so (Passages 1 and 4).")).toEqual([1, 4]);
  });

  it("finds the bracketed forms already stored on published rows", () => {
    expect(cited("Passage [4] notes the backlog.")).toEqual([4]);
    expect(cited("Passages [2], [3], and [10] agree.")).toEqual([2, 3, 10]);
    expect(cited("Passage [1] and [4] both say so.")).toEqual([1, 4]);
    expect(cited("...established in passages [1], [4].")).toEqual([1, 4]);
  });

  it("leaves figures alone — only a number after the word is a citation", () => {
    expect(cited("Revenue grew 12% over 4 quarters.")).toEqual([]);
    expect(cited("The 12 retrieved passages are generic.")).toEqual([]);
    // The run ends where the citation does; the next sentence's number is not
    // swept into it.
    expect(cited("(Passage 4). 12% of revenue.")).toEqual([4]);
  });

  it("reassembles the prose verbatim, brackets and punctuation included", () => {
    for (const text of [
      "Margins expand (Passage 4), per the note.",
      "Passages [2], [3], and [10] agree — passage [1] does not.",
      "Nothing cited here at all.",
    ]) {
      expect(splitCitations(text).map((t) => t.text).join("")).toBe(text);
    }
  });
});
