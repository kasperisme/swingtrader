"use server";

import { createClient } from "@/lib/supabase/server";

export type CompanySnapshot = {
  ticker: string;
  vectorDate: string;
  dimensions: Record<string, number>;
  raw: Record<string, number | null>;
  metadata: {
    name?: string;
    sector?: string;
    industry?: string;
    market_cap?: number;
  };
};

export type CompanyFingerprintResult =
  | { ok: true; data: CompanySnapshot }
  | { ok: false; error: string };

function asObject(v: unknown): Record<string, unknown> {
  if (v && typeof v === "object" && !Array.isArray(v)) {
    return v as Record<string, unknown>;
  }
  if (typeof v === "string") {
    try {
      const parsed = JSON.parse(v);
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        return parsed as Record<string, unknown>;
      }
    } catch {
      /* fall through */
    }
  }
  return {};
}

function toNumberMap(v: unknown): Record<string, number> {
  const obj = asObject(v);
  const out: Record<string, number> = {};
  for (const [k, raw] of Object.entries(obj)) {
    const n = Number(raw);
    if (Number.isFinite(n)) out[k] = n;
  }
  return out;
}

function toNullableNumberMap(v: unknown): Record<string, number | null> {
  const obj = asObject(v);
  const out: Record<string, number | null> = {};
  for (const [k, raw] of Object.entries(obj)) {
    if (raw == null) {
      out[k] = null;
      continue;
    }
    const n = Number(raw);
    out[k] = Number.isFinite(n) ? n : null;
  }
  return out;
}

function toSnapshot(
  ticker: string,
  row: Record<string, unknown>,
): CompanySnapshot {
  const meta = asObject(row.metadata_json);
  const marketCap = Number(meta.market_cap);
  return {
    ticker,
    vectorDate: String(row.vector_date ?? ""),
    dimensions: toNumberMap(row.dimensions_json),
    raw: toNullableNumberMap(row.raw_json),
    metadata: {
      name: typeof meta.name === "string" ? meta.name : undefined,
      sector: typeof meta.sector === "string" ? meta.sector : undefined,
      industry: typeof meta.industry === "string" ? meta.industry : undefined,
      market_cap: Number.isFinite(marketCap) ? marketCap : undefined,
    },
  };
}

/** Returns the latest snapshot for `ticker`. */
export async function getCompanyFingerprint(
  ticker: string,
): Promise<CompanyFingerprintResult> {
  const t = ticker.trim().toUpperCase();
  if (!t) return { ok: false, error: "ticker required" };

  const supabase = await createClient();
  const res = await supabase
    .schema("swingtrader")
    .from("company_vectors")
    .select("vector_date, dimensions_json, raw_json, metadata_json")
    .eq("ticker", t)
    .order("vector_date", { ascending: false })
    .limit(1);

  if (res.error) return { ok: false, error: res.error.message };
  const row = res.data?.[0];
  if (!row) return { ok: false, error: "No company vector for ticker" };

  return { ok: true, data: toSnapshot(t, row) };
}
