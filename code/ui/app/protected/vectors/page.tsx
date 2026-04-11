import { Suspense } from "react";
import { createClient } from "@/lib/supabase/server";
import { VectorsUI, type TickerRow } from "./vectors-ui";

async function fetchCompanyVectors(): Promise<TickerRow[]> {
  const supabase = await createClient();

  const { data, error } = await supabase
    .schema("swingtrader")
    .from("company_vectors")
    .select("ticker, vector_date, dimensions_json, raw_json, metadata_json, fetched_at")
    .order("ticker", { ascending: true })
    .order("vector_date", { ascending: false });

  if (error) {
    console.error("Failed to fetch company vectors:", error);
    return [];
  }

  // Deduplicate: keep only the latest vector_date per ticker
  const seen = new Set<string>();
  const rows: TickerRow[] = [];

  for (const row of data ?? []) {
    if (seen.has(row.ticker)) continue;
    seen.add(row.ticker);

    let dimensions: Record<string, number | null> = {};
    let raw: Record<string, number | null> = {};
    let metadata = { name: row.ticker, sector: "", industry: "", market_cap: null as number | null };

    try {
      dimensions = JSON.parse(row.dimensions_json ?? "{}");
    } catch {}
    try {
      raw = JSON.parse(row.raw_json ?? "{}");
    } catch {}
    try {
      const m = JSON.parse(row.metadata_json ?? "{}");
      metadata = {
        name: m.name ?? row.ticker,
        sector: m.sector ?? "",
        industry: m.industry ?? "",
        market_cap: m.market_cap ?? null,
      };
    } catch {}

    rows.push({
      ticker: row.ticker,
      vector_date: row.vector_date,
      dimensions,
      raw,
      metadata,
      fetched_at: row.fetched_at,
    });
  }

  return rows;
}

async function VectorsData() {
  const tickers = await fetchCompanyVectors();
  return <VectorsUI tickers={tickers} count={tickers.length} />;
}

export default function VectorsPage() {
  return (
    <div className="flex-1 w-full flex flex-col gap-6">
      <div>
        <p className="text-xs font-semibold uppercase tracking-widest text-amber-500">Fundamentals</p>
        <h1 className="mt-1 text-2xl font-bold tracking-tight">Company Sensitivity Vectors</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Rank-normalised fundamental embeddings across 9 dimension clusters.
        </p>
      </div>

      <Suspense
        fallback={
          <div className="text-sm text-muted-foreground animate-pulse">Loading vectors…</div>
        }
      >
        <VectorsData />
      </Suspense>
    </div>
  );
}
