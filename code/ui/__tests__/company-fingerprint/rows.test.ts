import { describe, it, expect } from "vitest";
import {
  buildOperationalRows,
  buildSectorRows,
} from "@/lib/company-fingerprint/rows";
import { SECTOR_DIMS } from "@/lib/company-fingerprint/dimensions";

describe("buildOperationalRows", () => {
  it("excludes dimensions where raw is null (0.5 sentinel)", () => {
    const dimensions = {
      eps_growth_rate: 0.5, // null raw → excluded
      price_momentum: 0.92, // strong → must appear
      pricing_power: 0.55, // weak deviation
    };
    const raw = {
      eps_growth_rate: null,
      price_momentum: 0.92,
      pricing_power: 0.55,
    };
    const rows = buildOperationalRows({ dimensions, raw });
    const keys = rows.map((r) => r.dim);
    expect(keys).not.toContain("eps_growth_rate");
    expect(keys).toContain("price_momentum");
    expect(keys).toContain("pricing_power");
  });

  it("excludes sector classification dims even when raw is non-null", () => {
    const dimensions = {
      sector_technology: 0.95,
      price_momentum: 0.7,
    };
    const raw = {
      sector_technology: 0.95,
      price_momentum: 0.7,
    };
    const rows = buildOperationalRows({ dimensions, raw });
    expect(rows.map((r) => r.dim)).toEqual(["price_momentum"]);
  });

  it("sorts by |value - 0.5| descending", () => {
    const dimensions = {
      a: 0.55, // dev 0.05
      b: 0.1, // dev 0.40
      c: 0.95, // dev 0.45
    };
    const raw = { a: 1, b: 1, c: 1 };
    const rows = buildOperationalRows({ dimensions, raw });
    expect(rows.map((r) => r.dim)).toEqual(["c", "b", "a"]);
  });

  it("respects topN cap", () => {
    const dimensions: Record<string, number> = {};
    const raw: Record<string, number | null> = {};
    for (let i = 0; i < 30; i++) {
      dimensions[`op_${i}`] = i / 30;
      raw[`op_${i}`] = 1;
    }
    const rows = buildOperationalRows({ dimensions, raw, topN: 5 });
    expect(rows).toHaveLength(5);
  });

  it("attaches pressure when provided", () => {
    const pressureByDim = new Map([["price_momentum", "up" as const]]);
    const rows = buildOperationalRows({
      dimensions: { price_momentum: 0.9, pricing_power: 0.6 },
      raw: { price_momentum: 1, pricing_power: 1 },
      pressureByDim,
    });
    expect(rows.find((r) => r.dim === "price_momentum")?.pressure).toBe("up");
    expect(rows.find((r) => r.dim === "pricing_power")?.pressure).toBeNull();
  });
});

describe("buildSectorRows", () => {
  it("always returns all 8 sector bars regardless of raw null status", () => {
    const dimensions: Record<string, number> = {};
    for (let i = 0; i < SECTOR_DIMS.length; i += 2) {
      dimensions[SECTOR_DIMS[i]] = (i + 1) / 10;
    }
    const rows = buildSectorRows({ dimensions });
    expect(rows.map((r) => r.dim)).toEqual([...SECTOR_DIMS]);
    expect(rows).toHaveLength(8);
  });

  it("missing sector → defaults to 0, still rendered", () => {
    const dimensions = { sector_technology: 0.4 };
    const rows = buildSectorRows({ dimensions });
    expect(rows.find((r) => r.dim === "sector_technology")?.value).toBe(0.4);
    const energy = rows.find((r) => r.dim === "sector_energy");
    expect(energy).toBeDefined();
    expect(energy?.value).toBe(0);
  });

  it("attaches pressure when provided", () => {
    const pressureByDim = new Map([["sector_technology", "up" as const]]);
    const rows = buildSectorRows({
      dimensions: { sector_technology: 0.5 },
      pressureByDim,
    });
    expect(rows.find((r) => r.dim === "sector_technology")?.pressure).toBe("up");
    expect(rows.find((r) => r.dim === "sector_energy")?.pressure).toBeNull();
  });
});
