"use client";

import { useState, useMemo, useEffect, useCallback, useRef } from "react";
import { useRouter } from "next/navigation";
import {
  CheckCircle, XCircle, Search, ChevronDown, ChevronUp,
  ChevronLeft, ChevronRight, BarChart2, List, TrendingUp, Loader2, Newspaper, Trash2, RotateCcw, Star, MessageSquare,
  Activity, Copy, Gauge, Plus,
} from "lucide-react";
import { CLUSTERS } from "../vectors/dimensions";
import { NewsTrendsUI, type ArticleImpact } from "../news-trends/news-trends-ui";
import { getCachedQuotes, setCachedQuotes } from "@/lib/quote-cache";
import { fmpGetOhlc, fmpGetQuote, fmpGetPriceAtDate } from "@/app/actions/fmp";
import { createClient } from "@/lib/supabase/client";
import {
  screeningsGetNewsImpacts,
  screeningsGetTickerRelationships,
  screeningsSoftDeleteRun,
  screeningsUpsertDismissNote,
} from "@/app/actions/screenings";
import {
  collectAllRowDataKeys,
  compareRowDataValues,
  getRowDataValue,
  inferBooleanFilterKeys,
  inferNumericFilterKeys,
  isBooleanColumn,
  isNumericColumn,
  MAX_CATEGORICAL_STRING_OPTIONS,
  orderedDataColumnKeys,
  stringifyRowDataValueForFilter,
  uniqueStringValuesForKey,
} from "./screenings-row-data";
import { ScreeningsFilterBar } from "./screenings-filter-bar";
import {
  DEFAULT_SCREENINGS_FILTERS,
  NOTE_STAGE_NONE,
  type ScreeningsFilters,
} from "./screenings-filters-model";

type SentimentArticleImpact = ArticleImpact & {
  ticker_sentiment?: Record<string, number>;
};

export interface ScanRun {
  id: number;
  created_at: string;
  scan_date: string;
  source: string;
}

export interface ScreeningRow {
  scan_row_id: number;
  run_id: number;
  symbol: string;
  /** Raw JSON from `user_scan_rows.row_data` (all keys preserved for dynamic columns / filters). */
  rowData: Record<string, unknown>;
  sector: string;
  industry: string;
  subSector: string;
  // Technical
  RS_Rank: number | null;
  Passed: boolean;
  PASSED_FUNDAMENTALS: boolean;
  PriceOverSMA150And200: boolean;
  SMA150AboveSMA200: boolean;
  SMA50AboveSMA150And200: boolean;
  SMA200Slope: boolean;
  PriceAbove25Percent52WeekLow: boolean;
  PriceWithin25Percent52WeekHigh: boolean;
  RSOver70: boolean;
  // Volume / price action
  adr_pct: number | null;
  vol_ratio_today: number | null;
  up_down_vol_ratio: number | null;
  accumulation: boolean | null;
  rs_line_new_high: boolean | null;
  within_buy_range: boolean | null;
  extended: boolean | null;
  // Fundamentals
  increasing_eps: boolean;
  beat_estimate: boolean;
  eps_growth_yoy: number | null;
  rev_growth_yoy: number | null;
  eps_accelerating: boolean | null;
  three_yr_annual_eps_25pct: boolean | null;
  roe: number | null;
  roe_above_17pct: boolean | null;
  passes_oneil_fundamentals: boolean | null;
  // Sector
  sector_is_leader: boolean | null;
  sector_rank: number | null;
  total_sectors: number | null;
  // Institutional
  inst_shares_increasing: boolean | null;
  inst_pct_accumulating: number | null;
}

type NoteStatus = "active" | "dismissed" | "watchlist" | "pipeline";

export interface ScanRowNote {
  scan_row_id: number;
  run_id: number;
  ticker: string;
  user_id: string;
  status: NoteStatus;
  highlighted: boolean;
  comment: string | null;
  stage: string | null;
  priority: number | null;
  tags: string[];
  metadata_json: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

// ─── small display helpers ───────────────────────────────────────────────────

function Check({ value }: { value: boolean | null | undefined }) {
  if (value == null) return <span className="text-muted-foreground/40 text-xs">—</span>;
  return value ? (
    <CheckCircle className="w-4 h-4 text-emerald-500 shrink-0" />
  ) : (
    <XCircle className="w-4 h-4 text-rose-400 shrink-0" />
  );
}

function Num({
  value,
  suffix = "",
  decimals = 1,
  colorize = false,
}: {
  value: number | null | undefined;
  suffix?: string;
  decimals?: number;
  colorize?: boolean;
}) {
  if (value == null) return <span className="text-muted-foreground/40">—</span>;
  const formatted = `${value >= 0 ? "+" : ""}${value.toFixed(decimals)}${suffix}`;
  const color = colorize
    ? value >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-rose-500"
    : "";
  return <span className={`tabular-nums ${color}`}>{formatted}</span>;
}

function RsBadge({ rank }: { rank: number | null }) {
  if (rank == null) return <span className="text-muted-foreground">—</span>;
  const color =
    rank >= 90 ? "bg-emerald-500/20 text-emerald-600 dark:text-emerald-400" :
    rank >= 70 ? "bg-amber-500/20 text-amber-600 dark:text-amber-400" :
    "bg-muted text-muted-foreground";
  return (
    <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium tabular-nums ${color}`}>
      {rank}
    </span>
  );
}

function DataCell({ colKey, value }: { colKey: string; value: unknown }) {
  if (value === undefined || value === null) {
    return <span className="text-muted-foreground/40 text-xs">—</span>;
  }
  if (colKey === "RS_Rank" || colKey === "rs_rank") {
    const n = typeof value === "number" ? value : parseFloat(String(value));
    return <RsBadge rank={Number.isFinite(n) ? n : null} />;
  }
  if (typeof value === "boolean") {
    return (
      <div className="flex justify-center">
        <Check value={value} />
      </div>
    );
  }
  if (typeof value === "number") {
    if (Number.isInteger(value)) {
      return <span className="tabular-nums text-xs">{value}</span>;
    }
    return <span className="tabular-nums text-xs">{value.toFixed(3)}</span>;
  }
  if (typeof value === "string") {
    const t = value.trim();
    if (!t) return <span className="text-muted-foreground/40 text-xs">—</span>;
    return (
      <span
        className="text-xs max-w-[140px] truncate inline-block align-bottom"
        title={t}
      >
        {t}
      </span>
    );
  }
  if (typeof value === "object") {
    let s: string;
    try {
      s = JSON.stringify(value);
    } catch {
      s = "[object]";
    }
    return (
      <span
        className="text-[10px] font-mono text-muted-foreground max-w-[120px] truncate inline-block align-bottom"
        title={s}
      >
        {s.length > 56 ? `${s.slice(0, 56)}…` : s}
      </span>
    );
  }
  return <span className="text-xs">{String(value)}</span>;
}

// ─── filter state (model: screenings-filters-model.ts) ───────────────────────

type Filters = ScreeningsFilters;
const DEFAULT_FILTERS = DEFAULT_SCREENINGS_FILTERS;

/** Sort column: `symbol` or any key present in rowData (discovered per run). */
type SortKey = string;
type SortDir = "asc" | "desc";
type ViewTab = "results" | "quotes" | "charts" | "news" | "sentiment" | "relationship" | "tradeMonitoring";

// ─── FMP Quote types ─────────────────────────────────────────────────────────

interface FmpQuote {
  symbol: string;
  name: string;
  price: number;
  changePercentage: number;
  change: number;
  volume: number;
  dayLow: number;
  dayHigh: number;
  yearHigh: number;
  yearLow: number;
  marketCap: number;
  priceAvg50: number;
  priceAvg200: number;
  exchange: string;
  open: number;
  previousClose: number;
  timestamp: number;
}

// ─── QuotesView ──────────────────────────────────────────────────────────────

type QuoteSortKey = "symbol" | "price" | "changePercentage" | "volume" | "marketCap" |
  "dayLow" | "dayHigh" | "yearLow" | "yearHigh" | "priceAvg50" | "priceAvg200";

function QuotesView({
  symbols,
  selectedTicker,
  onSelect,
  onOpenWorkflowEditor,
}: {
  symbols: string[];
  selectedTicker: string | null;
  onSelect: (ticker: string) => void;
  onOpenWorkflowEditor: (ticker: string) => void;
}) {
  const [quotes, setQuotes] = useState<Record<string, FmpQuote | null>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const QUOTE_SORT_KEYS: QuoteSortKey[] = ["symbol","price","changePercentage","volume","marketCap","dayLow","dayHigh","yearLow","yearHigh","priceAvg50","priceAvg200"];
  const [sortKey, setSortKeyRaw] = useState<QuoteSortKey>(() => {
    try {
      const v = localStorage.getItem("quotes-sort-key") as QuoteSortKey;
      if (QUOTE_SORT_KEYS.includes(v)) return v;
    } catch { /* ignore */ }
    return "symbol";
  });
  const [sortDir, setSortDirRaw] = useState<"asc" | "desc">(() => {
    try {
      const v = localStorage.getItem("quotes-sort-dir");
      if (v === "asc" || v === "desc") return v;
    } catch { /* ignore */ }
    return "asc";
  });

  function setSortKey(k: QuoteSortKey) {
    setSortKeyRaw(k);
    try { localStorage.setItem("quotes-sort-key", k); } catch { /* ignore */ }
  }
  function setSortDir(d: "asc" | "desc") {
    setSortDirRaw(d);
    try { localStorage.setItem("quotes-sort-dir", d); } catch { /* ignore */ }
  }

  useEffect(() => {
    if (symbols.length === 0) return;
    let cancelled = false;

    async function fetchAll() {
      // 1. Populate from IndexedDB immediately
      const cached = await getCachedQuotes<FmpQuote>(symbols);
      if (cancelled) return;
      if (Object.keys(cached).length > 0) setQuotes(cached);

      // 2. Fetch only symbols missing from cache (or stale)
      const missing = symbols.filter(s => !(s in cached));
      if (missing.length === 0) return;

      setLoading(true);
      setError(null);

      const chunks: string[][] = [];
      for (let i = 0; i < missing.length; i += 10) {
        chunks.push(missing.slice(i, i + 10));
      }

      const fresh: Record<string, FmpQuote | null> = {};
      for (const chunk of chunks) {
        await Promise.all(
          chunk.map(async (sym) => {
            try {
              const res = await fmpGetQuote(sym);
              if (!res.ok) { fresh[sym] = null; return; }
              const data = res.data;
              fresh[sym] = Array.isArray(data) ? (data[0] ?? null) : null;
            } catch {
              fresh[sym] = null;
            }
          })
        );
      }

      if (cancelled) return;

      // 3. Merge and update state
      setQuotes(prev => ({ ...prev, ...fresh }));

      // 4. Persist successful fetches to IndexedDB
      const toCache: Record<string, FmpQuote> = {};
      for (const [sym, q] of Object.entries(fresh)) {
        if (q != null) toCache[sym] = q;
      }
      if (Object.keys(toCache).length > 0) setCachedQuotes(toCache);
    }

    fetchAll()
      .catch(() => setError("Failed to load quotes"))
      .finally(() => { if (!cancelled) setLoading(false); });

    return () => { cancelled = true; };
  }, [symbols.join(",")]);

  if (symbols.length === 0) {
    return <p className="text-sm text-muted-foreground py-8 text-center">No stocks to show.</p>;
  }

  function fmtCap(v: number | null): string {
    if (v == null) return "—";
    if (v >= 1e12) return `$${(v / 1e12).toFixed(2)}T`;
    if (v >= 1e9) return `$${(v / 1e9).toFixed(2)}B`;
    if (v >= 1e6) return `$${(v / 1e6).toFixed(2)}M`;
    return `$${v.toLocaleString()}`;
  }

  function fmtVol(v: number | null): string {
    if (v == null) return "—";
    if (v >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
    if (v >= 1e3) return `${(v / 1e3).toFixed(0)}K`;
    return String(v);
  }

  function toggleSort(key: QuoteSortKey) {
    if (sortKey === key) {
      const next = sortDir === "asc" ? "desc" : "asc";
      setSortDir(next);
    } else {
      setSortKey(key);
      setSortDir(key === "symbol" ? "asc" : "desc");
    }
  }

  const sortedSymbols = useMemo(() => {
    return [...symbols].sort((a, b) => {
      const qa = quotes[a];
      const qb = quotes[b];
      if (sortKey === "symbol") {
        return sortDir === "asc" ? a.localeCompare(b) : b.localeCompare(a);
      }
      const va = qa?.[sortKey] ?? -Infinity;
      const vb = qb?.[sortKey] ?? -Infinity;
      return sortDir === "asc" ? Number(va) - Number(vb) : Number(vb) - Number(va);
    });
  }, [symbols, quotes, sortKey, sortDir]);

  function ColHd({ label, col, center }: { label: string; col: QuoteSortKey; center?: boolean }) {
    const active = sortKey === col;
    return (
      <th
        onClick={() => toggleSort(col)}
        className={`px-3 py-2 text-xs font-medium text-muted-foreground uppercase tracking-wide whitespace-nowrap cursor-pointer select-none hover:text-foreground ${center ? "text-center" : "text-left"} ${active ? "text-foreground" : ""}`}
      >
        {label}{active ? (sortDir === "asc" ? " ↑" : " ↓") : ""}
      </th>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {loading && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="w-4 h-4 animate-spin" />
          Loading quotes…
        </div>
      )}
      {error && <p className="text-sm text-rose-500">{error}</p>}
      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full text-sm">
          <thead className="bg-muted/40 border-b border-border">
            <tr>
              <ColHd label="Symbol" col="symbol" />
              <th className="px-3 py-2 text-xs font-medium text-muted-foreground uppercase tracking-wide whitespace-nowrap text-left">Name</th>
              <ColHd label="Price" col="price" />
              <th className="px-3 py-2 text-xs font-medium text-muted-foreground uppercase tracking-wide whitespace-nowrap text-left">Change</th>
              <ColHd label="Change %" col="changePercentage" />
              <th className="px-3 py-2 text-xs font-medium text-muted-foreground uppercase tracking-wide whitespace-nowrap text-left">Open</th>
              <th className="px-3 py-2 text-xs font-medium text-muted-foreground uppercase tracking-wide whitespace-nowrap text-left">Prev Close</th>
              <ColHd label="Day Low" col="dayLow" />
              <ColHd label="Day High" col="dayHigh" />
              <ColHd label="52w Low" col="yearLow" />
              <ColHd label="52w High" col="yearHigh" />
              <ColHd label="Avg50" col="priceAvg50" />
              <ColHd label="Avg200" col="priceAvg200" />
              <ColHd label="Volume" col="volume" />
              <ColHd label="Mkt Cap" col="marketCap" />
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {sortedSymbols.map(sym => {
              const q = quotes[sym];
              const isLoading = loading && q === undefined;
              const chgColor = q ? (q.changePercentage >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-rose-500") : "";
              const isSelected = sym === selectedTicker;
              return (
                <tr
                  key={sym}
                  onClick={() => onSelect(sym)}
                  onDoubleClick={() => onOpenWorkflowEditor(sym)}
                  className={`cursor-pointer transition-colors ${isSelected ? "bg-foreground/10 ring-1 ring-inset ring-foreground/20" : "hover:bg-muted/30"}`}
                >
                  <td className="px-3 py-2 font-mono font-semibold whitespace-nowrap">{sym}</td>
                  <td className="px-3 py-2 text-xs text-muted-foreground max-w-[160px] truncate whitespace-nowrap" title={q?.name}>{isLoading ? "…" : (q?.name ?? "—")}</td>
                  <td className="px-3 py-2 tabular-nums font-medium">{q ? `$${q.price.toFixed(2)}` : (isLoading ? "…" : "—")}</td>
                  <td className={`px-3 py-2 tabular-nums ${chgColor}`}>{q ? (q.change >= 0 ? "+" : "") + q.change.toFixed(2) : "—"}</td>
                  <td className={`px-3 py-2 tabular-nums font-medium ${chgColor}`}>{q ? (q.changePercentage >= 0 ? "+" : "") + q.changePercentage.toFixed(2) + "%" : "—"}</td>
                  <td className="px-3 py-2 tabular-nums">{q ? `$${q.open.toFixed(2)}` : "—"}</td>
                  <td className="px-3 py-2 tabular-nums">{q ? `$${q.previousClose.toFixed(2)}` : "—"}</td>
                  <td className="px-3 py-2 tabular-nums">{q ? `$${q.dayLow.toFixed(2)}` : "—"}</td>
                  <td className="px-3 py-2 tabular-nums">{q ? `$${q.dayHigh.toFixed(2)}` : "—"}</td>
                  <td className="px-3 py-2 tabular-nums text-muted-foreground">{q ? `$${q.yearLow.toFixed(2)}` : "—"}</td>
                  <td className="px-3 py-2 tabular-nums text-muted-foreground">{q ? `$${q.yearHigh.toFixed(2)}` : "—"}</td>
                  <td className="px-3 py-2 tabular-nums text-muted-foreground">{q ? `$${q.priceAvg50.toFixed(2)}` : "—"}</td>
                  <td className="px-3 py-2 tabular-nums text-muted-foreground">{q ? `$${q.priceAvg200.toFixed(2)}` : "—"}</td>
                  <td className="px-3 py-2 tabular-nums">{q ? fmtVol(q.volume) : "—"}</td>
                  <td className="px-3 py-2 tabular-nums">{q ? fmtCap(q.marketCap) : "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─── OHLC types ──────────────────────────────────────────────────────────────

interface OhlcBar {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}



// ─── Candlestick chart using pure SVG ────────────────────────────────────────
// (recharts doesn't support true candlestick natively; we build a lightweight SVG chart)

interface Crosshair {
  barIdx: number;
  svgY: number;
  pinned: boolean;
}

interface SelectionBox {
  startX: number;
  startY: number;
  endX: number;
  endY: number;
  locked: boolean;
}

interface ChartPoint {
  barIdx: number;
  date: string;
  price: number;
  open: number;
  high: number;
  low: number;
  close: number;
}

/** Single saved pivot: dot at bar + horizontal ray to the right (price pane only). */
export type PivotMarker = { barIdx: number; date: string; price: number };

function resolvePivotBarIndex(data: OhlcBar[], pivot: { barIdx: number; date: string }): number {
  const byDate = data.findIndex(d => d.date === pivot.date);
  if (byDate >= 0) return byDate;
  return Math.max(0, Math.min(data.length - 1, pivot.barIdx));
}

function pivotFromMetadata(meta: Record<string, unknown> | undefined): PivotMarker | null {
  if (!meta) return null;
  const single = meta.pivot;
  if (
    single &&
    typeof single === "object" &&
    typeof (single as { barIdx?: unknown }).barIdx === "number" &&
    typeof (single as { date?: unknown }).date === "string" &&
    typeof (single as { price?: unknown }).price === "number"
  ) {
    return {
      barIdx: (single as { barIdx: number }).barIdx,
      date: (single as { date: string }).date,
      price: (single as { price: number }).price,
    };
  }
  const raw = meta.pivot_points;
  if (Array.isArray(raw) && raw.length > 0) {
    const first = raw[0];
    if (
      first &&
      typeof first === "object" &&
      typeof (first as { date?: unknown }).date === "string" &&
      typeof (first as { price?: unknown }).price === "number"
    ) {
      const barIdx =
        typeof (first as { barIdx?: unknown }).barIdx === "number"
          ? (first as { barIdx: number }).barIdx
          : 0;
      return {
        barIdx,
        date: (first as { date: string }).date,
        price: (first as { price: number }).price,
      };
    }
  }
  return null;
}

function CandlestickSvg({
  symbol,
  onPointChange,
  pivotMarker,
  onChartMetrics,
  onChartData,
  onAutoPivot,
}: {
  symbol: string;
  onPointChange?: (point: ChartPoint | null) => void;
  pivotMarker?: PivotMarker | null;
  /** Latest bar close for header pivot distance when crosshair is inactive */
  onChartMetrics?: (m: { lastClose: number } | null) => void;
  onChartData?: (rows: OhlcBar[]) => void;
  onAutoPivot?: (point: ChartPoint) => void;
}) {
  const [data, setData] = useState<OhlcBar[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [crosshair, setCrosshair] = useState<Crosshair | null>(null);
  const [selBox, setSelBox] = useState<SelectionBox | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const lastPointKeyRef = useRef<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    setData([]);
    fmpGetOhlc(symbol)
      .then((r) => {
        if (!r.ok) {
          setError("Failed to load chart data");
          return;
        }
        setData(r.data);
      })
      .catch(() => setError("Failed to load chart data"))
      .finally(() => setLoading(false));
  }, [symbol]);

  useEffect(() => {
    if (!onChartMetrics) return;
    if (data.length === 0) {
      onChartMetrics(null);
      return;
    }
    onChartMetrics({ lastClose: data[data.length - 1]!.close });
  }, [data, onChartMetrics]);

  useEffect(() => {
    onChartData?.(data);
  }, [data, onChartData]);

  const W = 900;
  const H_PRICE = 340;
  const H_VOL = 80;
  const H = H_PRICE + H_VOL + 16;
  const PAD_L = 60;
  const PAD_R = 12;
  const PAD_T = 12;
  const PAD_B = 24;

  const chartW = W - PAD_L - PAD_R;
  const chartH = H_PRICE - PAD_T - PAD_B;

  const priceMin = useMemo(() => data.length ? Math.min(...data.map(d => d.low)) * 0.99 : 0, [data]);
  const priceMax = useMemo(() => data.length ? Math.max(...data.map(d => d.high)) * 1.01 : 1, [data]);
  const volMax = useMemo(() => data.length ? Math.max(...data.map(d => d.volume)) : 1, [data]);

  const toY = useCallback((p: number) => {
    return PAD_T + chartH - ((p - priceMin) / (priceMax - priceMin)) * chartH;
  }, [priceMin, priceMax, chartH]);

  const toVolY = useCallback((v: number) => {
    const volH = H_VOL - 8;
    return H_PRICE + 16 + volH - (v / volMax) * volH;
  }, [volMax]);

  const barW = Math.max(1, Math.min(12, chartW / (data.length || 1) - 1));
  const barStep = data.length > 1 ? chartW / data.length : chartW;

  function xOf(i: number) {
    return PAD_L + i * barStep + barStep / 2;
  }

  // SMAs
  const sma = useCallback((period: number) => {
    return data.map((_, i) => {
      if (i < period - 1) return null;
      const slice = data.slice(i - period + 1, i + 1);
      return slice.reduce((s, d) => s + d.close, 0) / period;
    });
  }, [data]);

  const sma10 = useMemo(() => sma(10), [sma]);
  const sma21 = useMemo(() => sma(21), [sma]);
  const sma50 = useMemo(() => sma(50), [sma]);
  const sma200 = useMemo(() => sma(200), [sma]);

  // Y-axis ticks
  const yTicks = useMemo(() => {
    const range = priceMax - priceMin;
    const step = Math.pow(10, Math.floor(Math.log10(range))) / 2;
    const ticks: number[] = [];
    const start = Math.ceil(priceMin / step) * step;
    for (let t = start; t <= priceMax; t += step) {
      ticks.push(Math.round(t * 100) / 100);
    }
    return ticks;
  }, [priceMin, priceMax]);

  // X-axis ticks
  const xTickIndices = useMemo(() => {
    if (data.length === 0) return [];
    const step = Math.ceil(data.length / 8);
    const idx: number[] = [];
    for (let i = 0; i < data.length; i += step) idx.push(i);
    return idx;
  }, [data]);

  const toPrice = useCallback((svgY: number): number => {
    return priceMin + (1 - (svgY - PAD_T) / chartH) * (priceMax - priceMin);
  }, [priceMin, chartH, priceMax, PAD_T]);

  function svgCoordsFromEvent(e: React.MouseEvent<SVGSVGElement>) {
    const svg = svgRef.current;
    if (!svg || data.length === 0) return null;
    const rect = svg.getBoundingClientRect();
    const scaleX = W / rect.width;
    const scaleY = H / rect.height;
    const svgX = (e.clientX - rect.left) * scaleX;
    const svgY = (e.clientY - rect.top) * scaleY;
    const rawIdx = (svgX - PAD_L - barStep / 2) / barStep;
    const barIdx = Math.max(0, Math.min(data.length - 1, Math.round(rawIdx)));
    return { barIdx, svgX, svgY };
  }

  function handleMouseMove(e: React.MouseEvent<SVGSVGElement>) {
    const coords = svgCoordsFromEvent(e);
    if (!coords) return;
    setCrosshair(prev => ({ barIdx: coords.barIdx, svgY: coords.svgY, pinned: prev?.pinned ?? false }));
    // Drag end corner of selection box to cursor position
    setSelBox(prev => prev && !prev.locked ? { ...prev, endX: coords.svgX, endY: coords.svgY } : prev);
  }

  function handleClick(e: React.MouseEvent<SVGSVGElement>) {
    const coords = svgCoordsFromEvent(e);
    if (!coords) return;
    if (e.shiftKey) {
      // Shift+click: start new box at cursor (or clear locked one)
      setSelBox(prev =>
        prev && prev.locked
          ? null
          : { startX: coords.svgX, startY: coords.svgY, endX: coords.svgX, endY: coords.svgY, locked: false }
      );
    } else if (selBox && !selBox.locked) {
      // Plain click while drawing: lock at current cursor
      setSelBox({ ...selBox, endX: coords.svgX, endY: coords.svgY, locked: true });
    } else if (selBox && selBox.locked) {
      // Click outside the locked box: clear it
      const x1 = Math.min(selBox.startX, selBox.endX);
      const x2 = Math.max(selBox.startX, selBox.endX);
      const y1 = Math.min(selBox.startY, selBox.endY);
      const y2 = Math.max(selBox.startY, selBox.endY);
      const inside = coords.svgX >= x1 && coords.svgX <= x2 && coords.svgY >= y1 && coords.svgY <= y2;
      if (!inside) setSelBox(null);
    }
  }

  function handleDoubleClick(e: React.MouseEvent<SVGSVGElement>) {
    const coords = svgCoordsFromEvent(e);
    if (!coords) return;
    setCrosshair(prev => ({ ...coords, pinned: !(prev?.pinned) }));
  }

  useEffect(() => {
    if (!onPointChange) return;
    if (!crosshair) {
      lastPointKeyRef.current = null;
      onPointChange(null);
      return;
    }
    const bar = data[crosshair.barIdx];
    if (!bar) {
      onPointChange(null);
      return;
    }
    const lineY = Math.max(PAD_T, Math.min(H_PRICE - PAD_B, crosshair.svgY));
    const nextPoint: ChartPoint = {
      barIdx: crosshair.barIdx,
      date: bar.date,
      price: toPrice(lineY),
      open: bar.open,
      high: bar.high,
      low: bar.low,
      close: bar.close,
    };
    const pointKey = `${nextPoint.barIdx}:${nextPoint.date}:${nextPoint.price.toFixed(4)}`;
    if (lastPointKeyRef.current === pointKey) return;
    lastPointKeyRef.current = pointKey;
    onPointChange(nextPoint);
  }, [crosshair, data, onPointChange, PAD_T, H_PRICE, PAD_B, toPrice]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64 gap-2 text-muted-foreground">
        <Loader2 className="w-5 h-5 animate-spin" />
        <span className="text-sm">Loading {symbol}…</span>
      </div>
    );
  }
  if (error) return <p className="text-sm text-rose-500 text-center py-8">{error}</p>;
  if (data.length === 0) return <p className="text-sm text-muted-foreground text-center py-8">No chart data.</p>;

  return (
    <div className="relative w-full">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${W} ${H}`}
        width="100%"
        className="block cursor-crosshair select-none"
        onMouseMove={handleMouseMove}
        onClick={handleClick}
        onDoubleClick={handleDoubleClick}
        onMouseDown={e => e.preventDefault()}
        onMouseLeave={() => setCrosshair(prev => prev?.pinned ? prev : null)}
      >
        {/* Grid */}
        {yTicks.map(t => (
          <line
            key={t}
            x1={PAD_L} x2={W - PAD_R}
            y1={toY(t)} y2={toY(t)}
            stroke="hsl(var(--border))"
            strokeWidth={0.5}
          />
        ))}

        {/* Y-axis labels */}
        {yTicks.map(t => (
          <text
            key={`yl-${t}`}
            x={PAD_L - 6}
            y={toY(t) + 4}
            textAnchor="end"
            fontSize={10}
            fill="hsl(var(--muted-foreground))"
          >
            ${t.toFixed(t >= 100 ? 0 : 2)}
          </text>
        ))}

        {/* SMAs */}
        {([
          { values: sma10,  color: "#10b981", key: "10"  },
          { values: sma21,  color: "#f97316", key: "21"  },
          { values: sma50,  color: "#ef4444", key: "50"  },
          { values: sma200, color: "#6366f1", key: "200" },
        ] as const).map(({ values, color, key }) =>
          values.map((v, i) => {
            if (v == null || values[i - 1] == null) return null;
            return (
              <line
                key={`s${key}-${i}`}
                x1={xOf(i - 1)} y1={toY(values[i - 1]!)}
                x2={xOf(i)} y2={toY(v)}
                stroke={color}
                strokeWidth={1.5}
                opacity={0.85}
              />
            );
          })
        )}

        {/* Candles */}
        {data.map((bar, i) => {
          const cx = xOf(i);
          const up = bar.close >= bar.open;
          const color = up ? "#10b981" : "#ef4444";
          const bodyTop = toY(Math.max(bar.open, bar.close));
          const bodyBot = toY(Math.min(bar.open, bar.close));
          const bodyH = Math.max(bodyBot - bodyTop, 1);

          return (
            <g key={i}>
              {/* Wick */}
              <line
                x1={cx} x2={cx}
                y1={toY(bar.high)} y2={toY(bar.low)}
                stroke={color}
                strokeWidth={1}
                opacity={0.7}
              />
              {/* Body */}
              <rect
                x={cx - barW / 2}
                y={bodyTop}
                width={barW}
                height={bodyH}
                fill={color}
                opacity={0.85}
              />
            </g>
          );
        })}

        {/* Pivot marker: dot at bar + horizontal line to the right edge of the price pane */}
        {pivotMarker && (() => {
          const pbi = resolvePivotBarIndex(data, pivotMarker);
          const px = xOf(pbi);
          const py = toY(pivotMarker.price);
          const inPane = py >= PAD_T && py <= H_PRICE - PAD_B;
          if (!inPane) return null;
          return (
            <g pointerEvents="none">
              <line
                x1={px}
                y1={py}
                x2={W - PAD_R}
                y2={py}
                stroke="#f59e0b"
                strokeWidth={1.5}
                strokeDasharray="5 3"
                opacity={0.95}
              />
              <circle
                cx={px}
                cy={py}
                r={4}
                fill="#f59e0b"
                stroke="hsl(var(--background))"
                strokeWidth={1.5}
              />
            </g>
          );
        })()}

        {/* X-axis labels */}
        {xTickIndices.map(i => (
          <text
            key={`xl-${i}`}
            x={xOf(i)}
            y={H_PRICE - PAD_B + 14}
            textAnchor="middle"
            fontSize={10}
            fill="hsl(var(--muted-foreground))"
          >
            {data[i]?.date?.slice(5)} {/* MM-DD */}
          </text>
        ))}

        {/* Divider */}
        <line
          x1={PAD_L} x2={W - PAD_R}
          y1={H_PRICE + 8} y2={H_PRICE + 8}
          stroke="hsl(var(--border))"
          strokeWidth={1}
        />

        {/* Volume bars */}
        {data.map((bar, i) => {
          const cx = xOf(i);
          const up = bar.close >= bar.open;
          const color = up ? "#10b981" : "#ef4444";
          const volY = toVolY(bar.volume);
          const volH = H_PRICE + 16 + (H_VOL - 8) - volY;
          return (
            <rect
              key={`v-${i}`}
              x={cx - barW / 2}
              y={volY}
              width={barW}
              height={Math.max(volH, 1)}
              fill={color}
              opacity={0.35}
            />
          );
        })}

        {/* Legend */}
        {[
          { color: "#10b981", label: "SMA 10"  },
          { color: "#f97316", label: "SMA 21"  },
          { color: "#ef4444", label: "SMA 50"  },
          { color: "#6366f1", label: "SMA 200" },
        ].map(({ color, label }, i) => (
          <g key={label}>
            <circle cx={PAD_L + 8 + i * 58} cy={PAD_T + 6} r={4} fill={color} opacity={0.85} />
            <text x={PAD_L + 16 + i * 58} y={PAD_T + 10} fontSize={10} fill="hsl(var(--muted-foreground))">{label}</text>
          </g>
        ))}

        {/* Selection box */}
        {selBox && (() => {
          // Box corners follow cursor exactly
          const x1 = Math.min(selBox.startX, selBox.endX);
          const x2 = Math.max(selBox.startX, selBox.endX);
          const y1 = Math.min(selBox.startY, selBox.endY);
          const y2 = Math.max(selBox.startY, selBox.endY);

          // Derive bar indices from x positions for stats only
          const toIdx = (x: number) =>
            Math.max(0, Math.min(data.length - 1, Math.round((x - PAD_L - barStep / 2) / barStep)));
          const minIdx = toIdx(x1);
          const maxIdx = toIdx(x2);
          const barsInRange = data.slice(minIdx, maxIdx + 1);
          if (barsInRange.length === 0) return null;

          const startBar = data[minIdx];
          const endBar   = data[maxIdx];
          const priceChange = endBar.close - startBar.open;
          const pctChange   = (priceChange / startBar.open) * 100;
          const barCount    = maxIdx - minIdx + 1;
          const totalVol    = barsInRange.reduce((s, b) => s + b.volume, 0);
          const calDays     = Math.round(
            (new Date(endBar.date).getTime() - new Date(startBar.date).getTime()) / 86400000
          );

          const up = priceChange >= 0;
          const boxColor = up ? "rgba(16,185,129,0.12)" : "rgba(239,68,68,0.12)";
          const borderColor = up ? "#10b981" : "#ef4444";

          const fmtVol = (v: number) =>
            v >= 1e9 ? `${(v / 1e9).toFixed(2)}B`
            : v >= 1e6 ? `${(v / 1e6).toFixed(2)}M`
            : v >= 1e3 ? `${(v / 1e3).toFixed(1)}K`
            : String(v);

          // Stats label — bottom-right of box, flip left if near edge
          const labelW = 180;
          const labelH = 56;
          const labelX = x2 + 8 + labelW > W - PAD_R ? x2 - labelW - 8 : x2 + 8;
          const labelY = Math.min(y2 + 8, H - labelH - 8);

          return (
            <g pointerEvents="none">
              {/* Fill */}
              <rect x={x1} y={y1} width={x2 - x1} height={y2 - y1} fill={boxColor} />
              {/* Dotted border */}
              <rect
                x={x1} y={y1} width={x2 - x1} height={y2 - y1}
                fill="none"
                stroke={borderColor}
                strokeWidth={1}
                strokeDasharray="5 3"
                opacity={0.8}
              />

              {/* Stats label */}
              <rect x={labelX} y={labelY} width={labelW} height={labelH} rx={5}
                fill={up ? "rgba(16,185,129,0.18)" : "rgba(239,68,68,0.18)"}
                stroke={borderColor} strokeWidth={1}
              />
              {/* Line 1: price change + % */}
              <text
                x={labelX + labelW / 2} y={labelY + 18}
                textAnchor="middle" fontSize={12} fontWeight="bold"
                fill={borderColor}
              >
                {priceChange >= 0 ? "+" : ""}{priceChange.toFixed(2)} ({pctChange >= 0 ? "+" : ""}{pctChange.toFixed(2)}%)
              </text>
              {/* Line 2: bars + days */}
              <text
                x={labelX + labelW / 2} y={labelY + 34}
                textAnchor="middle" fontSize={11}
                fill="hsl(var(--foreground))"
              >
                {barCount} bar{barCount !== 1 ? "s" : ""}, {calDays}d
              </text>
              {/* Line 3: volume */}
              <text
                x={labelX + labelW / 2} y={labelY + 50}
                textAnchor="middle" fontSize={11}
                fill="hsl(var(--muted-foreground))"
              >
                Vol {fmtVol(totalVol)}
              </text>
            </g>
          );
        })()}

        {/* Crosshair */}
        {crosshair && (() => {
          const { barIdx, svgY, pinned } = crosshair;
          const bar = data[barIdx];
          if (!bar) return null;

          const cx = xOf(barIdx);
          // Clamp horizontal line to price area
          const lineY = Math.max(PAD_T, Math.min(H_PRICE - PAD_B, svgY));
          const price = toPrice(lineY);
          const chg = bar.close - bar.open;
          const chgPct = (chg / bar.open) * 100;
          const up = chg >= 0;

          // Info panel: flip left if near right edge
          const panelW = 152;
          const panelH = 110;
          const panelX = cx + 12 + panelW > W - PAD_R ? cx - panelW - 12 : cx + 12;
          const panelY = Math.max(PAD_T, Math.min(H_PRICE - panelH - 8, lineY - panelH / 2));

          // Date label: flip left if near right edge
          const dateLabelW = 52;
          const dateLabelX = Math.max(PAD_L, Math.min(W - PAD_R - dateLabelW, cx - dateLabelW / 2));

          // Price label on Y-axis
          const priceLabelY = Math.max(PAD_T + 6, Math.min(H_PRICE - PAD_B, lineY));

          const priceStr = `$${price.toFixed(price >= 100 ? 2 : 2)}`;

          return (
            <g pointerEvents="none">
              {/* Vertical dotted line — full chart height */}
              <line
                x1={cx} x2={cx}
                y1={PAD_T} y2={H - PAD_B}
                stroke="hsl(var(--muted-foreground))"
                strokeWidth={1}
                strokeDasharray="4 3"
                opacity={0.7}
              />
              {/* Horizontal dotted line — price area only */}
              <line
                x1={PAD_L} x2={W - PAD_R}
                y1={lineY} y2={lineY}
                stroke="hsl(var(--muted-foreground))"
                strokeWidth={1}
                strokeDasharray="4 3"
                opacity={0.7}
              />

              {/* Date label on X-axis */}
              <rect
                x={dateLabelX} y={H_PRICE - PAD_B + 2}
                width={dateLabelW} height={16}
                rx={3}
                fill="hsl(var(--foreground))"
              />
              <text
                x={dateLabelX + dateLabelW / 2}
                y={H_PRICE - PAD_B + 13}
                textAnchor="middle"
                fontSize={10}
                fill="hsl(var(--background))"
                fontWeight="500"
              >
                {bar.date.slice(5)}
              </text>

              {/* Price label on Y-axis */}
              <rect
                x={0} y={priceLabelY - 7}
                width={PAD_L - 2} height={14}
                rx={3}
                fill="hsl(var(--foreground))"
              />
              <text
                x={PAD_L - 6}
                y={priceLabelY + 4}
                textAnchor="end"
                fontSize={10}
                fill="hsl(var(--background))"
                fontWeight="500"
              >
                {priceStr}
              </text>

              {/* Info panel — shown only when pinned (double-click) */}
              {pinned && <>
                <rect
                  x={panelX} y={panelY}
                  width={panelW} height={panelH}
                  rx={6}
                  fill="hsl(var(--background))"
                  stroke="hsl(var(--border))"
                  strokeWidth={1}
                />
                <text x={panelX + 10} y={panelY + 16} fontSize={11} fontWeight="bold" fill="hsl(var(--foreground))">{bar.date}</text>
                {[
                  ["O", `$${bar.open.toFixed(2)}`, "hsl(var(--foreground))"],
                  ["H", `$${bar.high.toFixed(2)}`, "hsl(var(--foreground))"],
                  ["L", `$${bar.low.toFixed(2)}`, "hsl(var(--foreground))"],
                  ["C", `$${bar.close.toFixed(2)}`, up ? "#10b981" : "#ef4444"],
                  ["Chg", `${chg >= 0 ? "+" : ""}${chg.toFixed(2)} (${chgPct >= 0 ? "+" : ""}${chgPct.toFixed(2)}%)`, up ? "#10b981" : "#ef4444"],
                ].map(([label, val, color], row) => (
                  <g key={label}>
                    <text x={panelX + 10} y={panelY + 32 + row * 16} fontSize={10} fill="hsl(var(--muted-foreground))">{label}</text>
                    <text x={panelX + panelW - 8} y={panelY + 32 + row * 16} fontSize={10} textAnchor="end" fill={color}>{val}</text>
                  </g>
                ))}
              </>}
            </g>
          );
        })()}
      </svg>

      {/* Selection-box toolbar — appears when box is locked */}
      {selBox?.locked && (() => {
        const toIdx = (x: number) =>
          Math.max(0, Math.min(data.length - 1, Math.round((x - PAD_L - barStep / 2) / barStep)));
        const x1 = Math.min(selBox.startX, selBox.endX);
        const x2 = Math.max(selBox.startX, selBox.endX);
        const y1 = Math.min(selBox.startY, selBox.endY);
        const y2 = Math.max(selBox.startY, selBox.endY);
        const minIdx = toIdx(x1);
        const maxIdx = toIdx(x2);

        // Position centered on box, above top edge; flip below if too close to top
        const cx = (x1 + x2) / 2;
        const leftPct = (cx / W) * 100;
        const showBelow = y1 / H < 0.12;
        const anchorPct = ((showBelow ? y2 : y1) / H) * 100;

        function autoFindPivot() {
          if (!onAutoPivot) return;
          let bestIdx = minIdx;
          for (let i = minIdx + 1; i <= maxIdx; i++) {
            if ((data[i]?.high ?? 0) > (data[bestIdx]?.high ?? 0)) bestIdx = i;
          }
          const bar = data[bestIdx];
          if (!bar) return;
          onAutoPivot({
            barIdx: bestIdx,
            date: bar.date,
            price: bar.high,
            open: bar.open,
            high: bar.high,
            low: bar.low,
            close: bar.close,
          });
          setSelBox(null);
        }

        return (
          <div
            className="absolute z-10 flex items-center bg-background border border-border rounded-md shadow-lg overflow-hidden"
            style={{
              left: `${leftPct}%`,
              top: `${anchorPct}%`,
              transform: `translate(-50%, ${showBelow ? "4px" : "calc(-100% - 4px)"})`,
              pointerEvents: "auto",
            }}
          >
            <span className="px-2 text-[10px] font-medium text-muted-foreground uppercase tracking-wide border-r border-border py-1.5">
              Selection
            </span>
            {onAutoPivot && (
              <button
                type="button"
                onClick={autoFindPivot}
                className="px-3 py-1.5 text-xs font-medium hover:bg-muted transition-colors whitespace-nowrap"
              >
                Auto find pivot
              </button>
            )}
          </div>
        );
      })()}
    </div>
  );
}

// Replace OhlcChart with CandlestickSvg in ChartsView
function ChartsViewFinal({
  symbols,
  selectedTicker,
  onSelect,
  dismissed,
  onDismiss,
  onRestore,
  getStatus,
  onSetStatus,
  hasComment,
  onEditComment,
  getTickerMeta,
  getPivotMarker,
  onSetPivotMarker,
  onClearPivotMarker,
}: {
  symbols: string[];
  selectedTicker: string | null;
  onSelect: (ticker: string) => void;
  dismissed: Set<string>;
  onDismiss: (ticker: string) => void;
  onRestore: (ticker: string) => void;
  getStatus: (ticker: string) => NoteStatus;
  onSetStatus: (ticker: string, status: NoteStatus) => void;
  hasComment: (ticker: string) => boolean;
  onEditComment: (ticker: string) => void;
  getTickerMeta: (ticker: string) => { sector: string; industry: string };
  getPivotMarker: (ticker: string) => PivotMarker | null;
  onSetPivotMarker: (ticker: string, point: ChartPoint) => void;
  onClearPivotMarker: (ticker: string) => void;
}) {
  const idx = useMemo(() => {
    const i = selectedTicker ? symbols.indexOf(selectedTicker) : -1;
    return i >= 0 ? i : 0;
  }, [symbols, selectedTicker]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "ArrowLeft") onSelect(symbols[Math.max(0, idx - 1)]);
      if (e.key === "ArrowRight") onSelect(symbols[Math.min(symbols.length - 1, idx + 1)]);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [idx, symbols, onSelect]);

  if (symbols.length === 0) {
    return <p className="text-sm text-muted-foreground py-8 text-center">No stocks to show.</p>;
  }

  const symbol = symbols[idx];
  const meta = getTickerMeta(symbol);
  const status = getStatus(symbol);
  const commentExists = hasComment(symbol);
  const pivotMarker = getPivotMarker(symbol);
  const [activePoint, setActivePoint] = useState<ChartPoint | null>(null);
  const activePointRef = useRef<ChartPoint | null>(null);
  activePointRef.current = activePoint;
  const [pivotMenu, setPivotMenu] = useState<{ x: number; y: number; pointSnapshot: ChartPoint | null } | null>(null);
  const pivotMenuRef = useRef<HTMLDivElement>(null);
  const [chartLastClose, setChartLastClose] = useState<number | null>(null);
  const [chartData, setChartData] = useState<OhlcBar[]>([]);
  const [copyState, setCopyState] = useState<"idle" | "ok" | "err">("idle");

  const onChartMetrics = useCallback((m: { lastClose: number } | null) => {
    setChartLastClose(m?.lastClose ?? null);
  }, []);
  const onChartData = useCallback((rows: OhlcBar[]) => {
    setChartData(rows);
  }, []);

  useEffect(() => {
    setChartLastClose(null);
    setChartData([]);
    setCopyState("idle");
  }, [symbol]);

  const pivotVsHeader = useMemo(() => {
    if (!pivotMarker) return null;
    const refPrice = activePoint?.price ?? chartLastClose;
    if (refPrice == null) return null;
    const pivot = pivotMarker.price;
    const d = refPrice - pivot;
    const dp = Math.abs(pivot) > 1e-9 ? (d / pivot) * 100 : 0;
    const source = activePoint ? "Crosshair" : "Last close";
    return { source, d, dp };
  }, [pivotMarker, activePoint, chartLastClose]);

  async function copyOhlcvToClipboard() {
    if (chartData.length === 0) return;
    const header = "date,open,high,low,close,volume";
    const lines = chartData.map(
      d => `${d.date},${d.open},${d.high},${d.low},${d.close},${d.volume}`
    );
    const text = [header, ...lines].join("\n");
    try {
      await navigator.clipboard.writeText(text);
      setCopyState("ok");
    } catch {
      setCopyState("err");
    }
    window.setTimeout(() => setCopyState("idle"), 1800);
  }

  useEffect(() => {
    if (!pivotMenu) return;
    function onPointerDown(e: PointerEvent) {
      if (pivotMenuRef.current?.contains(e.target as Node)) return;
      setPivotMenu(null);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setPivotMenu(null);
    }
    document.addEventListener("pointerdown", onPointerDown, true);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown, true);
      document.removeEventListener("keydown", onKey);
    };
  }, [pivotMenu]);

  return (
    <div className="flex flex-col gap-4">
      {/* Nav bar */}
      <div className="flex items-center gap-3">
        <button
          onClick={() => onSelect(symbols[Math.max(0, idx - 1)])}
          disabled={idx === 0}
          className="p-1.5 rounded-md border border-border hover:bg-muted disabled:opacity-30 transition-colors"
          title="Previous (←)"
        >
          <ChevronLeft className="w-4 h-4" />
        </button>

        <span className="font-mono font-bold text-lg">{symbol}</span>
        {(meta.sector || meta.industry) && (
          <span
            className="text-xs text-muted-foreground max-w-[260px] truncate"
            title={[meta.sector, meta.industry].filter(Boolean).join(" · ")}
          >
            {[meta.sector, meta.industry].filter(Boolean).join(" · ")}
          </span>
        )}
        <span className="text-sm text-muted-foreground">{idx + 1} / {symbols.length}</span>

        {dismissed.has(symbol) ? (
          <button
            onClick={() => onRestore(symbol)}
            title="Restore"
            className="flex items-center gap-1.5 text-xs px-2 py-1 rounded border border-border text-emerald-500 hover:bg-muted transition-colors"
          >
            <RotateCcw className="w-3.5 h-3.5" /> Restore
          </button>
        ) : (
          <button
            onClick={() => onDismiss(symbol)}
            title="Dismiss"
            className="flex items-center gap-1.5 text-xs px-2 py-1 rounded border border-border text-muted-foreground hover:text-rose-500 hover:border-rose-400 transition-colors"
          >
            <Trash2 className="w-3.5 h-3.5" /> Dismiss
          </button>
        )}

        <select
          value={status}
          onChange={e => onSetStatus(symbol, e.target.value as NoteStatus)}
          className="px-2 py-1 text-xs rounded border border-input bg-background focus:outline-none focus:ring-1 focus:ring-ring"
          title="Status"
        >
          <option value="active">Active</option>
          <option value="dismissed">Dismissed</option>
          <option value="watchlist">Watchlist</option>
          <option value="pipeline">Pipeline</option>
        </select>

        <button
          onClick={() => onEditComment(symbol)}
          title={commentExists ? "Edit note" : "Add note"}
          className={`flex items-center gap-1.5 text-xs px-2 py-1 rounded border border-border transition-colors ${commentExists ? "text-sky-500 hover:bg-muted" : "text-muted-foreground hover:text-sky-500 hover:border-sky-400"}`}
        >
          <MessageSquare className="w-3.5 h-3.5" /> {commentExists ? "Edit note" : "Add note"}
        </button>

        {pivotVsHeader && pivotMarker && (
          <div
            className="flex flex-col items-end gap-0.5 text-right shrink-0 min-w-0"
            title={`Pivot $${pivotMarker.price.toFixed(2)} · ${pivotVsHeader.source} vs pivot`}
          >
            <span className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">vs pivot</span>
            <span
              className={`text-xs font-semibold tabular-nums whitespace-nowrap ${pivotVsHeader.d >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-rose-500"}`}
            >
              {pivotVsHeader.source}: {pivotVsHeader.d >= 0 ? "+" : ""}
              {pivotVsHeader.d.toFixed(2)} ({pivotVsHeader.d >= 0 ? "+" : ""}
              {pivotVsHeader.dp.toFixed(2)}%)
            </span>
          </div>
        )}

        <button
          type="button"
          onClick={() => void copyOhlcvToClipboard()}
          disabled={chartData.length === 0}
          title="Copy date/open/high/low/close/volume as CSV"
          className={`flex items-center gap-1.5 text-xs px-2 py-1 rounded border transition-colors ${
            chartData.length === 0
              ? "border-border text-muted-foreground/60 cursor-not-allowed"
              : copyState === "ok"
                ? "border-emerald-500/50 text-emerald-600 dark:text-emerald-400"
                : copyState === "err"
                  ? "border-rose-400 text-rose-500"
                  : "border-border text-muted-foreground hover:text-foreground hover:border-foreground/40"
          }`}
        >
          <Copy className="w-3.5 h-3.5" />
          {copyState === "ok" ? "Copied" : copyState === "err" ? "Copy failed" : "Copy OHLCV"}
        </button>

        <select
          value={symbol}
          onChange={e => onSelect(e.target.value)}
          className="ml-auto px-2 py-1 text-sm rounded border border-input bg-background focus:outline-none focus:ring-1 focus:ring-ring"
        >
          {symbols.map((s, i) => (
            <option key={s} value={s}>{i + 1}. {s}</option>
          ))}
        </select>

        <button
          onClick={() => onSelect(symbols[Math.min(symbols.length - 1, idx + 1)])}
          disabled={idx === symbols.length - 1}
          className="p-1.5 rounded-md border border-border hover:bg-muted disabled:opacity-30 transition-colors"
          title="Next (→)"
        >
          <ChevronRight className="w-4 h-4" />
        </button>
      </div>

      {/* Chart — right-click for pivot menu */}
      <div
        className="relative border border-border rounded-lg p-4 bg-background"
        title="Right-click chart for pivot options"
        onContextMenu={e => {
          e.preventDefault();
          // Snapshot crosshair at open — leaving the SVG clears activePoint but menu must stay usable
          setPivotMenu({
            x: e.clientX,
            y: e.clientY,
            pointSnapshot: activePointRef.current,
          });
        }}
      >
        <CandlestickSvg
          key={symbol}
          symbol={symbol}
          onPointChange={setActivePoint}
          pivotMarker={pivotMarker}
          onChartMetrics={onChartMetrics}
          onChartData={onChartData}
          onAutoPivot={(point) => onSetPivotMarker(symbol, point)}
        />
      </div>

      {pivotMenu && (
        <div
          ref={pivotMenuRef}
          role="menu"
          className="fixed z-[100] min-w-[200px] rounded-md border border-border bg-popover py-1 text-popover-foreground shadow-md"
          style={{
            left: Math.min(pivotMenu.x, window.innerWidth - 210),
            top: Math.min(pivotMenu.y, window.innerHeight - 140),
          }}
          onPointerDown={e => e.stopPropagation()}
        >
          <div className="px-2 py-1.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
            Pivot
          </div>
          {pivotMarker && (
            <div className="px-2 pb-1.5 text-[11px] text-muted-foreground border-b border-border truncate" title={`${pivotMarker.date} @ $${pivotMarker.price.toFixed(2)}`}>
              Current: {pivotMarker.date} @ ${pivotMarker.price.toFixed(2)}
            </div>
          )}
          {!pivotMenu.pointSnapshot && (
            <div className="px-2 pb-1 text-[11px] text-muted-foreground border-b border-border">
              Move crosshair on chart, then right-click to capture a pivot point.
            </div>
          )}
          <button
            type="button"
            role="menuitem"
            className="flex w-full items-center px-3 py-2 text-left text-sm hover:bg-muted disabled:opacity-40 disabled:pointer-events-none"
            disabled={!pivotMenu.pointSnapshot}
            onClick={() => {
              if (pivotMenu.pointSnapshot) onSetPivotMarker(symbol, pivotMenu.pointSnapshot);
              setPivotMenu(null);
            }}
          >
            Set pivot at crosshair
          </button>
          <button
            type="button"
            role="menuitem"
            className="flex w-full items-center px-3 py-2 text-left text-sm text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-40 disabled:pointer-events-none"
            disabled={!pivotMarker}
            onClick={() => {
              onClearPivotMarker(symbol);
              setPivotMenu(null);
            }}
          >
            Clear pivot
          </button>
        </div>
      )}

      <p className="text-xs text-muted-foreground text-center">
        Use ← → arrow keys or buttons to navigate · right-click chart for pivot · {symbols.length} stocks in current filter
      </p>
    </div>
  );
}

// ─── RelationshipMapView ─────────────────────────────────────────────────────

interface TickerEdge {
  from: string;
  to: string;
  rel_type: string;
  strength: number;
  count: number;
  note: string;
}

const REL_COLORS: Record<string, string> = {
  competitor: "#ef4444",
  supplier:   "#22c55e",
  customer:   "#3b82f6",
  partner:    "#a855f7",
  acquirer:   "#f97316",
  subsidiary: "#14b8a6",
};

const REL_LABELS: Record<string, string> = {
  competitor: "Competitor",
  supplier:   "Supplier",
  customer:   "Customer",
  partner:    "Partner",
  acquirer:   "Acquirer",
  subsidiary: "Subsidiary",
};

const NODE_R = 18;
const GW = 900;
const GH = 520;
const REPULSION = 6000;
const SPRING_K = 0.04;
const SPRING_REST = 110;
const CENTER_K = 0.008;
const DAMPING = 0.86;
const SIM_STEPS = 400;

function runForceLayout(
  nodeIds: string[],
  edges: { from: string; to: string; strength: number }[],
): Record<string, { x: number; y: number }> {
  const cx = GW / 2, cy = GH / 2;
  const r0 = Math.min(GW, GH) * 0.32;
  const pos: Record<string, { x: number; y: number; vx: number; vy: number }> = {};
  nodeIds.forEach((id, i) => {
    const angle = (2 * Math.PI * i) / nodeIds.length - Math.PI / 2;
    pos[id] = { x: cx + r0 * Math.cos(angle), y: cy + r0 * Math.sin(angle), vx: 0, vy: 0 };
  });
  const active = edges.filter(e => e.from in pos && e.to in pos);
  for (let step = 0; step < SIM_STEPS; step++) {
    const cool = 1 - step / SIM_STEPS;
    for (let i = 0; i < nodeIds.length; i++) {
      for (let j = i + 1; j < nodeIds.length; j++) {
        const a = pos[nodeIds[i]!]!;
        const b = pos[nodeIds[j]!]!;
        const dx = a.x - b.x || 0.01;
        const dy = a.y - b.y || 0.01;
        const dist2 = Math.max(1, dx * dx + dy * dy);
        const dist = Math.sqrt(dist2);
        const f = REPULSION / dist2;
        const fx = (dx / dist) * f;
        const fy = (dy / dist) * f;
        a.vx += fx; a.vy += fy;
        b.vx -= fx; b.vy -= fy;
      }
    }
    for (const e of active) {
      const a = pos[e.from]!;
      const b = pos[e.to]!;
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const dist = Math.sqrt(dx * dx + dy * dy) || 0.01;
      const disp = dist - SPRING_REST * (1 / (0.3 + e.strength));
      const f = SPRING_K * disp;
      const fx = (dx / dist) * f;
      const fy = (dy / dist) * f;
      a.vx += fx; a.vy += fy;
      b.vx -= fx; b.vy -= fy;
    }
    for (const id of nodeIds) {
      const n = pos[id]!;
      n.vx += (cx - n.x) * CENTER_K;
      n.vy += (cy - n.y) * CENTER_K;
      n.vx *= DAMPING;
      n.vy *= DAMPING;
      n.x += n.vx * cool;
      n.y += n.vy * cool;
      n.x = Math.max(NODE_R + 6, Math.min(GW - NODE_R - 6, n.x));
      n.y = Math.max(NODE_R + 6, Math.min(GH - NODE_R - 6, n.y));
    }
  }
  return Object.fromEntries(nodeIds.map(id => [id, { x: pos[id]!.x, y: pos[id]!.y }]));
}

function RelationshipMapView({
  symbols,
  selectedTicker,
  onSelect,
  getTickerMeta,
}: {
  symbols: string[];
  selectedTicker: string | null;
  onSelect: (ticker: string) => void;
  getTickerMeta: (ticker: string) => { sector: string; industry: string };
}) {
  const [allEdges, setAllEdges] = useState<TickerEdge[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hoveredEdge, setHoveredEdge] = useState<TickerEdge | null>(null);
  const [hoveredNode, setHoveredNode] = useState<string | null>(null);

  const symbolSet = useMemo(() => new Set(symbols), [symbols]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    screeningsGetTickerRelationships()
      .then((res) => {
        if (!res.ok) {
          if (!cancelled) setError("Failed to load relationship data");
          return;
        }
        if (!cancelled) setAllEdges(Array.isArray(res.data) ? res.data : []);
      })
      .catch(() => { if (!cancelled) setError("Failed to load relationship data"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  const visibleEdges = useMemo(
    () => allEdges.filter(e => symbolSet.has(e.from) && symbolSet.has(e.to)),
    [allEdges, symbolSet]
  );

  const edgesByPair = useMemo(() => {
    const map = new Map<string, TickerEdge[]>();
    for (const e of visibleEdges) {
      const key = [e.from, e.to].sort().join("__");
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(e);
    }
    return map;
  }, [visibleEdges]);

  const nodeIds = useMemo(() => [...symbols].sort(), [symbols]);

  const positions = useMemo(() => {
    if (nodeIds.length === 0) return {};
    return runForceLayout(
      nodeIds,
      visibleEdges.map(e => ({ from: e.from, to: e.to, strength: e.strength }))
    );
  }, [nodeIds, visibleEdges]);

  const idx = selectedTicker ? nodeIds.indexOf(selectedTicker) : -1;

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      if (e.key === "ArrowLeft" && idx > 0) onSelect(nodeIds[idx - 1]!);
      if (e.key === "ArrowRight" && idx < nodeIds.length - 1) onSelect(nodeIds[idx + 1]!);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [idx, nodeIds, onSelect]);

  const symbol = selectedTicker ?? nodeIds[0] ?? null;
  const displayIdx = symbol ? nodeIds.indexOf(symbol) : 0;
  const selectedMeta = symbol ? getTickerMeta(symbol) : null;

  const connectedSet = useMemo(() => {
    if (!symbol) return new Set<string>();
    const s = new Set<string>();
    for (const e of visibleEdges) {
      if (e.from === symbol) s.add(e.to);
      if (e.to === symbol) s.add(e.from);
    }
    return s;
  }, [symbol, visibleEdges]);

  const selectedConnections = useMemo(() => {
    if (!symbol) return [];
    return visibleEdges
      .filter(e => e.from === symbol || e.to === symbol)
      .map(e => ({ ...e, peer: e.from === symbol ? e.to : e.from }))
      .sort((a, b) => b.strength - a.strength);
  }, [symbol, visibleEdges]);

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground py-8">
        <Loader2 className="w-4 h-4 animate-spin" />
        Loading relationship data…
      </div>
    );
  }
  if (error) return <p className="text-sm text-rose-500 py-8">{error}</p>;
  if (symbols.length === 0) {
    return <p className="text-sm text-muted-foreground py-8 text-center">No tickers in current filter set.</p>;
  }

  return (
    <div className="flex flex-col gap-3">
      {/* Navigation header */}
      <div className="flex items-center gap-3 flex-wrap">
        <button
          onClick={() => displayIdx > 0 && onSelect(nodeIds[displayIdx - 1]!)}
          disabled={displayIdx <= 0}
          className="p-1.5 rounded-md border border-border hover:bg-muted disabled:opacity-30 transition-colors"
          title="Previous (←)"
        >
          <ChevronLeft className="w-4 h-4" />
        </button>
        <select
          value={symbol ?? ""}
          onChange={e => onSelect(e.target.value)}
          className="px-2 py-1 text-sm font-mono font-semibold rounded border border-input bg-background focus:outline-none focus:ring-1 focus:ring-ring"
        >
          {nodeIds.map(s => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
        <button
          onClick={() => displayIdx < nodeIds.length - 1 && onSelect(nodeIds[displayIdx + 1]!)}
          disabled={displayIdx >= nodeIds.length - 1}
          className="p-1.5 rounded-md border border-border hover:bg-muted disabled:opacity-30 transition-colors"
          title="Next (→)"
        >
          <ChevronRight className="w-4 h-4" />
        </button>
        {selectedMeta && (selectedMeta.sector || selectedMeta.industry) && (
          <span className="text-xs text-muted-foreground truncate max-w-[260px]">
            {[selectedMeta.sector, selectedMeta.industry].filter(Boolean).join(" · ")}
          </span>
        )}
        <span className="text-sm text-muted-foreground ml-auto">{displayIdx + 1} / {nodeIds.length}</span>
      </div>

      {/* Hover tooltip */}
      {hoveredEdge && (
        <div className="text-xs text-muted-foreground px-1 min-h-[1.25rem]">
          <span className="font-mono font-semibold text-foreground">{hoveredEdge.from}</span>
          {" → "}
          <span className="font-mono font-semibold text-foreground">{hoveredEdge.to}</span>
          {" "}
          <span className="rounded px-1.5 py-0.5 text-white text-[10px] font-medium" style={{ background: REL_COLORS[hoveredEdge.rel_type] ?? "#888" }}>
            {REL_LABELS[hoveredEdge.rel_type] ?? hoveredEdge.rel_type}
          </span>
          {" "}
          <span className="tabular-nums">{(hoveredEdge.strength * 100).toFixed(0)}% strength</span>
          {hoveredEdge.count > 1 && <span className="text-muted-foreground/60"> · {hoveredEdge.count} mentions</span>}
          {hoveredEdge.note && <span className="ml-2 italic text-muted-foreground/70">{hoveredEdge.note.replace(/^\[.*?\]\s*/, "")}</span>}
        </div>
      )}

      {/* Network graph */}
      <div className="rounded-lg border border-border bg-background overflow-hidden">
        <svg viewBox={`0 0 ${GW} ${GH}`} className="w-full" style={{ maxHeight: 520 }}>
          {/* Edges */}
          {Array.from(edgesByPair.entries()).map(([pairKey, edges]) => {
            const primary = edges.reduce((best, e) => e.strength > best.strength ? e : best, edges[0]!);
            const p0 = positions[primary.from];
            const p1 = positions[primary.to];
            if (!p0 || !p1) return null;
            const isHighlighted = primary.from === symbol || primary.to === symbol;
            const isHovered = hoveredEdge &&
              ((hoveredEdge.from === primary.from && hoveredEdge.to === primary.to) ||
               (hoveredEdge.from === primary.to && hoveredEdge.to === primary.from));
            const color = REL_COLORS[primary.rel_type] ?? "#888";
            const opacity = symbol ? (isHighlighted ? 0.85 : 0.1) : (isHovered ? 0.9 : 0.4);
            const sw = 1 + primary.strength * 3 * (isHighlighted ? 1.5 : 1);
            const mx = (p0.x + p1.x) / 2;
            const my = (p0.y + p1.y) / 2;
            return (
              <g key={pairKey}>
                <line
                  x1={p0.x} y1={p0.y} x2={p1.x} y2={p1.y}
                  stroke={color} strokeWidth={sw} strokeOpacity={opacity}
                  className="cursor-pointer"
                  onMouseEnter={() => setHoveredEdge(primary)}
                  onMouseLeave={() => setHoveredEdge(null)}
                />
                {(isHighlighted || isHovered) && (
                  <text x={mx} y={my - 4} textAnchor="middle" fontSize={9}
                    fill={color} fillOpacity={0.9}
                    className="select-none pointer-events-none">
                    {REL_LABELS[primary.rel_type] ?? primary.rel_type}
                  </text>
                )}
              </g>
            );
          })}

          {/* Nodes */}
          {nodeIds.map(sym => {
            const p = positions[sym];
            if (!p) return null;
            const isSelected = sym === symbol;
            const isConnected = connectedSet.has(sym);
            const isHov = hoveredNode === sym;
            const dimmed = symbol && !isSelected && !isConnected;
            return (
              <g key={sym} transform={`translate(${p.x},${p.y})`}
                className="cursor-pointer"
                onClick={() => onSelect(sym)}
                onMouseEnter={() => setHoveredNode(sym)}
                onMouseLeave={() => setHoveredNode(null)}
                style={{ opacity: dimmed ? 0.3 : 1 }}
              >
                {(isSelected || isConnected || isHov) && (
                  <circle r={NODE_R + 4} fill="none"
                    stroke={isSelected ? "hsl(var(--foreground))" : "hsl(var(--foreground) / 0.3)"}
                    strokeWidth={isSelected ? 2 : 1}
                  />
                )}
                <circle r={NODE_R}
                  fill={isSelected ? "hsl(var(--foreground))" : "hsl(var(--muted))"}
                  stroke="hsl(var(--border))" strokeWidth={1}
                />
                <text textAnchor="middle" dominantBaseline="middle"
                  fontSize={sym.length > 4 ? 8 : 9} fontWeight="600" fontFamily="monospace"
                  fill={isSelected ? "hsl(var(--background))" : "hsl(var(--foreground))"}
                  className="select-none pointer-events-none">
                  {sym}
                </text>
              </g>
            );
          })}
        </svg>
      </div>

      {/* Connections detail + legend */}
      <div className="grid gap-4 md:grid-cols-2">
        <div className="flex flex-col gap-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            {symbol} — connections ({selectedConnections.length})
          </p>
          {selectedConnections.length === 0 ? (
            <p className="text-xs text-muted-foreground">No relationships found in current filter set.</p>
          ) : (
            <div className="rounded-lg border border-border overflow-hidden">
              <table className="w-full text-sm">
                <tbody className="divide-y divide-border">
                  {selectedConnections.map((c, i) => (
                    <tr key={`${c.peer}-${c.rel_type}-${i}`}
                      className="hover:bg-muted/30 cursor-pointer"
                      onClick={() => onSelect(c.peer)}
                    >
                      <td className="px-3 py-2 font-mono font-semibold w-20">{c.peer}</td>
                      <td className="px-3 py-2">
                        <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium text-white"
                          style={{ background: REL_COLORS[c.rel_type] ?? "#888" }}>
                          {REL_LABELS[c.rel_type] ?? c.rel_type}
                        </span>
                      </td>
                      <td className="px-3 py-2 tabular-nums text-xs text-muted-foreground">
                        {(c.strength * 100).toFixed(0)}%
                        {c.count > 1 && <span className="ml-1 text-muted-foreground/50">×{c.count}</span>}
                      </td>
                      <td className="px-3 py-2 text-xs text-muted-foreground/70 italic max-w-[200px] truncate" title={c.note}>
                        {c.note.replace(/^\[.*?\]\s*/, "")}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="flex flex-col gap-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Legend</p>
          <div className="flex flex-wrap gap-3">
            {Object.entries(REL_LABELS).map(([type, label]) => (
              <div key={type} className="flex items-center gap-1.5">
                <div className="w-3 h-1.5 rounded-sm" style={{ background: REL_COLORS[type] ?? "#888" }} />
                <span className="text-xs text-muted-foreground">{label}</span>
              </div>
            ))}
          </div>
          <p className="text-xs text-muted-foreground mt-1">
            Edge thickness = relationship strength · Only edges between tickers in current filter shown
          </p>
          {visibleEdges.length === 0 && allEdges.length > 0 && (
            <p className="text-xs text-amber-600 dark:text-amber-400 mt-1">
              No relationships between tickers in this filter. Try broadening your filter.
            </p>
          )}
          {allEdges.length === 0 && !loading && (
            <p className="text-xs text-muted-foreground/60 mt-1">
              No data yet — relationships are scored automatically as articles are ingested.
            </p>
          )}
        </div>
      </div>

      <p className="text-xs text-muted-foreground text-center">
        Use ← → arrow keys or buttons to navigate · click a node to select · {nodeIds.length} stocks in current filter
      </p>
    </div>
  );
}

// ─── SentimentView ───────────────────────────────────────────────────────────

type SentimentSort = { key: "symbol" | "s7d" | "s30d" | "s90d"; dir: "asc" | "desc" };

function computeStockSentiment(
  articles: SentimentArticleImpact[],
  ticker: string,
  cutoffDate: string,
): number {
  let total = 0;
  for (const article of articles) {
    if (article.published_at.slice(0, 10) < cutoffDate) continue;
    const score = article.ticker_sentiment?.[ticker];
    if (typeof score === "number" && Number.isFinite(score)) total += score;
  }
  return total;
}

function SentimentScoreCell({ value, maxAbs }: { value: number; maxAbs: number }) {
  const pct = maxAbs > 0 ? Math.abs(value) / maxAbs : 0;
  const pos = value >= 0;
  const negligible = Math.abs(value) < 0.01;
  return (
    <div className="flex items-center gap-2 min-w-[130px]">
      <div className="relative flex-1 h-1.5 rounded-full bg-muted overflow-hidden">
        <div className="absolute inset-y-0 left-1/2 w-px bg-border" />
        <div
          className={`absolute top-0 h-full rounded-full ${pos ? "bg-emerald-500 left-1/2" : "bg-rose-400 right-1/2"}`}
          style={{ width: `${pct * 50}%` }}
        />
      </div>
      <span className={`text-xs font-mono w-14 text-right tabular-nums ${negligible ? "text-muted-foreground" : pos ? "text-emerald-500" : "text-rose-400"}`}>
        {value >= 0 ? "+" : ""}{value.toFixed(2)}
      </span>
    </div>
  );
}

function SentimentTh({
  col, sort, onSort, children, right,
}: {
  col: SentimentSort["key"];
  sort: SentimentSort;
  onSort: (col: SentimentSort["key"]) => void;
  children: React.ReactNode;
  right?: boolean;
}) {
  return (
    <th
      className={`px-3 py-2 text-xs font-medium text-muted-foreground uppercase tracking-wide cursor-pointer select-none hover:text-foreground whitespace-nowrap ${right ? "text-right" : "text-left"}`}
      onClick={() => onSort(col)}
    >
      {children}
      {sort.key === col && (sort.dir === "asc"
        ? <ChevronUp className="w-3 h-3 inline ml-0.5" />
        : <ChevronDown className="w-3 h-3 inline ml-0.5" />)}
    </th>
  );
}

function SentimentView({
  symbols,
  selectedTicker,
  onSelect,
  getTickerMeta,
}: {
  symbols: string[];
  selectedTicker: string | null;
  onSelect: (ticker: string) => void;
  getTickerMeta: (ticker: string) => { sector: string; industry: string };
}) {
  const [articles, setArticles] = useState<SentimentArticleImpact[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sort, setSort] = useState<SentimentSort>({ key: "s7d", dir: "desc" });

  useEffect(() => {
    setLoading(true);
    setError(null);
    screeningsGetNewsImpacts()
      .then((res) => {
        if (!res.ok) {
          setError("Failed to load news data");
          return;
        }
        setArticles(res.data as SentimentArticleImpact[]);
      })
      .catch(() => setError("Failed to load news data"))
      .finally(() => setLoading(false));
  }, []);

  const cutoffs = useMemo(() => {
    const now = new Date();
    function daysAgo(n: number) {
      const d = new Date(now);
      d.setDate(d.getDate() - n);
      return d.toISOString().slice(0, 10);
    }
    return { c7: daysAgo(7), c30: daysAgo(30), c90: daysAgo(90) };
  }, []);

  const rows = useMemo(() => {
    return symbols
      .map(symbol => {
        const { sector, industry } = getTickerMeta(symbol);
        return {
          symbol,
          sector,
          industry,
          s7d: computeStockSentiment(articles, symbol, cutoffs.c7),
          s30d: computeStockSentiment(articles, symbol, cutoffs.c30),
          s90d: computeStockSentiment(articles, symbol, cutoffs.c90),
        };
      });
  }, [symbols, articles, cutoffs, getTickerMeta]);

  const maxAbs = useMemo(
    () => Math.max(...rows.flatMap(r => [Math.abs(r.s7d), Math.abs(r.s30d), Math.abs(r.s90d)]), 0.01),
    [rows],
  );

  const sorted = useMemo(() => {
    const { key, dir } = sort;
    return [...rows].sort((a, b) => {
      const av = a[key];
      const bv = b[key];
      if (typeof av === "string" && typeof bv === "string") {
        return dir === "asc" ? av.localeCompare(bv) : bv.localeCompare(av);
      }
      return dir === "asc" ? (av as number) - (bv as number) : (bv as number) - (av as number);
    });
  }, [rows, sort]);

  function toggleSort(key: SentimentSort["key"]) {
    setSort(prev =>
      prev.key === key
        ? { key, dir: prev.dir === "asc" ? "desc" : "asc" }
        : { key, dir: key === "symbol" ? "asc" : "desc" }
    );
  }

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground py-8">
        <Loader2 className="w-4 h-4 animate-spin" />
        Loading sentiment data…
      </div>
    );
  }
  if (error) return <p className="text-sm text-rose-500 py-4">{error}</p>;
  if (rows.length === 0) {
    return (
      <p className="text-sm text-muted-foreground py-8 text-center">
        {articles.length === 0
          ? "No news data available."
          : "No ticker sentiment data available for the filtered stocks."}
      </p>
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full text-sm">
        <thead className="bg-muted/40 border-b border-border">
          <tr>
            <SentimentTh col="symbol" sort={sort} onSort={toggleSort}>Symbol</SentimentTh>
            <th className="px-3 py-2 text-left text-xs font-medium text-muted-foreground uppercase tracking-wide whitespace-nowrap">Sector</th>
            <SentimentTh col="s7d" sort={sort} onSort={toggleSort} right>7-day</SentimentTh>
            <SentimentTh col="s30d" sort={sort} onSort={toggleSort} right>30-day</SentimentTh>
            <SentimentTh col="s90d" sort={sort} onSort={toggleSort} right>90-day</SentimentTh>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {sorted.map(row => (
            <tr
              key={row.symbol}
              onClick={() => onSelect(row.symbol)}
              className={`cursor-pointer transition-colors hover:bg-muted/30 ${selectedTicker === row.symbol ? "bg-foreground/10 ring-1 ring-inset ring-foreground/20" : ""}`}
            >
              <td className="px-3 py-2 font-mono font-semibold whitespace-nowrap">{row.symbol}</td>
              <td className="px-3 py-2 text-xs text-muted-foreground whitespace-nowrap max-w-[140px] truncate" title={row.sector || undefined}>{row.sector || "—"}</td>
              <td className="px-3 py-2"><SentimentScoreCell value={row.s7d} maxAbs={maxAbs} /></td>
              <td className="px-3 py-2"><SentimentScoreCell value={row.s30d} maxAbs={maxAbs} /></td>
              <td className="px-3 py-2"><SentimentScoreCell value={row.s90d} maxAbs={maxAbs} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ─── StockNewsTrendView ──────────────────────────────────────────────────────

/** Scale each dimension's impact by the company vector score for that dimension. */
function applyCompanyVector(
  articles: ArticleImpact[],
  companyDims: Record<string, number>,
): ArticleImpact[] {
  return articles.map(a => ({
    ...a,
    impact_json: Object.fromEntries(
      Object.entries(a.impact_json).map(([k, v]) => [k, v * (companyDims[k] ?? 0)])
    ),
  }));
}

function StockNewsTrendView({
  symbols,
  companyVectorDimensions,
  selectedTicker,
  onSelect,
  dismissed,
  onDismiss,
  onRestore,
  getStatus,
  onSetStatus,
  hasComment,
  onEditComment,
  getTickerMeta,
}: {
  symbols: string[];
  companyVectorDimensions: Record<string, Record<string, number>>;
  selectedTicker: string | null;
  onSelect: (ticker: string) => void;
  dismissed: Set<string>;
  onDismiss: (ticker: string) => void;
  onRestore: (ticker: string) => void;
  getStatus: (ticker: string) => NoteStatus;
  onSetStatus: (ticker: string, status: NoteStatus) => void;
  hasComment: (ticker: string) => boolean;
  onEditComment: (ticker: string) => void;
  getTickerMeta: (ticker: string) => { sector: string; industry: string };
}) {
  const [articles, setArticles] = useState<ArticleImpact[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Match the candlestick chart's aspect ratio (viewBox 900×436)
  const containerRef = useRef<HTMLDivElement>(null);
  const [chartHeight, setChartHeight] = useState(436);
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => {
      const w = entry.contentRect.width;
      setChartHeight(Math.max(260, Math.round(w * (436 / 900))));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Only stocks with a vector
  const eligible = useMemo(
    () => symbols.filter(s => {
      const d = companyVectorDimensions[s];
      return d && Object.keys(d).length > 0;
    }),
    [symbols, companyVectorDimensions]
  );

  const idx = useMemo(() => {
    const i = selectedTicker ? eligible.indexOf(selectedTicker) : -1;
    return i >= 0 ? i : 0;
  }, [eligible, selectedTicker]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "ArrowLeft") onSelect(eligible[Math.max(0, idx - 1)]);
      if (e.key === "ArrowRight") onSelect(eligible[Math.min(eligible.length - 1, idx + 1)]);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [idx, eligible, onSelect]);

  useEffect(() => {
    setLoading(true);
    setError(null);
    screeningsGetNewsImpacts()
      .then((res) => {
        if (!res.ok) {
          setError("Failed to load news data");
          return;
        }
        setArticles(res.data);
      })
      .catch(() => setError("Failed to load news data"))
      .finally(() => setLoading(false));
  }, []);

  const symbol = eligible[idx] ?? null;
  const meta = symbol ? getTickerMeta(symbol) : { sector: "", industry: "" };
  const status = symbol ? getStatus(symbol) : "active";
  const commentExists = symbol ? hasComment(symbol) : false;

  // Pre-multiply articles by the current stock's company vector
  const weightedArticles = useMemo(() => {
    if (!symbol || articles.length === 0) return [];
    const dims = companyVectorDimensions[symbol] ?? {};
    return applyCompanyVector(articles, dims);
  }, [symbol, articles, companyVectorDimensions]);

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground py-8">
        <Loader2 className="w-4 h-4 animate-spin" />
        Loading news data…
      </div>
    );
  }
  if (error) return <p className="text-sm text-rose-500 py-4">{error}</p>;
  if (eligible.length === 0) {
    return (
      <p className="text-sm text-muted-foreground py-8 text-center">
        None of the filtered stocks have a company vector. Run the vector builder first.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {/* Nav bar */}
      <div className="flex items-center gap-3">
        <button
          onClick={() => onSelect(eligible[Math.max(0, idx - 1)])}
          disabled={idx === 0}
          className="p-1.5 rounded-md border border-border hover:bg-muted disabled:opacity-30 transition-colors"
          title="Previous (←)"
        >
          <ChevronLeft className="w-4 h-4" />
        </button>

        <span className="font-mono font-bold text-lg">{symbol}</span>
        {(meta.sector || meta.industry) && (
          <span
            className="text-xs text-muted-foreground max-w-[260px] truncate"
            title={[meta.sector, meta.industry].filter(Boolean).join(" · ")}
          >
            {[meta.sector, meta.industry].filter(Boolean).join(" · ")}
          </span>
        )}
        <span className="text-sm text-muted-foreground">{idx + 1} / {eligible.length}</span>

        {symbol && (dismissed.has(symbol) ? (
          <button
            onClick={() => onRestore(symbol)}
            title="Restore"
            className="flex items-center gap-1.5 text-xs px-2 py-1 rounded border border-border text-emerald-500 hover:bg-muted transition-colors"
          >
            <RotateCcw className="w-3.5 h-3.5" /> Restore
          </button>
        ) : (
          <button
            onClick={() => onDismiss(symbol)}
            title="Dismiss"
            className="flex items-center gap-1.5 text-xs px-2 py-1 rounded border border-border text-muted-foreground hover:text-rose-500 hover:border-rose-400 transition-colors"
          >
            <Trash2 className="w-3.5 h-3.5" /> Dismiss
          </button>
        ))}

        {symbol && (
          <select
            value={status}
            onChange={e => onSetStatus(symbol, e.target.value as NoteStatus)}
            className="px-2 py-1 text-xs rounded border border-input bg-background focus:outline-none focus:ring-1 focus:ring-ring"
            title="Status"
          >
            <option value="active">Active</option>
            <option value="dismissed">Dismissed</option>
            <option value="watchlist">Watchlist</option>
            <option value="pipeline">Pipeline</option>
          </select>
        )}

        {symbol && (
          <button
            onClick={() => onEditComment(symbol)}
            title={commentExists ? "Edit note" : "Add note"}
            className={`flex items-center gap-1.5 text-xs px-2 py-1 rounded border border-border transition-colors ${commentExists ? "text-sky-500 hover:bg-muted" : "text-muted-foreground hover:text-sky-500 hover:border-sky-400"}`}
          >
            <MessageSquare className="w-3.5 h-3.5" /> {commentExists ? "Edit note" : "Add note"}
          </button>
        )}

        <select
          value={symbol ?? ""}
          onChange={e => onSelect(e.target.value)}
          className="ml-auto px-2 py-1 text-sm rounded border border-input bg-background focus:outline-none focus:ring-1 focus:ring-ring"
        >
          {eligible.map((s, i) => (
            <option key={s} value={s}>{i + 1}. {s}</option>
          ))}
        </select>

        <button
          onClick={() => onSelect(eligible[Math.min(eligible.length - 1, idx + 1)])}
          disabled={idx === eligible.length - 1}
          className="p-1.5 rounded-md border border-border hover:bg-muted disabled:opacity-30 transition-colors"
          title="Next (→)"
        >
          <ChevronRight className="w-4 h-4" />
        </button>
      </div>

      {/* News trend chart — reuses the full NewsTrendsUI with weighted articles */}
      <div ref={containerRef} className="w-full">
        {symbol && weightedArticles.length > 0 && (
          <NewsTrendsUI key={symbol} articles={weightedArticles} chartHeight={chartHeight} />
        )}
      </div>
      {symbol && weightedArticles.length === 0 && articles.length > 0 && (
        <p className="text-sm text-muted-foreground py-8 text-center">No news data available.</p>
      )}

      {symbols.length > eligible.length && (
        <p className="text-xs text-muted-foreground">
          {symbols.length - eligible.length} stock{symbols.length - eligible.length !== 1 ? "s" : ""} skipped — no company vector.
        </p>
      )}
    </div>
  );
}

function LogTradeForm({
  ticker,
  defaultPrice,
  onDone,
  onCancel,
}: {
  ticker: string;
  defaultPrice: number | null;
  onDone: () => void;
  onCancel: () => void;
}) {
  const router = useRouter();
  const [side, setSide] = useState<"buy" | "sell">("buy");
  const [positionSide, setPositionSide] = useState<"long" | "short">("long");
  const [quantity, setQuantity] = useState("");
  const [pricePerUnit, setPricePerUnit] = useState(
    defaultPrice != null ? String(Math.round(defaultPrice * 1_000_000) / 1_000_000) : ""
  );
  const [currency, setCurrency] = useState("USD");
  const [executedAtLocal, setExecutedAtLocal] = useState(() => {
    const d = new Date();
    const pad = (n: number) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  });
  const [tradeNotes, setTradeNotes] = useState("");
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [priceStatus, setPriceStatus] = useState<"idle" | "loading" | "ok">("idle");
  const priceFetchGen = useRef(0);
  const priceDirtyRef = useRef(false);

  // Auto-fill price when execution date changes (same logic as trades page)
  useEffect(() => {
    priceDirtyRef.current = false;
  }, [executedAtLocal]);

  useEffect(() => {
    if (!ticker || !executedAtLocal) return;
    const d = new Date(executedAtLocal);
    if (Number.isNaN(d.getTime())) return;
    const cal = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

    const handle = setTimeout(() => {
      const id = ++priceFetchGen.current;
      async function run() {
        if (priceDirtyRef.current) return;
        setPriceStatus("loading");
        try {
          const res = await fmpGetPriceAtDate(ticker, cal);
          if (id !== priceFetchGen.current) return;
          if (res.ok && !priceDirtyRef.current) {
            setPricePerUnit(String(Math.round(res.data.price * 1_000_000) / 1_000_000));
            setPriceStatus("ok");
          } else {
            setPriceStatus("idle");
          }
        } catch {
          if (id === priceFetchGen.current) setPriceStatus("idle");
        }
      }
      void run();
    }, 600);

    return () => { clearTimeout(handle); priceFetchGen.current += 1; };
  }, [ticker, executedAtLocal]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setFormError(null);
    const q = parseFloat(quantity);
    const p = parseFloat(pricePerUnit);
    if (!Number.isFinite(q) || q <= 0) { setFormError("Quantity must be a positive number."); return; }
    if (!Number.isFinite(p) || p < 0) { setFormError("Price must be zero or positive."); return; }
    const executed = new Date(executedAtLocal);
    if (Number.isNaN(executed.getTime())) { setFormError("Invalid execution date."); return; }

    setSaving(true);
    const supabase = createClient();
    const { data: userData, error: userErr } = await supabase.auth.getUser();
    if (userErr || !userData.user) { setFormError("Not signed in."); setSaving(false); return; }

    const { error: dbErr } = await supabase
      .schema("swingtrader")
      .from("user_trades")
      .insert({
        user_id: userData.user.id,
        side,
        position_side: positionSide,
        ticker,
        quantity: q,
        price_per_unit: p,
        currency: currency.trim() || "USD",
        executed_at: executed.toISOString(),
        notes: tradeNotes.trim() || null,
      });

    setSaving(false);
    if (dbErr) { setFormError(dbErr.message); return; }
    router.refresh();
    onDone();
  }

  const inputCls = "rounded-md border border-border bg-background px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-ring";
  const selectCls = `${inputCls} pr-6`;

  return (
    <form onSubmit={e => void handleSubmit(e)} className="flex flex-col gap-3 p-4 bg-muted/30 rounded-lg border border-border">
      <p className="text-xs font-semibold text-foreground">Log trade — <span className="font-mono">{ticker}</span></p>
      <div className="flex flex-wrap gap-3 items-end">
        {/* Side */}
        <label className="flex flex-col gap-1 text-xs text-muted-foreground">
          Side
          <select value={side} onChange={e => setSide(e.target.value as "buy" | "sell")} className={selectCls}>
            <option value="buy">Buy</option>
            <option value="sell">Sell</option>
          </select>
        </label>
        {/* Position */}
        <label className="flex flex-col gap-1 text-xs text-muted-foreground">
          Position
          <select value={positionSide} onChange={e => setPositionSide(e.target.value as "long" | "short")} className={selectCls}>
            <option value="long">Long</option>
            <option value="short">Short</option>
          </select>
        </label>
        {/* Executed */}
        <label className="flex flex-col gap-1 text-xs text-muted-foreground">
          Executed (local)
          <input
            type="datetime-local"
            value={executedAtLocal}
            onChange={e => setExecutedAtLocal(e.target.value)}
            className={inputCls}
          />
        </label>
        {/* Quantity */}
        <label className="flex flex-col gap-1 text-xs text-muted-foreground">
          Quantity
          <input
            type="number"
            min="0"
            step="any"
            placeholder="0"
            value={quantity}
            onChange={e => setQuantity(e.target.value)}
            className={`${inputCls} w-24`}
            required
          />
        </label>
        {/* Price */}
        <label className="flex flex-col gap-1 text-xs text-muted-foreground">
          Price / unit
          <div className="relative flex items-center">
            <input
              type="number"
              min="0"
              step="any"
              placeholder="0.00"
              value={pricePerUnit}
              onChange={e => { priceDirtyRef.current = true; setPricePerUnit(e.target.value); setPriceStatus("idle"); }}
              className={`${inputCls} w-28 pr-6`}
              required
            />
            {priceStatus === "loading" && (
              <Loader2 className="absolute right-1.5 w-3 h-3 animate-spin text-muted-foreground" />
            )}
            {priceStatus === "ok" && (
              <CheckCircle className="absolute right-1.5 w-3 h-3 text-emerald-500" />
            )}
          </div>
        </label>
        {/* Currency */}
        <label className="flex flex-col gap-1 text-xs text-muted-foreground">
          CCY
          <input
            type="text"
            value={currency}
            onChange={e => setCurrency(e.target.value.toUpperCase())}
            maxLength={4}
            className={`${inputCls} w-16 uppercase`}
          />
        </label>
        {/* Notes */}
        <label className="flex flex-col gap-1 text-xs text-muted-foreground flex-1 min-w-[140px]">
          Notes (optional)
          <input
            type="text"
            value={tradeNotes}
            onChange={e => setTradeNotes(e.target.value)}
            placeholder="e.g. breakout entry"
            className={inputCls}
          />
        </label>
      </div>
      {formError && <p className="text-xs text-rose-500">{formError}</p>}
      <div className="flex gap-2">
        <button
          type="submit"
          disabled={saving}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-foreground text-background text-xs font-medium disabled:opacity-50 hover:opacity-90 transition-opacity"
        >
          {saving ? <Loader2 className="w-3 h-3 animate-spin" /> : <Plus className="w-3 h-3" />}
          {saving ? "Saving…" : "Save trade"}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="px-3 py-1.5 rounded-md border border-border text-xs text-muted-foreground hover:bg-muted/40 transition-colors"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}

function TradeMonitoringView({
  entries,
  selectedTicker,
  onSelect,
  onGoToCharts,
  onOpenWorkflowEditor,
  getStatus,
  filteredSymbolSet,
}: {
  entries: { row: ScreeningRow; pivot: PivotMarker }[];
  selectedTicker: string | null;
  onSelect: (ticker: string) => void;
  onGoToCharts: () => void;
  onOpenWorkflowEditor: (ticker: string) => void;
  getStatus: (ticker: string) => NoteStatus;
  /** Symbols currently included in the Results table after filters (pivot names may extend beyond this). */
  filteredSymbolSet: Set<string>;
}) {
  const [quotes, setQuotes] = useState<Record<string, FmpQuote | null>>({});
  const [loadingQuotes, setLoadingQuotes] = useState(false);
  const [logTradeTicker, setLogTradeTicker] = useState<string | null>(null);
  type TradeSortKey = "symbol" | "sector" | "RS_Rank" | "Passed" | "pivotDate" | "pivotPrice" | "latest" | "vsPivotPct" | "workflow" | "results";
  const TRADE_SORT_KEYS: TradeSortKey[] = ["symbol", "sector", "RS_Rank", "Passed", "pivotDate", "pivotPrice", "latest", "vsPivotPct", "workflow", "results"];
  const [sortKey, setSortKeyRaw] = useState<TradeSortKey>(() => {
    try {
      const v = localStorage.getItem("trade-monitor-sort-key") as TradeSortKey;
      if (TRADE_SORT_KEYS.includes(v)) return v;
    } catch { /* ignore */ }
    return "RS_Rank";
  });
  const [sortDir, setSortDirRaw] = useState<"asc" | "desc">(() => {
    try {
      const v = localStorage.getItem("trade-monitor-sort-dir");
      if (v === "asc" || v === "desc") return v;
    } catch { /* ignore */ }
    return "desc";
  });

  function setSortKey(k: TradeSortKey) {
    setSortKeyRaw(k);
    try { localStorage.setItem("trade-monitor-sort-key", k); } catch { /* ignore */ }
  }
  function setSortDir(d: "asc" | "desc") {
    setSortDirRaw(d);
    try { localStorage.setItem("trade-monitor-sort-dir", d); } catch { /* ignore */ }
  }

  function toggleSort(k: TradeSortKey) {
    if (sortKey === k) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
      return;
    }
    setSortKey(k);
    setSortDir(k === "symbol" || k === "sector" || k === "pivotDate" || k === "workflow" ? "asc" : "desc");
  }

  const symbols = useMemo(
    () => entries.map(e => e.row.symbol).filter((s): s is string => !!s),
    [entries]
  );

  useEffect(() => {
    if (symbols.length === 0) return;
    let cancelled = false;

    async function fetchQuotes() {
      const cached = await getCachedQuotes<FmpQuote>(symbols);
      if (cancelled) return;
      if (Object.keys(cached).length > 0) setQuotes(prev => ({ ...prev, ...cached }));

      const missing = symbols.filter(s => !(s in cached));
      if (missing.length === 0) return;

      setLoadingQuotes(true);
      const fresh: Record<string, FmpQuote | null> = {};
      await Promise.all(
        missing.map(async sym => {
          try {
            const res = await fmpGetQuote(sym);
            if (!res.ok) {
              fresh[sym] = null;
              return;
            }
            const data = res.data;
            fresh[sym] = Array.isArray(data) ? (data[0] ?? null) : null;
          } catch {
            fresh[sym] = null;
          }
        })
      );

      if (cancelled) return;
      setQuotes(prev => ({ ...prev, ...fresh }));
      const toCache: Record<string, FmpQuote> = {};
      for (const [sym, q] of Object.entries(fresh)) {
        if (q != null) toCache[sym] = q;
      }
      if (Object.keys(toCache).length > 0) setCachedQuotes(toCache);
    }

    fetchQuotes().finally(() => {
      if (!cancelled) setLoadingQuotes(false);
    });

    return () => {
      cancelled = true;
    };
  }, [symbols.join(",")]);

  const sorted = useMemo(() => {
    const out = [...entries];
    out.sort((a, b) => {
      const symA = a.row.symbol ?? "";
      const symB = b.row.symbol ?? "";
      const qA = quotes[symA];
      const qB = quotes[symB];
      const dA = qA?.price != null ? qA.price - a.pivot.price : null;
      const dB = qB?.price != null ? qB.price - b.pivot.price : null;
      const dpA = dA != null && Math.abs(a.pivot.price) > 1e-9 ? (dA / a.pivot.price) * 100 : null;
      const dpB = dB != null && Math.abs(b.pivot.price) > 1e-9 ? (dB / b.pivot.price) * 100 : null;
      const stA = getStatus(symA);
      const stB = getStatus(symB);
      const inA = filteredSymbolSet.has(symA);
      const inB = filteredSymbolSet.has(symB);

      let cmp = 0;
      if (sortKey === "symbol") cmp = symA.localeCompare(symB);
      else if (sortKey === "sector") cmp = (a.row.sector ?? "").localeCompare(b.row.sector ?? "");
      else if (sortKey === "RS_Rank") cmp = (a.row.RS_Rank ?? -1) - (b.row.RS_Rank ?? -1);
      else if (sortKey === "Passed") cmp = Number(a.row.Passed) - Number(b.row.Passed);
      else if (sortKey === "pivotDate") cmp = a.pivot.date.localeCompare(b.pivot.date);
      else if (sortKey === "pivotPrice") cmp = a.pivot.price - b.pivot.price;
      else if (sortKey === "latest") cmp = (qA?.price ?? -Infinity) - (qB?.price ?? -Infinity);
      else if (sortKey === "vsPivotPct") cmp = (dpA ?? -Infinity) - (dpB ?? -Infinity);
      else if (sortKey === "workflow") cmp = stA.localeCompare(stB);
      else if (sortKey === "results") cmp = Number(inA) - Number(inB);

      if (cmp === 0) cmp = symA.localeCompare(symB);
      return sortDir === "asc" ? cmp : -cmp;
    });
    return out;
  }, [entries, quotes, getStatus, filteredSymbolSet, sortKey, sortDir]);

  function ColHd({ label, col, align = "left" }: { label: string; col: TradeSortKey; align?: "left" | "center" | "right" }) {
    const active = sortKey === col;
    const alignClass = align === "center" ? "text-center" : align === "right" ? "text-right" : "text-left";
    return (
      <th
        onClick={() => toggleSort(col)}
        className={`px-3 py-2 text-xs font-medium text-muted-foreground uppercase tracking-wide whitespace-nowrap cursor-pointer select-none hover:text-foreground ${alignClass} ${active ? "text-foreground" : ""}`}
      >
        {label}{active ? (sortDir === "asc" ? " ↑" : " ↓") : ""}
      </th>
    );
  }

  if (entries.length === 0) {
    return (
      <p className="text-sm text-muted-foreground py-8 text-center">
        No pivot markers yet. Set a pivot on the Charts tab (right-click the chart).
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="space-y-1">
        <h3 className="text-sm font-semibold text-foreground">Pivot overview</h3>
        <p className="text-sm text-muted-foreground">
          All tickers in this run with a saved chart pivot. Charts still draw the pivot dot and ray; open a row to review price vs pivot on the Charts tab.
        </p>
      </div>
      {loadingQuotes && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="w-4 h-4 animate-spin" />
          Loading latest prices…
        </div>
      )}
      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full text-sm">
          <thead className="bg-muted/40 border-b border-border">
            <tr>
              <ColHd label="Symbol" col="symbol" />
              <ColHd label="Sector" col="sector" />
              <ColHd label="RS" col="RS_Rank" align="center" />
              <ColHd label="Tech" col="Passed" align="center" />
              <ColHd label="Pivot date" col="pivotDate" />
              <ColHd label="Pivot" col="pivotPrice" align="right" />
              <ColHd label="Latest" col="latest" align="right" />
              <ColHd label="Vs pivot" col="vsPivotPct" align="right" />
              <ColHd label="Workflow" col="workflow" align="center" />
              <ColHd label="Results" col="results" align="center" />
              <th className="px-3 py-2 text-right text-xs font-medium text-muted-foreground uppercase tracking-wide" aria-hidden />
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {sorted.map(({ row, pivot }) => {
              const sym = row.symbol!;
              const sel = sym === selectedTicker;
              const st = getStatus(sym);
              const inFilter = filteredSymbolSet.has(sym);
              const q = quotes[sym];
              const latest = q?.price ?? null;
              const d = latest != null ? latest - pivot.price : null;
              const dp = d != null && Math.abs(pivot.price) > 1e-9 ? (d / pivot.price) * 100 : null;
              const distColor = d == null ? "text-muted-foreground" : d >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-rose-500";
              const loggingThis = logTradeTicker === sym;
              return (
                <>
                  <tr
                    key={row.scan_row_id}
                    onClick={() => onSelect(sym)}
                    onDoubleClick={() => onOpenWorkflowEditor(sym)}
                    className={`cursor-pointer transition-colors ${sel ? "bg-foreground/10 ring-1 ring-inset ring-foreground/20" : "hover:bg-muted/30"}`}
                  >
                    <td className="px-3 py-2 font-mono font-semibold whitespace-nowrap">{sym}</td>
                    <td className="px-3 py-2 text-xs text-muted-foreground max-w-[140px] truncate" title={row.sector || undefined}>
                      {row.sector || "—"}
                    </td>
                    <td className="px-3 py-2 text-center"><RsBadge rank={row.RS_Rank} /></td>
                    <td className="px-3 py-2 text-center"><Check value={row.Passed} /></td>
                    <td className="px-3 py-2 text-muted-foreground whitespace-nowrap">{pivot.date}</td>
                    <td className="px-3 py-2 text-right tabular-nums">${pivot.price.toFixed(2)}</td>
                    <td className="px-3 py-2 text-right tabular-nums font-medium">
                      {latest != null ? `$${latest.toFixed(2)}` : "—"}
                    </td>
                    <td className={`px-3 py-2 text-right tabular-nums whitespace-nowrap ${distColor}`}>
                      {d == null || dp == null ? "—" : `${d >= 0 ? "+" : ""}${d.toFixed(2)} (${dp >= 0 ? "+" : ""}${dp.toFixed(2)}%)`}
                    </td>
                    <td className="px-3 py-2 text-center">
                      <span className="text-xs text-muted-foreground capitalize">{st}</span>
                    </td>
                    <td className="px-3 py-2 text-center">
                      {inFilter ? (
                        <span className="text-[11px] text-emerald-600 dark:text-emerald-400">Shown</span>
                      ) : (
                        <span className="text-[11px] text-muted-foreground" title="Hidden by current Results filters — still on chart list">
                          Outside filter
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-right whitespace-nowrap">
                      <div className="flex items-center justify-end gap-3">
                        <button
                          type="button"
                          onClick={e => {
                            e.stopPropagation();
                            setLogTradeTicker(loggingThis ? null : sym);
                          }}
                          className={`flex items-center gap-1 text-xs font-medium transition-colors ${loggingThis ? "text-muted-foreground hover:text-foreground" : "text-emerald-600 hover:text-emerald-700 dark:text-emerald-400 dark:hover:text-emerald-300"}`}
                          title="Log a trade for this ticker"
                        >
                          <Plus className="w-3 h-3" />
                          {loggingThis ? "Cancel" : "Log trade"}
                        </button>
                        <button
                          type="button"
                          onClick={e => {
                            e.stopPropagation();
                            onSelect(sym);
                            onGoToCharts();
                          }}
                          className="text-xs font-medium text-sky-600 hover:underline dark:text-sky-400"
                        >
                          Open chart
                        </button>
                      </div>
                    </td>
                  </tr>
                  {loggingThis && (
                    <tr key={`${row.scan_row_id}-log-form`}>
                      <td colSpan={11} className="px-3 py-3 bg-muted/20">
                        <LogTradeForm
                          ticker={sym}
                          defaultPrice={latest}
                          onDone={() => setLogTradeTicker(null)}
                          onCancel={() => setLogTradeTicker(null)}
                        />
                      </td>
                    </tr>
                  )}
                </>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─── main component ──────────────────────────────────────────────────────────

const TECH_CRITERIA: { key: keyof ScreeningRow; short: string; label: string }[] = [
  { key: "PriceOverSMA150And200", short: "P>SMA", label: "Price > SMA150 & SMA200" },
  { key: "SMA150AboveSMA200", short: "150>200", label: "SMA150 > SMA200" },
  { key: "SMA50AboveSMA150And200", short: "50>150", label: "SMA50 > SMA150 & SMA200" },
  { key: "SMA200Slope", short: "200↗", label: "SMA200 Uptrending" },
  { key: "PriceAbove25Percent52WeekLow", short: ">Low", label: "Price > 52wk Low +25%" },
  { key: "PriceWithin25Percent52WeekHigh", short: "<High", label: "Price within 25% of 52wk High" },
  { key: "RSOver70", short: "RS>70", label: "RS > 70" },
];

export function ScreeningsUI({
  runs,
  rows,
  selectedRunId,
  vectorTickers,
  companyVectorDimensions,
  initialNotes = [],
}: {
  runs: ScanRun[];
  rows: ScreeningRow[];
  selectedRunId: number | null;
  vectorTickers: Set<string>;
  companyVectorDimensions: Record<string, Record<string, number>>;
  initialNotes?: ScanRowNote[];
}) {
  const router = useRouter();
  const [search, setSearch] = useState("");
  const [filters, setFiltersState] = useState<Filters>(DEFAULT_FILTERS);

  const setFilters = useCallback((f: Filters | ((prev: Filters) => Filters)) => {
    setFiltersState((prev) => {
      const next = typeof f === "function" ? f(prev) : f;
      try {
        localStorage.setItem("screenings-filters", JSON.stringify(next));
      } catch {
        /* ignore */
      }
      return next;
    });
  }, []);
  const [sortKey, setSortKeyState] = useState<SortKey>("RS_Rank");
  const [sortDir, setSortDirState] = useState<SortDir>("desc");

  function setSortKey(k: SortKey) {
    setSortKeyState(k);
    try { localStorage.setItem("screenings-sort-key", k); } catch { /* ignore */ }
  }
  function setSortDir(d: SortDir | ((prev: SortDir) => SortDir)) {
    setSortDirState(prev => {
      const next = typeof d === "function" ? d(prev) : d;
      try { localStorage.setItem("screenings-sort-dir", next); } catch { /* ignore */ }
      return next;
    });
  }
  const [activeView, setActiveView] = useState<ViewTab>("results");
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);
  const [workflowEditor, setWorkflowEditor] = useState<{
    scanRowId: number;
    ticker: string;
    status: NoteStatus;
    comment: string;
  } | null>(null);
  const [savingWorkflowEditor, setSavingWorkflowEditor] = useState(false);
  const [deletingRunId, setDeletingRunId] = useState<number | null>(null);

  // Load persisted UI preferences only after hydration to avoid SSR/client mismatch.
  useEffect(() => {
    try {
      const storedFilters = localStorage.getItem("screenings-filters");
      if (storedFilters) {
        const parsed = JSON.parse(storedFilters) as Record<string, unknown>;
        const legacy = parsed as {
          dynamicTruthys?: Record<string, boolean>;
          dynamicNumericMins?: Record<string, string>;
        };
        const statusRaw = parsed.status;
        const nh = parsed.noteHighlighted;
        const nc = parsed.noteComment;
        const tagsRaw = parsed.noteTagsAny;
        setFiltersState({
          ...DEFAULT_FILTERS,
          ...(typeof statusRaw === "string" ? { status: statusRaw as Filters["status"] } : {}),
          ...(nh === "any" || nh === "yes" || nh === "no" ? { noteHighlighted: nh } : {}),
          ...(nc === "any" || nc === "with" || nc === "without" ? { noteComment: nc } : {}),
          ...(typeof parsed.noteStage === "string" ? { noteStage: parsed.noteStage } : {}),
          ...(typeof parsed.notePriorityMin === "string"
            ? { notePriorityMin: parsed.notePriorityMin }
            : {}),
          ...(typeof parsed.notePriorityMax === "string"
            ? { notePriorityMax: parsed.notePriorityMax }
            : {}),
          ...(typeof parsed.notePriorityGt === "string"
            ? { notePriorityGt: parsed.notePriorityGt }
            : {}),
          ...(typeof parsed.notePriorityLt === "string"
            ? { notePriorityLt: parsed.notePriorityLt }
            : {}),
          ...(typeof parsed.notePriorityEq === "string"
            ? { notePriorityEq: parsed.notePriorityEq }
            : {}),
          ...(Array.isArray(tagsRaw)
            ? {
                noteTagsAny: tagsRaw.filter((t): t is string => typeof t === "string"),
              }
            : {}),
          boolRequire: {
            ...DEFAULT_FILTERS.boolRequire,
            ...((parsed.boolRequire as Record<string, boolean> | undefined) ?? {}),
            ...(legacy.dynamicTruthys ?? {}),
          },
          boolReject: {
            ...DEFAULT_FILTERS.boolReject,
            ...((parsed.boolReject as Record<string, boolean> | undefined) ?? {}),
          },
          numMin: {
            ...DEFAULT_FILTERS.numMin,
            ...((parsed.numMin as Record<string, string> | undefined) ?? {}),
            ...(legacy.dynamicNumericMins ?? {}),
          },
          numMax: {
            ...DEFAULT_FILTERS.numMax,
            ...((parsed.numMax as Record<string, string> | undefined) ?? {}),
          },
          numGt: {
            ...DEFAULT_FILTERS.numGt,
            ...((parsed.numGt as Record<string, string> | undefined) ?? {}),
          },
          numLt: {
            ...DEFAULT_FILTERS.numLt,
            ...((parsed.numLt as Record<string, string> | undefined) ?? {}),
          },
          stringOneOf: {
            ...DEFAULT_FILTERS.stringOneOf,
            ...((parsed.stringOneOf as Record<string, string[]> | undefined) ?? {}),
          },
          stringContains: {
            ...DEFAULT_FILTERS.stringContains,
            ...((parsed.stringContains as Record<string, string> | undefined) ?? {}),
          },
          stringEquals: {
            ...DEFAULT_FILTERS.stringEquals,
            ...((parsed.stringEquals as Record<string, string> | undefined) ?? {}),
          },
        });
      }
    } catch {
      // ignore malformed storage
    }

    try {
      const v = localStorage.getItem("screenings-sort-key");
      if (typeof v === "string" && v.length > 0 && v.length < 200) {
        setSortKeyState(v);
      }
    } catch {
      // ignore malformed storage
    }

    try {
      const v = localStorage.getItem("screenings-sort-dir");
      if (v === "asc" || v === "desc") {
        setSortDirState(v);
      }
    } catch {
      // ignore malformed storage
    }
  }, []);

  // ── Row-level workflow annotations ───────────────────────────────────────
  const [rowNotes, setRowNotes] = useState<Map<number, ScanRowNote>>(
    () => new Map(initialNotes.map(n => [n.scan_row_id, n]))
  );

  useEffect(() => {
    setRowNotes(new Map(initialNotes.map((n) => [n.scan_row_id, n])));
  }, [selectedRunId, initialNotes]);

  const rowBySymbol = useMemo(() => {
    const map = new Map<string, ScreeningRow>();
    for (const row of rows) {
      if (!row.symbol || map.has(row.symbol)) continue;
      map.set(row.symbol, row);
    }
    return map;
  }, [rows]);

  const dismissedSymbols = useMemo(() => {
    const symbols = new Set<string>();
    for (const row of rows) {
      const note = rowNotes.get(row.scan_row_id);
      if (note?.status === "dismissed" && row.symbol) symbols.add(row.symbol);
    }
    return symbols;
  }, [rows, rowNotes]);

  const dismissedCount = useMemo(() => {
    let count = 0;
    for (const note of rowNotes.values()) {
      if (note.status === "dismissed") count++;
    }
    return count;
  }, [rowNotes]);

  const noteStageOptions = useMemo(() => {
    const s = new Set<string>();
    for (const n of rowNotes.values()) {
      const st = n.stage?.trim();
      if (st) s.add(st);
    }
    return [...s].sort((a, b) => a.localeCompare(b));
  }, [rowNotes]);

  const noteTagOptions = useMemo(() => {
    const s = new Set<string>();
    for (const n of rowNotes.values()) {
      for (const t of n.tags ?? []) {
        const u = String(t).trim();
        if (u) s.add(u);
      }
    }
    return [...s].sort((a, b) => a.localeCompare(b));
  }, [rowNotes]);

  const tradeMonitoringRows = useMemo(() => {
    const out: { row: ScreeningRow; pivot: PivotMarker }[] = [];
    for (const row of rows) {
      if (!row.symbol) continue;
      const p = pivotFromMetadata(rowNotes.get(row.scan_row_id)?.metadata_json);
      if (p) out.push({ row, pivot: p });
    }
    out.sort((a, b) => (a.row.symbol ?? "").localeCompare(b.row.symbol ?? ""));
    return out;
  }, [rows, rowNotes]);

  const hasAnyPivotMarkers = tradeMonitoringRows.length > 0;

  useEffect(() => {
    if (activeView === "tradeMonitoring" && !hasAnyPivotMarkers) {
      setActiveView("charts");
    }
  }, [activeView, hasAnyPivotMarkers]);

  async function upsertRowNote(row: ScreeningRow, patch: {
    status?: NoteStatus;
    highlighted?: boolean;
    comment?: string | null;
    metadataJson?: Record<string, unknown>;
  }) {
    const now = new Date().toISOString();
    const prev = rowNotes.get(row.scan_row_id);
    const next: ScanRowNote = {
      scan_row_id: row.scan_row_id,
      run_id: row.run_id,
      ticker: row.symbol,
      user_id: prev?.user_id ?? "",
      status: patch.status ?? prev?.status ?? "active",
      highlighted: patch.highlighted ?? prev?.highlighted ?? false,
      comment: patch.comment !== undefined ? patch.comment : (prev?.comment ?? null),
      stage: prev?.stage ?? null,
      priority: prev?.priority ?? null,
      tags: prev?.tags ?? [],
      metadata_json: patch.metadataJson ?? prev?.metadata_json ?? {},
      created_at: prev?.created_at ?? now,
      updated_at: now,
    };

    setRowNotes(prevMap => new Map(prevMap).set(row.scan_row_id, next));
    try {
      const res = await screeningsUpsertDismissNote({
        scanRowId: row.scan_row_id,
        runId: row.run_id,
        ticker: row.symbol,
        status: next.status,
        highlighted: next.highlighted,
        comment: next.comment,
        metadataJson: next.metadata_json,
      });
      if (!res.ok) throw new Error(res.error);
    } catch {
      setRowNotes(prevMap => {
        const m = new Map(prevMap);
        if (prev) m.set(row.scan_row_id, prev);
        else m.delete(row.scan_row_id);
        return m;
      });
    }
  }

  async function dismissTicker(ticker: string) {
    const row = rowBySymbol.get(ticker);
    if (!row) return;
    await upsertRowNote(row, { status: "dismissed" });
    if (selectedTicker === ticker) setSelectedTicker(null);
  }

  async function restoreTicker(ticker: string) {
    const row = rowBySymbol.get(ticker);
    if (!row) return;
    await upsertRowNote(row, { status: "active" });
  }

  async function toggleHighlight(row: ScreeningRow) {
    const current = rowNotes.get(row.scan_row_id)?.highlighted ?? false;
    await upsertRowNote(row, { highlighted: !current });
  }

  function openWorkflowModalForRow(row: ScreeningRow) {
    const current = rowNotes.get(row.scan_row_id);
    setWorkflowEditor({
      scanRowId: row.scan_row_id,
      ticker: row.symbol,
      status: current?.status ?? "active",
      comment: current?.comment ?? "",
    });
  }

  async function editComment(row: ScreeningRow) {
    openWorkflowModalForRow(row);
  }

  function getTickerStatus(ticker: string): NoteStatus {
    const row = rowBySymbol.get(ticker);
    if (!row) return "active";
    return rowNotes.get(row.scan_row_id)?.status ?? "active";
  }

  function tickerHasComment(ticker: string): boolean {
    const row = rowBySymbol.get(ticker);
    if (!row) return false;
    return !!rowNotes.get(row.scan_row_id)?.comment;
  }

  function getTickerMeta(ticker: string): { sector: string; industry: string } {
    const row = rowBySymbol.get(ticker);
    return {
      sector: row?.sector ?? "",
      industry: row?.industry ?? row?.subSector ?? "",
    };
  }

  async function setTickerStatus(ticker: string, status: NoteStatus) {
    if (status === "dismissed") {
      await dismissTicker(ticker);
      return;
    }
    if (status === "active") {
      await restoreTicker(ticker);
      return;
    }
    const row = rowBySymbol.get(ticker);
    if (!row) return;
    await upsertRowNote(row, { status });
  }

  async function editTickerComment(ticker: string) {
    const row = rowBySymbol.get(ticker);
    if (!row) return;
    openWorkflowModalForRow(row);
  }

  function getTickerPivotMarker(ticker: string): PivotMarker | null {
    const row = rowBySymbol.get(ticker);
    if (!row) return null;
    return pivotFromMetadata(rowNotes.get(row.scan_row_id)?.metadata_json);
  }

  async function setTickerPivotMarker(ticker: string, point: ChartPoint) {
    const row = rowBySymbol.get(ticker);
    if (!row) return;
    const prev = rowNotes.get(row.scan_row_id);
    const rest = { ...(prev?.metadata_json ?? {}) };
    delete (rest as { pivot_points?: unknown }).pivot_points;
    const nextMetadata: Record<string, unknown> = {
      ...rest,
      pivot: { barIdx: point.barIdx, date: point.date, price: point.price },
    };
    await upsertRowNote(row, { metadataJson: nextMetadata });
  }

  async function clearTickerPivotMarker(ticker: string) {
    const row = rowBySymbol.get(ticker);
    if (!row) return;
    const prev = rowNotes.get(row.scan_row_id);
    const rest = { ...(prev?.metadata_json ?? {}) };
    delete (rest as { pivot?: unknown }).pivot;
    delete (rest as { pivot_points?: unknown }).pivot_points;
    await upsertRowNote(row, { metadataJson: rest });
  }

  function openTickerWorkflowEditor(ticker: string) {
    const row = rowBySymbol.get(ticker);
    if (!row) return;
    openWorkflowModalForRow(row);
  }

  async function saveWorkflowEditor() {
    if (!workflowEditor) return;
    const row = rows.find(r => r.scan_row_id === workflowEditor.scanRowId);
    if (!row) {
      setWorkflowEditor(null);
      return;
    }
    setSavingWorkflowEditor(true);
    try {
      const nextStatus = workflowEditor.status;
      const nextComment = workflowEditor.comment.trim() ? workflowEditor.comment.trim() : null;
      await upsertRowNote(row, { status: nextStatus, comment: nextComment });
      if (nextStatus === "dismissed" && selectedTicker === row.symbol) {
        setSelectedTicker(null);
      }
      setWorkflowEditor(null);
    } finally {
      setSavingWorkflowEditor(false);
    }
  }

  const rowDataKeySet = useMemo(() => collectAllRowDataKeys(rows), [rows]);

  const dataColumnKeys = useMemo(
    () => orderedDataColumnKeys(rowDataKeySet),
    [rowDataKeySet],
  );

  const boolFilterKeys = useMemo(
    () => [...inferBooleanFilterKeys(rows, dataColumnKeys)].sort((a, b) => a.localeCompare(b)),
    [rows, dataColumnKeys],
  );

  const numFilterKeys = useMemo(
    () => [...inferNumericFilterKeys(rows, dataColumnKeys)].sort((a, b) => a.localeCompare(b)),
    [rows, dataColumnKeys],
  );

  const { categoricalStringCols, freeStringKeys } = useMemo(() => {
    const cat: { key: string; options: string[] }[] = [];
    const free: string[] = [];
    for (const k of dataColumnKeys) {
      if (isBooleanColumn(rows, k) || isNumericColumn(rows, k)) continue;
      const opts = uniqueStringValuesForKey(rows, k);
      if (opts.length === 0) continue;
      if (opts.length <= MAX_CATEGORICAL_STRING_OPTIONS) {
        cat.push({ key: k, options: opts });
      } else {
        free.push(k);
      }
    }
    free.sort((a, b) => a.localeCompare(b));
    return { categoricalStringCols: cat, freeStringKeys: free };
  }, [rows, dataColumnKeys]);

  useEffect(() => {
    if (rows.length === 0) return;
    const ok = sortKey === "symbol" || dataColumnKeys.includes(sortKey);
    if (ok) return;
    const next =
      dataColumnKeys.includes("RS_Rank")
        ? "RS_Rank"
        : dataColumnKeys.includes("Passed")
          ? "Passed"
          : (dataColumnKeys[0] ?? "symbol");
    setSortKeyState(next);
    setSortDirState(
      next === "symbol" || ["sector", "industry", "subSector"].includes(next) ? "asc" : "desc",
    );
  }, [rows.length, dataColumnKeys, sortKey]);

  function selectRun(id: number) {
    router.push(`/protected/screenings?run=${id}`);
  }

  async function softDeleteRun(runId: number) {
    if (
      !window.confirm(
        "Remove this screening from your list? Data stays in the database but it will no longer appear here.",
      )
    ) {
      return;
    }
    setDeletingRunId(runId);
    try {
      const res = await screeningsSoftDeleteRun(runId);
      if (!res.ok) {
        window.alert(res.error);
        return;
      }
      const wasSelected = selectedRunId === runId;
      const others = runs.filter((r) => r.id !== runId);
      if (wasSelected) {
        if (others[0]) {
          router.push(`/protected/screenings?run=${others[0].id}`);
        } else {
          router.push("/protected/screenings");
        }
      }
      router.refresh();
    } finally {
      setDeletingRunId(null);
    }
  }

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      const ascDefault =
        key === "symbol" || key === "sector" || key === "industry" || key === "subSector";
      setSortDir(ascDefault ? "asc" : "desc");
    }
  }

  const filtered = useMemo(() => {
    let result = rows.filter((r) => {
      const note = rowNotes.get(r.scan_row_id);
      const status = note?.status ?? "active";
      if (filters.status !== "all" && status !== filters.status) return false;

      const highlighted = note?.highlighted ?? false;
      if (filters.noteHighlighted === "yes" && !highlighted) return false;
      if (filters.noteHighlighted === "no" && highlighted) return false;

      const commentTrim = note?.comment?.trim() ?? "";
      if (filters.noteComment === "with" && !commentTrim) return false;
      if (filters.noteComment === "without" && commentTrim) return false;

      if (filters.noteStage) {
        const st = note?.stage?.trim() ?? "";
        if (filters.noteStage === NOTE_STAGE_NONE) {
          if (st) return false;
        } else if (st !== filters.noteStage) {
          return false;
        }
      }

      const pminStr = filters.notePriorityMin.trim();
      if (pminStr) {
        const pmin = parseFloat(pminStr);
        if (Number.isFinite(pmin)) {
          const p = note?.priority;
          if (p == null || !Number.isFinite(p) || p < pmin) return false;
        }
      }
      const pmaxStr = filters.notePriorityMax.trim();
      if (pmaxStr) {
        const pmax = parseFloat(pmaxStr);
        if (Number.isFinite(pmax)) {
          const p = note?.priority;
          if (p == null || !Number.isFinite(p) || p > pmax) return false;
        }
      }
      const pgtNote = filters.notePriorityGt.trim();
      if (pgtNote) {
        const bound = parseFloat(pgtNote);
        if (Number.isFinite(bound)) {
          const p = note?.priority;
          if (p == null || !Number.isFinite(p) || p <= bound) return false;
        }
      }
      const pltNote = filters.notePriorityLt.trim();
      if (pltNote) {
        const bound = parseFloat(pltNote);
        if (Number.isFinite(bound)) {
          const p = note?.priority;
          if (p == null || !Number.isFinite(p) || p >= bound) return false;
        }
      }

      if (filters.noteTagsAny.length > 0) {
        const rowTags = new Set(
          (note?.tags ?? []).map((t) => String(t).trim()).filter(Boolean),
        );
        const any = filters.noteTagsAny.some((t) => rowTags.has(t));
        if (!any) return false;
      }

      for (const [k, on] of Object.entries(filters.boolRequire)) {
        if (on && !getRowDataValue(r, k)) return false;
      }
      for (const [k, on] of Object.entries(filters.boolReject)) {
        if (on && getRowDataValue(r, k)) return false;
      }

      for (const [k, minStr] of Object.entries(filters.numMin)) {
        const t = minStr?.trim();
        if (!t) continue;
        const min = parseFloat(t);
        if (!Number.isFinite(min)) continue;
        const v = getRowDataValue(r, k);
        const n = typeof v === "number" ? v : parseFloat(String(v));
        if (!Number.isFinite(n) || n < min) return false;
      }
      for (const [k, maxStr] of Object.entries(filters.numMax)) {
        const t = maxStr?.trim();
        if (!t) continue;
        const max = parseFloat(t);
        if (!Number.isFinite(max)) continue;
        const v = getRowDataValue(r, k);
        const n = typeof v === "number" ? v : parseFloat(String(v));
        if (!Number.isFinite(n) || n > max) return false;
      }
      for (const [k, gtStr] of Object.entries(filters.numGt)) {
        const t = gtStr?.trim();
        if (!t) continue;
        const gt = parseFloat(t);
        if (!Number.isFinite(gt)) continue;
        const v = getRowDataValue(r, k);
        const n = typeof v === "number" ? v : parseFloat(String(v));
        if (!Number.isFinite(n) || n <= gt) return false;
      }
      for (const [k, ltStr] of Object.entries(filters.numLt)) {
        const t = ltStr?.trim();
        if (!t) continue;
        const lt = parseFloat(t);
        if (!Number.isFinite(lt)) continue;
        const v = getRowDataValue(r, k);
        const n = typeof v === "number" ? v : parseFloat(String(v));
        if (!Number.isFinite(n) || n >= lt) return false;
      }

      for (const [k, allowed] of Object.entries(filters.stringOneOf)) {
        if (!allowed.length) continue;
        const s = stringifyRowDataValueForFilter(getRowDataValue(r, k));
        if (!allowed.includes(s)) return false;
      }
      for (const [k, sub] of Object.entries(filters.stringContains)) {
        const needle = sub.trim().toLowerCase();
        if (!needle) continue;
        const hay = stringifyRowDataValueForFilter(getRowDataValue(r, k)).toLowerCase();
        if (!hay.includes(needle)) return false;
      }
      for (const [k, exact] of Object.entries(filters.stringEquals)) {
        const want = exact.trim();
        if (!want) continue;
        const s = stringifyRowDataValueForFilter(getRowDataValue(r, k));
        if (s !== want) return false;
      }

      return true;
    });

    if (search.trim()) {
      const q = search.trim().toLowerCase();
      result = result.filter((r) => {
        if (r.symbol?.toLowerCase().includes(q)) return true;
        for (const v of Object.values(r.rowData)) {
          if (v == null) continue;
          if (typeof v === "object") {
            try {
              if (JSON.stringify(v).toLowerCase().includes(q)) return true;
            } catch {
              /* ignore */
            }
          } else if (String(v).toLowerCase().includes(q)) return true;
        }
        return false;
      });
    }

    result = [...result].sort((a, b) => {
      let cmp = 0;
      if (sortKey === "symbol") cmp = (a.symbol ?? "").localeCompare(b.symbol ?? "");
      else
        cmp = compareRowDataValues(getRowDataValue(a, sortKey), getRowDataValue(b, sortKey));
      return sortDir === "asc" ? cmp : -cmp;
    });

    return result;
  }, [rows, rowNotes, filters, search, sortKey, sortDir]);

  const filteredSymbols = useMemo(() => filtered.map(r => r.symbol).filter(Boolean) as string[], [filtered]);

  /** Chart carousel includes filtered symbols first, then any pivot-marked tickers not in the current filter so pivots always stay on-chart. */
  const chartSymbols = useMemo(() => {
    const seen = new Set<string>();
    const out: string[] = [];
    for (const s of filteredSymbols) {
      if (!seen.has(s)) {
        seen.add(s);
        out.push(s);
      }
    }
    const extras = tradeMonitoringRows
      .map(e => e.row.symbol)
      .filter((s): s is string => !!s && !seen.has(s));
    extras.sort((a, b) => a.localeCompare(b));
    for (const s of extras) {
      seen.add(s);
      out.push(s);
    }
    return out;
  }, [filteredSymbols, tradeMonitoringRows]);

  const filteredSymbolSet = useMemo(() => new Set(filteredSymbols), [filteredSymbols]);

  const selectedRun = runs.find(r => r.id === selectedRunId) ?? runs[0] ?? null;

  function SortIcon({ col }: { col: SortKey }) {
    if (sortKey !== col) return null;
    return sortDir === "asc"
      ? <ChevronUp className="w-3 h-3 inline ml-0.5" />
      : <ChevronDown className="w-3 h-3 inline ml-0.5" />;
  }

  function Th({ col, children, center }: { col: SortKey; children: React.ReactNode; center?: boolean }) {
    return (
      <th
        className={`px-3 py-2 text-xs font-medium text-muted-foreground uppercase tracking-wide cursor-pointer select-none hover:text-foreground whitespace-nowrap ${center ? "text-center" : "text-left"}`}
        onClick={() => toggleSort(col)}
      >
        {children}<SortIcon col={col} />
      </th>
    );
  }

  const primaryViewTabs: { id: ViewTab; label: string; icon: React.ReactNode }[] = [
    { id: "results", label: "Results", icon: <List className="w-3.5 h-3.5" /> },
    { id: "quotes", label: "Quotes", icon: <TrendingUp className="w-3.5 h-3.5" /> },
    { id: "charts", label: "Charts", icon: <BarChart2 className="w-3.5 h-3.5" /> },
    { id: "news", label: "News Trend", icon: <Newspaper className="w-3.5 h-3.5" /> },
    { id: "sentiment", label: "Sentiment", icon: <Gauge className="w-3.5 h-3.5" /> },
    { id: "relationship", label: "Relationships", icon: <Activity className="w-3.5 h-3.5" /> },
  ];

  const tradeMonitoringDisabled = !hasAnyPivotMarkers;
  const tradeMonitoringTitle = tradeMonitoringDisabled
    ? "Set a pivot on the Charts tab (right-click) to enable this view"
    : undefined;

  function columnHeaderLabel(key: string): string {
    const tech = TECH_CRITERIA.find((t) => t.key === key);
    if (tech) return tech.short;
    if (key.length > 20) return `${key.slice(0, 18)}…`;
    return key;
  }

  return (
    <div className="flex flex-col gap-4 min-h-0 w-full">
      {/* Scan runs — horizontal selector (scrolls when many runs) */}
      <div className="flex flex-col gap-2 shrink-0">
        <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Scan runs</p>
        {runs.length === 0 ? (
          <p className="text-sm text-muted-foreground">No runs yet.</p>
        ) : (
          <div className="flex gap-2 overflow-x-auto pb-1 -mx-1 px-1 [scrollbar-width:thin]">
            {runs.map(run => {
              const active = run.id === (selectedRun?.id ?? null);
              const busy = deletingRunId === run.id;
              return (
                <div
                  key={run.id}
                  className={`relative shrink-0 group min-w-[9.5rem] max-w-[220px] rounded-lg border flex flex-col ${
                    active
                      ? "border-foreground bg-foreground text-background"
                      : "border-border bg-background text-muted-foreground"
                  }`}
                >
                  <button
                    type="button"
                    onClick={() => selectRun(run.id)}
                    disabled={busy}
                    className={`text-left px-3 pt-2 pb-1.5 pr-8 text-sm transition-colors rounded-t-lg ${
                      active
                        ? "font-medium"
                        : "hover:bg-muted hover:text-foreground hover:border-foreground/30"
                    } ${busy ? "opacity-60" : ""}`}
                  >
                    <div className="font-medium leading-tight">{run.scan_date}</div>
                    <div className="text-xs opacity-80 truncate mt-0.5" title={run.source}>{run.source}</div>
                  </button>
                  <button
                    type="button"
                    title="Remove from list"
                    aria-label={`Remove screening ${run.scan_date}`}
                    disabled={busy}
                    onClick={(e) => {
                      e.stopPropagation();
                      void softDeleteRun(run.id);
                    }}
                    className={`absolute right-1 top-1 p-1 rounded-md transition-colors ${
                      active
                        ? "text-background/70 hover:text-background hover:bg-background/15"
                        : "text-muted-foreground hover:text-destructive hover:bg-destructive/10"
                    } ${busy ? "pointer-events-none opacity-50" : ""}`}
                  >
                    {busy ? (
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    ) : (
                      <Trash2 className="w-3.5 h-3.5" />
                    )}
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Main panel */}
      <div className="flex-1 min-w-0 flex flex-col gap-4">
        {/* Search + count */}
        <div className="flex items-center gap-3">
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <input
              type="text"
              placeholder="Search symbol or any row field…"
              value={search}
              onChange={e => setSearch(e.target.value)}
              className="pl-8 pr-3 py-1.5 text-sm rounded-md border border-input bg-background focus:outline-none focus:ring-1 focus:ring-ring w-52"
            />
          </div>
          {dismissedCount > 0 && (
            <button
              onClick={() =>
                setFilters((prev) => ({
                  ...prev,
                  status: prev.status === "dismissed" ? "active" : "dismissed",
                }))
              }
              className={`flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-md border transition-colors ${filters.status === "dismissed" ? "bg-foreground text-background border-foreground" : "border-border text-muted-foreground hover:text-foreground hover:border-foreground/40"}`}
              title={filters.status === "dismissed" ? "Switch to active" : "Show dismissed"}
            >
              <Trash2 className="w-3.5 h-3.5" />
              {dismissedCount} dismissed
            </button>
          )}
          <span className="text-sm text-muted-foreground ml-auto">
            {filtered.length} shown
            {rows.length > 0 && ` / ${rows.length} screened`}
          </span>
        </div>

        <ScreeningsFilterBar
          filters={filters}
          setFilters={setFilters}
          noteStageOptions={noteStageOptions}
          noteTagOptions={noteTagOptions}
          boolKeys={boolFilterKeys}
          numKeys={numFilterKeys}
          categoricalStringCols={categoricalStringCols}
          freeStringKeys={freeStringKeys}
        />

        {/* View tabs — trade monitoring last, separated by a divider */}
        <div className="flex items-stretch gap-1 border-b border-border">
          {primaryViewTabs.map(tab => (
            <button
              key={tab.id}
              type="button"
              onClick={() => setActiveView(tab.id)}
              className={`flex items-center gap-1.5 px-3 py-2 text-sm font-medium transition-colors border-b-2 -mb-px ${
                activeView === tab.id
                  ? "border-foreground text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
            >
              {tab.icon}
              {tab.label}
            </button>
          ))}
          <div
            className="w-px shrink-0 self-stretch bg-border my-2 mx-1"
            role="separator"
            aria-orientation="vertical"
            aria-hidden
          />
          <button
            type="button"
            disabled={tradeMonitoringDisabled}
            title={tradeMonitoringTitle}
            onClick={() => {
              if (tradeMonitoringDisabled) return;
              setActiveView("tradeMonitoring");
            }}
            className={`flex items-center gap-1.5 px-3 py-2 text-sm font-medium transition-colors border-b-2 -mb-px ${
              activeView === "tradeMonitoring"
                ? "border-foreground text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground"
            } ${tradeMonitoringDisabled ? "opacity-40 cursor-not-allowed hover:text-muted-foreground" : ""}`}
          >
            <Activity className="w-3.5 h-3.5" />
            Trade monitoring
          </button>
        </div>

        {/* View content */}
        {rows.length === 0 ? (
          <div className="text-sm text-muted-foreground py-8 text-center">
            {selectedRun ? "No results for this run." : "Select a scan run to view results."}
          </div>
        ) : activeView === "results" ? (
          <>
            {filtered.length === 0 ? (
              <div className="text-sm text-muted-foreground py-8 text-center">
                No stocks match the current filters.
              </div>
            ) : (
              <div className="overflow-x-auto rounded-lg border border-border">
                <table className="w-full text-sm">
                  <thead className="bg-muted/40 border-b border-border">
                    <tr>
                      <Th col="symbol">Symbol</Th>
                      {dataColumnKeys.map((k) => {
                        const boolCol = isBooleanColumn(rows, k);
                        return (
                          <th
                            key={k}
                            title={TECH_CRITERIA.find((t) => t.key === k)?.label ?? k}
                            className={`px-2 py-2 text-xs font-medium text-muted-foreground uppercase tracking-wide whitespace-nowrap cursor-pointer select-none hover:text-foreground ${
                              boolCol ? "text-center" : "text-left"
                            }`}
                            onClick={() => toggleSort(k)}
                          >
                            {columnHeaderLabel(k)}
                            <SortIcon col={k} />
                          </th>
                        );
                      })}
                      <th
                        title="Company sensitivity vector in database"
                        className="px-3 py-2 text-center text-xs font-medium text-muted-foreground uppercase tracking-wide"
                      >
                        Vec
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {filtered.map((row, i) => {
                      const isSelected = row.symbol === selectedTicker;
                      const note = rowNotes.get(row.scan_row_id);
                      const isDismissed = note?.status === "dismissed";
                      const isHighlighted = !!note?.highlighted;
                      return (
                        <tr
                          key={row.scan_row_id ?? row.symbol ?? i}
                          onClick={() => row.symbol && setSelectedTicker(row.symbol)}
                          onDoubleClick={() => row.symbol && void openTickerWorkflowEditor(row.symbol)}
                          className={`group cursor-pointer transition-colors ${isDismissed ? "opacity-40" : ""} ${isHighlighted ? "bg-amber-500/10" : ""} ${isSelected ? "bg-foreground/10 ring-1 ring-inset ring-foreground/20" : "hover:bg-muted/30"}`}
                        >
                          <td className="px-3 py-2 font-mono font-semibold whitespace-nowrap">
                            {row.symbol ?? "—"}
                          </td>
                          {dataColumnKeys.map((k) => {
                            const boolCol = isBooleanColumn(rows, k);
                            const v = getRowDataValue(row, k);
                            return (
                              <td
                                key={k}
                                className={`px-2 py-2 align-middle ${boolCol ? "text-center" : "text-left"}`}
                              >
                                <DataCell colKey={k} value={v} />
                              </td>
                            );
                          })}
                          <td className="px-3 py-2 text-center">
                            <div className="flex justify-center">
                              <Check value={vectorTickers.has(row.symbol ?? "")} />
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}

            {/* Column legend */}
            {filtered.length > 0 && (
              <details className="text-xs text-muted-foreground">
                <summary className="cursor-pointer hover:text-foreground">Column key</summary>
                <div className="mt-2 grid grid-cols-2 gap-x-6 gap-y-0.5 pl-2">
                  <div>
                    <span className="font-mono font-medium">Symbol</span> — From scan row (not duplicated from{" "}
                    <code className="text-[10px]">row_data</code>)
                  </div>
                  {dataColumnKeys.map((k) => {
                    const tech = TECH_CRITERIA.find((t) => t.key === k);
                    return (
                      <div key={k}>
                        <span className="font-mono font-medium">{columnHeaderLabel(k)}</span>
                        {tech ? (
                          ` — ${tech.label}`
                        ) : (
                          <>
                            {" — "}
                            <code className="text-[10px]">{k}</code>
                            {" from row_data"}
                          </>
                        )}
                      </div>
                    );
                  })}
                  <div>
                    <span className="font-mono font-medium">Vec</span> — Company sensitivity vector in database
                  </div>
                </div>
              </details>
            )}
          </>
        ) : activeView === "quotes" ? (
          <QuotesView
            symbols={filteredSymbols}
            selectedTicker={selectedTicker}
            onSelect={setSelectedTicker}
            onOpenWorkflowEditor={openTickerWorkflowEditor}
          />
        ) : activeView === "charts" ? (
          <ChartsViewFinal
            symbols={chartSymbols}
            selectedTicker={selectedTicker}
            onSelect={setSelectedTicker}
            dismissed={dismissedSymbols}
            onDismiss={dismissTicker}
            onRestore={restoreTicker}
            getStatus={getTickerStatus}
            onSetStatus={setTickerStatus}
            hasComment={tickerHasComment}
            onEditComment={editTickerComment}
            getTickerMeta={getTickerMeta}
            getPivotMarker={getTickerPivotMarker}
            onSetPivotMarker={setTickerPivotMarker}
            onClearPivotMarker={clearTickerPivotMarker}
          />
        ) : activeView === "tradeMonitoring" ? (
          <TradeMonitoringView
            entries={tradeMonitoringRows}
            selectedTicker={selectedTicker}
            onSelect={setSelectedTicker}
            onGoToCharts={() => setActiveView("charts")}
            onOpenWorkflowEditor={openTickerWorkflowEditor}
            getStatus={getTickerStatus}
            filteredSymbolSet={filteredSymbolSet}
          />
        ) : activeView === "sentiment" ? (
          <SentimentView
            symbols={filteredSymbols}
            selectedTicker={selectedTicker}
            onSelect={setSelectedTicker}
            getTickerMeta={getTickerMeta}
          />
        ) : activeView === "relationship" ? (
          <RelationshipMapView
            symbols={filteredSymbols}
            selectedTicker={selectedTicker}
            onSelect={setSelectedTicker}
            getTickerMeta={getTickerMeta}
          />
        ) : (
          <StockNewsTrendView
            symbols={filteredSymbols}
            companyVectorDimensions={companyVectorDimensions}
            selectedTicker={selectedTicker}
            onSelect={setSelectedTicker}
            dismissed={dismissedSymbols}
            onDismiss={dismissTicker}
            onRestore={restoreTicker}
            getStatus={getTickerStatus}
            onSetStatus={setTickerStatus}
            hasComment={tickerHasComment}
            onEditComment={editTickerComment}
            getTickerMeta={getTickerMeta}
          />
        )}
      </div>
      {workflowEditor && (
        <div
          className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4"
          onClick={() => !savingWorkflowEditor && setWorkflowEditor(null)}
        >
          <div
            className="w-full max-w-md rounded-lg border border-border bg-background p-4 shadow-xl flex flex-col gap-3"
            onClick={e => e.stopPropagation()}
          >
            <div className="flex items-center justify-between">
              <h3 className="text-base font-semibold">Workflow update</h3>
              <span className="font-mono text-sm text-muted-foreground">{workflowEditor.ticker}</span>
            </div>
            <label className="flex flex-col gap-1">
              <span className="text-xs text-muted-foreground">Status</span>
              <select
                value={workflowEditor.status}
                onChange={e => setWorkflowEditor(prev => prev ? { ...prev, status: e.target.value as NoteStatus } : prev)}
                className="px-2 py-1.5 text-sm rounded border border-input bg-background focus:outline-none focus:ring-1 focus:ring-ring"
                disabled={savingWorkflowEditor}
              >
                <option value="active">Active</option>
                <option value="dismissed">Dismissed</option>
                <option value="watchlist">Watchlist</option>
                <option value="pipeline">Pipeline</option>
              </select>
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs text-muted-foreground">Note</span>
              <textarea
                value={workflowEditor.comment}
                onChange={e => setWorkflowEditor(prev => prev ? { ...prev, comment: e.target.value } : prev)}
                rows={4}
                placeholder="Add screening notes..."
                className="px-2 py-1.5 text-sm rounded border border-input bg-background focus:outline-none focus:ring-1 focus:ring-ring resize-y"
                disabled={savingWorkflowEditor}
              />
            </label>
            <div className="flex items-center justify-end gap-2 pt-1">
              <button
                onClick={() => setWorkflowEditor(null)}
                className="px-3 py-1.5 text-sm rounded border border-border hover:bg-muted transition-colors"
                disabled={savingWorkflowEditor}
              >
                Cancel
              </button>
              <button
                onClick={() => void saveWorkflowEditor()}
                className="px-3 py-1.5 text-sm rounded bg-foreground text-background hover:opacity-90 transition-opacity disabled:opacity-50"
                disabled={savingWorkflowEditor}
              >
                {savingWorkflowEditor ? "Saving..." : "Save"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
