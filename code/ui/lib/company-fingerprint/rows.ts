import { SECTOR_DIMS, isSectorDim } from "./dimensions";
import type { NewsPressure } from "./news-pressure";

export type OperationalRow = {
  dim: string;
  /** Percentile-rank value in [0, 1]. */
  value: number;
  numericLabel: string;
  pressure: NewsPressure | null;
};

export type SectorRow = {
  dim: string;
  value: number;
  pressure: NewsPressure | null;
};

/** Maximum number of operational rows surfaced in the chart. */
export const FINGERPRINT_TOP_N = 18;

/** Operational-fingerprint rows for the latest snapshot:
 *   - excludes sector classification dims (rendered separately)
 *   - excludes dims where raw is null (the 0.5 sentinel for "no data")
 *   - sorted by |value - 0.5| descending, capped at FINGERPRINT_TOP_N */
export function buildOperationalRows(args: {
  dimensions: Record<string, number>;
  raw: Record<string, number | null>;
  pressureByDim?: ReadonlyMap<string, NewsPressure>;
  topN?: number;
}): OperationalRow[] {
  const { dimensions, raw, pressureByDim, topN = FINGERPRINT_TOP_N } = args;
  const out: OperationalRow[] = [];

  for (const [dim, value] of Object.entries(dimensions)) {
    if (isSectorDim(dim)) continue;
    if (raw[dim] == null) continue;
    if (!Number.isFinite(value)) continue;
    out.push({
      dim,
      value,
      numericLabel: value.toFixed(2),
      pressure: pressureByDim?.get(dim) ?? null,
    });
  }
  out.sort((a, b) => Math.abs(b.value - 0.5) - Math.abs(a.value - 0.5));
  return out.slice(0, topN);
}

/** Sector inset always shows all 8 sectors, regardless of raw null status —
 *  zero exposure is informative. Missing values default to 0. */
export function buildSectorRows(args: {
  dimensions: Record<string, number>;
  pressureByDim?: ReadonlyMap<string, NewsPressure>;
}): SectorRow[] {
  const { dimensions, pressureByDim } = args;
  return SECTOR_DIMS.map((dim) => {
    const v = dimensions[dim];
    const value = typeof v === "number" && Number.isFinite(v) ? v : 0;
    return {
      dim,
      value,
      pressure: pressureByDim?.get(dim) ?? null,
    };
  });
}
