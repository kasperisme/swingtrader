import type { ValidatedKey } from "@/lib/api-auth";

export const SCREENINGS_V1_CORS: HeadersInit = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Access-Control-Allow-Headers": "Authorization, Content-Type",
};

/** Scope required for POST /api/v1/screenings/* */
export const SCREENINGS_WRITE_SCOPE = "screenings:write";

export const MAX_SCREENING_ROWS_PER_REQUEST = 500;

const SOURCE_MAX = 128;
const DATASET_MAX = 64;
const SYMBOL_MAX = 32;

export function isValidIsoDateOnly(s: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(s)) return false;
  const [y, m, d] = s.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d));
  return dt.getUTCFullYear() === y && dt.getUTCMonth() === m - 1 && dt.getUTCDate() === d;
}

export type ScreeningRunCreateBody = {
  scan_date: string;
  source: string;
  market_json?: unknown;
  result_json?: unknown;
};

export type ScreeningRowInput = {
  dataset: string;
  symbol?: string | null;
  row_data: Record<string, unknown>;
};

export function parseCreateRunBody(body: unknown):
  | { ok: true; value: ScreeningRunCreateBody }
  | { ok: false; message: string } {
  if (body === null || typeof body !== "object" || Array.isArray(body)) {
    return { ok: false, message: "Body must be a JSON object" };
  }
  const o = body as Record<string, unknown>;
  const scanDate = o.scan_date;
  if (typeof scanDate !== "string" || !isValidIsoDateOnly(scanDate)) {
    return { ok: false, message: "'scan_date' must be a valid ISO date (YYYY-MM-DD)" };
  }
  const source = o.source;
  if (typeof source !== "string" || !source.trim()) {
    return { ok: false, message: "'source' is required (non-empty string)" };
  }
  if (source.trim().length > SOURCE_MAX) {
    return { ok: false, message: `'source' must be at most ${SOURCE_MAX} characters` };
  }
  if (o.market_json !== undefined && o.market_json !== null && (typeof o.market_json !== "object" || Array.isArray(o.market_json))) {
    return { ok: false, message: "'market_json' must be an object when provided" };
  }
  if (o.result_json !== undefined && o.result_json !== null && (typeof o.result_json !== "object" || Array.isArray(o.result_json))) {
    return { ok: false, message: "'result_json' must be an object when provided" };
  }
  return {
    ok: true,
    value: {
      scan_date: scanDate,
      source: source.trim(),
      market_json: o.market_json,
      result_json: o.result_json,
    },
  };
}

export function parseAppendRowsBody(body: unknown):
  | { ok: true; value: ScreeningRowInput[] }
  | { ok: false; message: string } {
  if (body === null || typeof body !== "object" || Array.isArray(body)) {
    return { ok: false, message: "Body must be a JSON object" };
  }
  const rowsRaw = (body as { rows?: unknown }).rows;
  if (!Array.isArray(rowsRaw)) {
    return { ok: false, message: "'rows' must be a non-empty array" };
  }
  if (rowsRaw.length === 0) {
    return { ok: false, message: "'rows' must be a non-empty array" };
  }
  if (rowsRaw.length > MAX_SCREENING_ROWS_PER_REQUEST) {
    return {
      ok: false,
      message: `'rows' must have at most ${MAX_SCREENING_ROWS_PER_REQUEST} items per request`,
    };
  }

  const out: ScreeningRowInput[] = [];
  for (let i = 0; i < rowsRaw.length; i++) {
    const item = rowsRaw[i];
    if (item === null || typeof item !== "object" || Array.isArray(item)) {
      return { ok: false, message: `rows[${i}] must be an object` };
    }
    const r = item as Record<string, unknown>;
    const dataset = r.dataset;
    if (typeof dataset !== "string" || !dataset.trim()) {
      return { ok: false, message: `rows[${i}].dataset is required` };
    }
    if (dataset.length > DATASET_MAX) {
      return { ok: false, message: `rows[${i}].dataset is too long (max ${DATASET_MAX})` };
    }
    const rowData = r.row_data;
    if (rowData === null || typeof rowData !== "object" || Array.isArray(rowData)) {
      return { ok: false, message: `rows[${i}].row_data must be an object` };
    }
    let symbol: string | null | undefined = undefined;
    if (r.symbol !== undefined && r.symbol !== null) {
      if (typeof r.symbol !== "string") {
        return { ok: false, message: `rows[${i}].symbol must be a string` };
      }
      const sym = r.symbol.trim().toUpperCase();
      if (sym.length > SYMBOL_MAX) {
        return { ok: false, message: `rows[${i}].symbol is too long` };
      }
      symbol = sym || null;
    }
    out.push({
      dataset: dataset.trim(),
      symbol: symbol === undefined ? undefined : symbol,
      row_data: rowData as Record<string, unknown>,
    });
  }
  return { ok: true, value: out };
}

/** Resolve ticker symbol from row_data keys (aligned with analytics append_scan_rows). */
export function symbolFromRowData(rowData: Record<string, unknown>): string | null {
  for (const k of ["symbol", "ticker", "Symbol"] as const) {
    const v = rowData[k];
    if (v !== undefined && v !== null && String(v).trim()) {
      return String(v).trim().toUpperCase().slice(0, SYMBOL_MAX);
    }
  }
  return null;
}

export function screeningRowsToDbRecords(
  runId: number,
  scanDate: string,
  rows: ScreeningRowInput[],
  key: ValidatedKey,
) {
  return rows.map((r) => ({
    run_id: runId,
    scan_date: scanDate,
    dataset: r.dataset,
    symbol: r.symbol ?? symbolFromRowData(r.row_data),
    row_data: r.row_data,
    user_id: key.userId,
  }));
}
