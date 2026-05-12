import { describe, it, expect } from "vitest";
import {
  DIM_TO_CLUSTERS,
  SECTOR_DIMS,
  isSectorDim,
  operationalDimsOf,
} from "@/lib/company-fingerprint/dimensions";
import { HEATMAP_CLUSTERS } from "@/lib/news-impact-heatmap/aggregate";

describe("dimensions module", () => {
  it("DIM_TO_CLUSTERS keys look like valid dim identifiers (snake_case, no typos)", () => {
    // The spec describes ~42 dimensions but the live raw_json keys are the
    // source of truth at runtime. This check exists only to catch obvious
    // typos in the static mapping — e.g. trailing spaces or empty keys.
    const keyShape = /^[a-z][a-z0-9_]*$/;
    for (const k of Object.keys(DIM_TO_CLUSTERS)) {
      expect(keyShape.test(k), `bad dim key: ${JSON.stringify(k)}`).toBe(true);
    }
  });

  it("has exactly 8 sector dims wired through SECTOR_ROTATION", () => {
    const sectorEntries = Object.entries(DIM_TO_CLUSTERS).filter(([, m]) =>
      m.some((x) => Array.isArray(x) && x[0] === "SECTOR_ROTATION"),
    );
    expect(sectorEntries).toHaveLength(8);
  });

  it("DIM_TO_CLUSTERS contains every sector dim", () => {
    for (const s of SECTOR_DIMS) {
      expect(DIM_TO_CLUSTERS[s]).toBeDefined();
    }
  });

  it("every DIM_TO_CLUSTERS entry references a known heatmap cluster", () => {
    const valid = new Set<string>(HEATMAP_CLUSTERS);
    for (const [dim, mappings] of Object.entries(DIM_TO_CLUSTERS)) {
      expect(mappings.length).toBeGreaterThan(0);
      for (const m of mappings) {
        const cluster = Array.isArray(m) ? m[0] : m;
        expect(valid.has(cluster), `${dim} → ${cluster}`).toBe(true);
      }
    }
  });

  it("sector dims route through SECTOR_ROTATION sub-keys matching the dim name", () => {
    for (const s of SECTOR_DIMS) {
      const m = DIM_TO_CLUSTERS[s];
      expect(Array.isArray(m[0])).toBe(true);
      const [cluster, subKey] = m[0] as [string, string];
      expect(cluster).toBe("SECTOR_ROTATION");
      expect(subKey).toBe(s);
    }
  });

  it("isSectorDim correctly identifies sector vs operational dims", () => {
    for (const s of SECTOR_DIMS) expect(isSectorDim(s)).toBe(true);
    expect(isSectorDim("eps_growth_rate")).toBe(false);
    expect(isSectorDim("not_a_real_dim")).toBe(false);
  });

  it("operationalDimsOf excludes sector dims and preserves order otherwise", () => {
    const input = [
      "eps_growth_rate",
      "sector_technology",
      "price_momentum",
      "sector_energy",
    ];
    expect(operationalDimsOf(input)).toEqual([
      "eps_growth_rate",
      "price_momentum",
    ]);
  });
});
