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
  parseSources,
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
