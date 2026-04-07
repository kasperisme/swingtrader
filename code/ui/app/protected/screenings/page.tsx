import { Suspense } from "react";
import { createClient } from "@/lib/supabase/server";
import { ScreeningsUI, type ScanRun, type ScreeningRow, type ScanRowNote } from "./screenings-ui";

async function fetchRuns(): Promise<ScanRun[]> {
  const supabase = await createClient();
  const { data, error } = await supabase
    .schema("swingtrader")
    .from("scan_runs")
    .select("id, created_at, scan_date, source")
    .order("created_at", { ascending: false })
    .limit(50);

  if (error) {
    console.error("Failed to fetch scan runs:", error);
    return [];
  }
  return data ?? [];
}

function asNum(v: unknown): number | null {
  if (v == null) return null;
  const n = typeof v === "number" ? v : parseFloat(String(v));
  return isFinite(n) ? n : null;
}

function asBool(v: unknown): boolean | null {
  if (v == null) return null;
  return Boolean(v);
}

function parseRow(scanRowId: number, runId: number, symbol: string, d: Record<string, unknown>): ScreeningRow {
  return {
    scan_row_id: scanRowId,
    run_id: runId,
    symbol: symbol || String(d.ticker ?? d.symbol ?? ""),
    sector: String(d.sector ?? d.sector_x ?? d.sector_y ?? ""),
    industry: String(d.industry ?? d.subSector ?? ""),
    subSector: String(d.subSector ?? d.industry ?? ""),
    // Technical
    RS_Rank: asNum(d.RS_Rank ?? d.rs_rank),
    Passed: !!(d.Passed),
    PASSED_FUNDAMENTALS: !!(d.PASSED_FUNDAMENTALS),
    PriceOverSMA150And200: !!(d.PriceOverSMA150And200),
    SMA150AboveSMA200: !!(d.SMA150AboveSMA200),
    SMA50AboveSMA150And200: !!(d.SMA50AboveSMA150And200),
    SMA200Slope: !!(d.SMA200Slope),
    PriceAbove25Percent52WeekLow: !!(d.PriceAbove25Percent52WeekLow),
    PriceWithin25Percent52WeekHigh: !!(d.PriceWithin25Percent52WeekHigh),
    RSOver70: !!(d.RSOver70),
    // Volume / price action
    adr_pct: asNum(d.adr_pct),
    vol_ratio_today: asNum(d.vol_ratio_today),
    up_down_vol_ratio: asNum(d.up_down_vol_ratio),
    accumulation: asBool(d.accumulation),
    rs_line_new_high: asBool(d.rs_line_new_high),
    within_buy_range: asBool(d.within_buy_range),
    extended: asBool(d.extended),
    // Fundamentals
    increasing_eps: !!(d.increasing_eps),
    beat_estimate: !!(d.beat_estimate),
    eps_growth_yoy: asNum(d.eps_growth_yoy),
    rev_growth_yoy: asNum(d.rev_growth_yoy),
    eps_accelerating: asBool(d.eps_accelerating),
    three_yr_annual_eps_25pct: asBool(d.three_yr_annual_eps_25pct),
    roe: asNum(d.roe),
    roe_above_17pct: asBool(d.roe_above_17pct),
    passes_oneil_fundamentals: asBool(d.passes_oneil_fundamentals),
    // Sector
    sector_is_leader: asBool(d.sector_is_leader),
    sector_rank: asNum(d.sector_rank),
    total_sectors: asNum(d.total_sectors),
    // Institutional
    inst_shares_increasing: asBool(d.inst_shares_increasing),
    inst_pct_accumulating: asNum(d.inst_pct_accumulating),
  };
}

async function fetchRows(runId: number): Promise<ScreeningRow[]> {
  const supabase = await createClient();

  // Fetch both datasets: trend_template (ibd_screener) and passed_stocks (run_screener)
  const [ttRes, psRes] = await Promise.all([
    supabase
      .schema("swingtrader")
      .from("scan_rows")
      .select("id, run_id, symbol, row_data")
      .eq("run_id", runId)
      .eq("dataset", "trend_template"),
    supabase
      .schema("swingtrader")
      .from("scan_rows")
      .select("id, run_id, symbol, row_data")
      .eq("run_id", runId)
      .eq("dataset", "passed_stocks"),
  ]);

  // Prefer passed_stocks (richer data) if present, else fall back to trend_template
  const source = (psRes.data && psRes.data.length > 0) ? psRes.data : (ttRes.data ?? []);

  return source.map(r => parseRow(r.id, r.run_id, r.symbol ?? "", r.row_data as Record<string, unknown>));
}

async function fetchRowNotes(runId: number): Promise<ScanRowNote[]> {
  const supabase = await createClient();
  const { data } = await supabase
    .schema("swingtrader")
    .from("scan_row_notes")
    .select("scan_row_id, run_id, ticker, status, highlighted, comment, stage, priority, tags, metadata_json, created_at, updated_at")
    .eq("run_id", runId)
    .order("updated_at", { ascending: false });
  return (data ?? []) as ScanRowNote[];
}

async function fetchCompanyVectors(): Promise<{
  tickers: Set<string>;
  dimensions: Record<string, Record<string, number>>;
}> {
  const supabase = await createClient();
  const { data } = await supabase
    .schema("swingtrader")
    .from("company_vectors")
    .select("ticker, dimensions_json, vector_date")
    .order("ticker", { ascending: true })
    .order("vector_date", { ascending: false });

  const tickers = new Set<string>();
  const dimensions: Record<string, Record<string, number>> = {};

  // Keep only the latest vector per ticker
  const seen = new Set<string>();
  for (const row of data ?? []) {
    const ticker = row.ticker as string;
    if (seen.has(ticker)) continue;
    seen.add(ticker);
    tickers.add(ticker);
    const raw = row.dimensions_json;
    if (raw && typeof raw === "object") {
      dimensions[ticker] = raw as Record<string, number>;
    } else if (typeof raw === "string") {
      try { dimensions[ticker] = JSON.parse(raw); } catch { dimensions[ticker] = {}; }
    } else {
      dimensions[ticker] = {};
    }
  }

  return { tickers, dimensions };
}

async function ScreeningsData({ searchParams }: { searchParams: Promise<{ run?: string }> }) {
  const params = await searchParams;
  const runId = params.run ? parseInt(params.run, 10) : null;

  const [runs, { tickers: vectorTickers, dimensions: companyVectorDimensions }] = await Promise.all([
    fetchRuns(),
    fetchCompanyVectors(),
  ]);
  const effectiveRunId = runId ?? runs[0]?.id ?? null;
  const [rows, initialNotes] = effectiveRunId
    ? await Promise.all([fetchRows(effectiveRunId), fetchRowNotes(effectiveRunId)])
    : [[], []];

  return (
    <ScreeningsUI
      runs={runs}
      rows={rows}
      selectedRunId={effectiveRunId}
      vectorTickers={vectorTickers}
      companyVectorDimensions={companyVectorDimensions}
      initialNotes={initialNotes}
    />
  );
}

export default function ScreeningsPage({
  searchParams,
}: {
  searchParams: Promise<{ run?: string }>;
}) {
  return (
    <div className="flex-1 w-full flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold">Screenings</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Minervini trend template — NYSE &amp; NASDAQ market-wide scans.
        </p>
      </div>

      <Suspense
        fallback={
          <div className="text-sm text-muted-foreground animate-pulse">Loading screenings…</div>
        }
      >
        <ScreeningsData searchParams={searchParams} />
      </Suspense>
    </div>
  );
}
