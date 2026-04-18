import { Suspense } from "react";
import { createClient } from "@/lib/supabase/server";
import { ChartsPageClient } from "./charts-client";

type PageProps = {
  searchParams?: Promise<{ tickers?: string }>;
};

async function fetchVectorTickers(): Promise<string[]> {
  const supabase = await createClient();
  const { data, error } = await supabase
    .schema("swingtrader")
    .from("company_vectors")
    .select("ticker, vector_date")
    .order("ticker", { ascending: true })
    .order("vector_date", { ascending: false });

  if (error) {
    console.error("Failed to fetch vector tickers for charts:", error);
    return [];
  }

  const seen = new Set<string>();
  const out: string[] = [];
  for (const row of data ?? []) {
    const t = String(row.ticker ?? "")
      .trim()
      .toUpperCase();
    if (!t || seen.has(t)) continue;
    seen.add(t);
    out.push(t);
  }
  return out;
}

async function ChartsBody({ searchParams }: PageProps) {
  const params = searchParams ? await searchParams : {};
  const suggestionTickers = await fetchVectorTickers();
  const tickersParam = params.tickers;

  return (
    <ChartsPageClient
      key={tickersParam ?? "__default__"}
      tickersParam={tickersParam}
      suggestionTickers={suggestionTickers}
    />
  );
}

export default function ChartsPage({ searchParams }: PageProps) {
  return (
    <div className="flex-1 w-full flex flex-col gap-6">
      <div>
        <p className="text-xs font-semibold uppercase tracking-widest text-amber-500">
          Charts
        </p>
        <h1 className="mt-1 text-2xl font-bold tracking-tight">Ticker charts</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Daily OHLCV with SMA overlays and session-only pivot markers. Search
          resolves tickers like Explore, or open with{" "}
          <code className="text-xs rounded bg-muted px-1 py-0.5">
            ?tickers=AAPL,MSFT
          </code>{" "}
          (defaults to SPY, QQQ, IWM).
        </p>
      </div>

      <Suspense
        fallback={
          <div className="text-sm text-muted-foreground animate-pulse">
            Loading charts…
          </div>
        }
      >
        <ChartsBody searchParams={searchParams} />
      </Suspense>
    </div>
  );
}
