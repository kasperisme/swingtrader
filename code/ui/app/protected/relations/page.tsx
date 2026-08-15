import { Suspense } from "react";
import { createClient } from "@/lib/supabase/server";
import { RelationshipsUI } from "./relationships-ui";
import { type TickerRow } from "../vectors/vectors-ui";
import { getOnboardingTours } from "@/app/actions/onboarding";
import { PageTour } from "@/app/protected/_components/page-tour";

async function RelationsTourMount() {
  const tours = await getOnboardingTours();
  return <PageTour tourKey="relations" autoStart={!tours.relations} />;
}

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

async function RelationshipsData({ initialTicker }: { initialTicker?: string }) {
  const vectors = await fetchCompanyVectors();
  return <RelationshipsUI vectors={vectors} initialTicker={initialTicker} />;
}

function normalizeTicker(raw: unknown): string | undefined {
  if (typeof raw !== "string") return undefined;
  const t = raw.trim().toUpperCase();
  if (!t) return undefined;
  if (!/^[A-Z0-9.\-]{1,10}$/.test(t)) return undefined;
  return t;
}

export default async function RelationshipsPage({
  searchParams,
}: {
  searchParams?: Promise<{ ticker?: string | string[] }>;
}) {
  const params = (await searchParams) ?? {};
  const raw = Array.isArray(params.ticker) ? params.ticker[0] : params.ticker;
  const initialTicker = normalizeTicker(raw);

  // The graph deliberately bleeds past the layout's horizontal padding, but
  // each negative margin has to be paid for with matching width. This was
  // `w-[85vw]` — 85% of the VIEWPORT inside a max-w-7xl padded container —
  // which overflowed on wide screens and clipped the graph on narrow ones.
  return (
    <div className="flex h-[calc(100svh-9rem)] min-h-[480px] w-full flex-col sm:-mx-2 sm:w-[calc(100%+1rem)] lg:-mx-4 lg:w-[calc(100%+2rem)] xl:-mx-8 xl:w-[calc(100%+4rem)]">
      <Suspense
        fallback={
          <div className="flex flex-1 flex-col gap-2 p-2" aria-hidden>
            <div className="h-9 w-full animate-pulse rounded-md bg-muted/60" />
            <div className="h-6 w-2/3 animate-pulse rounded bg-muted/40" />
            <div className="flex-1 animate-pulse rounded-xl bg-card" />
            <span className="sr-only">Loading explore view…</span>
          </div>
        }
      >
        <RelationshipsData initialTicker={initialTicker} />
      </Suspense>
      <Suspense fallback={null}>
        <RelationsTourMount />
      </Suspense>
    </div>
  );
}
