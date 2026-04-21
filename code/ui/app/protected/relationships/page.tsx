import { Suspense } from "react";
import { createClient } from "@/lib/supabase/server";
import { RelationshipsUI } from "./relationships-ui";
import { type TickerRow } from "../vectors/vectors-ui";

async function fetchCompanyVectors(): Promise<TickerRow[]> {
  const supabase = await createClient();

  const { data, error } = await supabase
    .schema("swingtrader")
    .from("company_vectors")
    .select(
      "ticker, vector_date, dimensions_json, raw_json, metadata_json, fetched_at",
    )
    .order("ticker", { ascending: true })
    .order("vector_date", { ascending: false });

  if (error) {
    console.error("Failed to fetch company vectors:", error);
    return [];
  }

  const seen = new Set<string>();
  const rows: TickerRow[] = [];

  for (const row of data ?? []) {
    if (seen.has(row.ticker)) continue;
    seen.add(row.ticker);

    let dimensions: Record<string, number | null> = {};
    let raw: Record<string, number | null> = {};
    let metadata = {
      name: row.ticker,
      sector: "",
      industry: "",
      market_cap: null as number | null,
    };

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

async function RelationshipsData() {
  const vectors = await fetchCompanyVectors();
  return <RelationshipsUI vectors={vectors} />;
}

export default function RelationshipsPage() {
  return (
    <div className="sm:-mx-2 lg:-mx-4 xl:-mx-8 flex flex-col h-[calc(100svh-9rem)] min-h-[480px] w-[85vw] content-center">
      <Suspense
        fallback={
          <div className="flex-1 flex items-center justify-center text-sm text-muted-foreground animate-pulse">
            Loading explore view…
          </div>
        }
      >
        <RelationshipsData />
      </Suspense>
    </div>
  );
}
