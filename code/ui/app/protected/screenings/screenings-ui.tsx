"use client";

import { useState, useMemo, useEffect, useCallback, useRef, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import {
  CheckCircle, XCircle, Search, ChevronDown, ChevronUp,
  BarChart2, List, TrendingUp, Loader2, Newspaper, Trash2, RotateCcw, Star, MessageSquare,
  Activity, Copy, Gauge, Plus, Bot, FolderPlus,
} from "lucide-react";
import { AiAnalysisPanel } from "@/components/ai-analysis-panel";
import { CLUSTERS } from "../vectors/dimensions";
import { NewsTrendsUI, type ArticleImpact } from "../news-trends/news-trends-ui";
import { fmpGetPriceAtDate } from "@/app/actions/fmp";
import { relationshipsResolveTicker } from "@/app/actions/relationships";
import {
  TickerChartsPanel,
  entryFromMetadata,
  type ChartPoint,
  type EntryMarker,
} from "@/components/ticker-charts";
import { createClient } from "@/lib/supabase/client";
import {
  screeningsGetNewsImpacts,
  screeningsGetTickerSentimentHeadRows,
  screeningsAddTicker,
  screeningsCreateRun,
  screeningsSoftDeleteRun,
  screeningsUpsertDismissNote,
  type ScreeningTickerSentimentHeadRow,
} from "@/app/actions/screenings";
import { RelationshipNetworkExplorer } from "@/components/relationship-network/relationship-network-explorer";
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
import { AddFilterWidget } from "./screenings-filter-bar";
import {
  DEFAULT_SCREENINGS_FILTERS,
  NOTE_STAGE_NONE,
  type ScreeningsFilters,
  countScreeningsFilterRules,
} from "./screenings-filters-model";
import { TickerSidebar } from "./ticker-sidebar";
import { TickerContextMenu, type NoteStatus as ContextMenuNoteStatus } from "./ticker-context-menu";
import type { OhlcBar, ChartAnnotation } from "@/components/ticker-charts/types";
import { useQuotes, type FmpQuote } from "@/lib/use-quotes";
import { chartWorkspaceLoad, chartWorkspaceSave, type ChartAiChatMessage } from "@/app/actions/chart-workspace";
import { ChartAiChat } from "@/components/chart-ai-chat";
import { ChartDateRangePicker } from "@/components/chart-date-range-picker";

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

const DEEP_DIVE_VIEWS: ViewTab[] = ["charts", "news", "relationship"];

function isDeepDiveView(v: ViewTab): boolean {
  return DEEP_DIVE_VIEWS.includes(v);
}

type ScreeningsPrimaryTabDef = { id: ViewTab; label: string; icon: ReactNode };

// ─── QuotesView ──────────────────────────────────────────────────────────────

type QuoteSortKey = "symbol" | "price" | "changePercentage" | "volume" | "marketCap" |
  "dayLow" | "dayHigh" | "yearLow" | "yearHigh" | "priceAvg50" | "priceAvg200";

function QuotesView({
  symbols,
  quotes,
  loading,
  selectedTicker,
  onSelect,
  onOpenWorkflowEditor,
  dismissedSymbols,
  highlightedSymbols,
  getStatus,
}: {
  symbols: string[];
  quotes: Record<string, FmpQuote | null>;
  loading: boolean;
  selectedTicker: string | null;
  onSelect: (ticker: string) => void;
  onOpenWorkflowEditor: (ticker: string) => void;
  dismissedSymbols: Set<string>;
  highlightedSymbols: Set<string>;
  getStatus: (ticker: string) => string;
}) {
  const [error] = useState<string | null>(null);
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
      <div className="overflow-x-auto border border-border">
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
              const isDismissed = dismissedSymbols.has(sym);
              const isHighlighted = highlightedSymbols.has(sym);
              const status = getStatus(sym);
              const statusStripe: Record<string, string> = {
                dismissed: "border-l-rose-400",
                watchlist: "border-l-amber-400",
                pipeline: "border-l-sky-400",
                active: "border-l-emerald-400",
              };
              const stripe = isDismissed || isHighlighted || isSelected
                ? statusStripe[status] ?? "border-l-transparent"
                : "";
              return (
                <tr
                  key={sym}
                  onClick={() => onSelect(sym)}
                  onDoubleClick={() => onOpenWorkflowEditor(sym)}
                  className={`cursor-pointer transition-colors border-l-[3px] ${stripe || "border-l-transparent"} ${isDismissed ? "opacity-40" : ""} ${isHighlighted ? "bg-amber-500/10" : ""} ${isSelected ? "bg-foreground/10 ring-1 ring-inset ring-foreground/20" : "hover:bg-muted/30"}`}
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


// ─── Screenings relationship network (same DB neighborhood as Explore) ─────

function ScreeningsRelationshipNetworkPanel({
  symbols,
  selectedTicker,
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
  selectedTicker: string | null;
  onSelect: (ticker: string) => void;
  dismissed: Set<string>;
  onDismiss: (ticker: string) => void;
  onRestore: (ticker: string) => void;
  getStatus: (ticker: string) => NoteStatus;
  onSetStatus: (ticker: string, status: NoteStatus) => void;
  hasComment: (ticker: string) => boolean;
  onEditComment: (ticker: string) => void;
  getTickerMeta: (ticker: string) => { sector: string; industry: string; subSector: string };
}) {
  const idx = useMemo(() => {
    const i = selectedTicker ? symbols.indexOf(selectedTicker) : -1;
    return i >= 0 ? i : 0;
  }, [symbols, selectedTicker]);

  if (symbols.length === 0) {
    return <p className="text-sm text-muted-foreground py-8 text-center">No stocks to show.</p>;
  }

  const symbol = symbols[idx]!;
  const meta = getTickerMeta(symbol);
  const status = getStatus(symbol);
  const commentExists = hasComment(symbol);

  return (
    <div className="flex flex-col gap-4">
      <RelationshipNetworkExplorer
        key={symbol}
        vectors={[]}
        initialSeedTicker={symbol}
        hideSeedControls
      />
    </div>
  );
}

// ─── SentimentView ───────────────────────────────────────────────────────────

type SentimentSort = { key: "symbol" | "s7d" | "s30d" | "s90d"; dir: "asc" | "desc" };

/** Sum `sentiment_score` for `ticker` from `ticker_sentiment_heads_v` rows on/after `cutoffDate` (UTC date). */
function computeTickerSentimentWindow(
  rows: ScreeningTickerSentimentHeadRow[],
  ticker: string,
  cutoffDate: string,
): number {
  const t = ticker.toUpperCase();
  let total = 0;
  for (const row of rows) {
    if (row.ticker.toUpperCase() !== t) continue;
    const day = row.article_ts.slice(0, 10);
    if (day < cutoffDate) continue;
    if (Number.isFinite(row.sentiment_score)) total += row.sentiment_score;
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
  dismissedSymbols,
  highlightedSymbols,
  getStatus,
}: {
  symbols: string[];
  selectedTicker: string | null;
  onSelect: (ticker: string) => void;
  getTickerMeta: (ticker: string) => { sector: string; industry: string; subSector: string };
  dismissedSymbols: Set<string>;
  highlightedSymbols: Set<string>;
  getStatus: (ticker: string) => string;
}) {
  const [sentimentHeadRows, setSentimentHeadRows] = useState<ScreeningTickerSentimentHeadRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sort, setSort] = useState<SentimentSort>({ key: "s7d", dir: "desc" });

  useEffect(() => {
    if (symbols.length === 0) {
      setSentimentHeadRows([]);
      setLoading(false);
      setError(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    screeningsGetTickerSentimentHeadRows(symbols)
      .then((res) => {
        if (cancelled) return;
        if (!res.ok) {
          setError("Failed to load ticker sentiment");
          setSentimentHeadRows([]);
          return;
        }
        setSentimentHeadRows(res.data);
      })
      .catch(() => {
        if (!cancelled) {
          setError("Failed to load ticker sentiment");
          setSentimentHeadRows([]);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [symbols]);

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
          s7d: computeTickerSentimentWindow(sentimentHeadRows, symbol, cutoffs.c7),
          s30d: computeTickerSentimentWindow(sentimentHeadRows, symbol, cutoffs.c30),
          s90d: computeTickerSentimentWindow(sentimentHeadRows, symbol, cutoffs.c90),
        };
      });
  }, [symbols, sentimentHeadRows, cutoffs, getTickerMeta]);

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

  if (symbols.length === 0) {
    return (
      <p className="text-sm text-muted-foreground py-8 text-center">No stocks to show.</p>
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

  return (
    <div className="overflow-x-auto border border-border">
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
          {sorted.map(row => {
            const isSelected = selectedTicker === row.symbol;
            const isDismissed = dismissedSymbols.has(row.symbol);
            const isHighlighted = highlightedSymbols.has(row.symbol);
            const status = getStatus(row.symbol);
            const statusStripe: Record<string, string> = {
              dismissed: "border-l-rose-400",
              watchlist: "border-l-amber-400",
              pipeline: "border-l-sky-400",
              active: "border-l-emerald-400",
            };
            const stripe = isDismissed || isHighlighted || isSelected
              ? statusStripe[status] ?? "border-l-transparent"
              : "";
            return (
            <tr
              key={row.symbol}
              onClick={() => onSelect(row.symbol)}
              className={`cursor-pointer transition-colors border-l-[3px] ${stripe || "border-l-transparent"} ${isDismissed ? "opacity-40" : ""} ${isHighlighted ? "bg-amber-500/10" : ""} ${isSelected ? "bg-foreground/10 ring-1 ring-inset ring-foreground/20" : "hover:bg-muted/30"}`}
            >
              <td className="px-3 py-2 font-mono font-semibold whitespace-nowrap">{row.symbol}</td>
              <td className="px-3 py-2 text-xs text-muted-foreground whitespace-nowrap max-w-[140px] truncate" title={row.sector || undefined}>{row.sector || "—"}</td>
              <td className="px-3 py-2"><SentimentScoreCell value={row.s7d} maxAbs={maxAbs} /></td>
              <td className="px-3 py-2"><SentimentScoreCell value={row.s30d} maxAbs={maxAbs} /></td>
              <td className="px-3 py-2"><SentimentScoreCell value={row.s90d} maxAbs={maxAbs} /></td>
            </tr>
            );
          })}
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
  getTickerMeta: (ticker: string) => { sector: string; industry: string; subSector: string };
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
      {/* News trend chart — reuses the full NewsTrendsUI with weighted articles */}
      <div ref={containerRef} className="w-full">
        {symbol && weightedArticles.length > 0 && (
          <NewsTrendsUI
            key={symbol}
            articles={weightedArticles}
            chartHeight={chartHeight}
            showMainChartFrame={false}
          />
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
  quotes,
  loadingQuotes,
  selectedTicker,
  onSelect,
  onGoToCharts,
  onOpenWorkflowEditor,
  getStatus,
  filteredSymbolSet,
}: {
  entries: { row: ScreeningRow; pivot: EntryMarker }[];
  quotes: Record<string, FmpQuote | null>;
  loadingQuotes: boolean;
  selectedTicker: string | null;
  onSelect: (ticker: string) => void;
  onGoToCharts: () => void;
  onOpenWorkflowEditor: (ticker: string) => void;
  getStatus: (ticker: string) => NoteStatus;
  /** Symbols currently included in the Results table after filters (pivot names may extend beyond this). */
  filteredSymbolSet: Set<string>;
}) {
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
      <div className="overflow-x-auto border border-border">
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
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    document.body.classList.add("screenings-fullscreen");
    return () => {
      document.body.classList.remove("screenings-fullscreen");
      document.body.classList.remove("hide-site-header");
    };
  }, []);

  useEffect(() => {
    document.body.classList.toggle("hide-site-header", collapsed);
  }, [collapsed]);
  const [addFilterOpen, setAddFilterOpen] = useState(false);
  const [contextMenu, setContextMenu] = useState<{ ticker: string; x: number; y: number } | null>(null);
  const ohlcvDataRef = useRef<OhlcBar[]>([]);
  const handleContextMenu = useCallback((ticker: string, e: React.MouseEvent) => {
    e.preventDefault();
    setContextMenu({ ticker, x: e.clientX, y: e.clientY });
  }, []);
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);
  const [chartAnnotations, setChartAnnotations] = useState<ChartAnnotation[]>([]);
  const [chartAiMessages, setChartAiMessages] = useState<ChartAiChatMessage[]>([]);
  const [chartWorkspaceReady, setChartWorkspaceReady] = useState(false);
  const chartSaveSeq = useRef(0);
  const [chartDateRange, setChartDateRange] = useState<{ from: string; to: string } | undefined>();

  useEffect(() => {
    setChartWorkspaceReady(false);
    setChartAnnotations([]);
    setChartAiMessages([]);
    if (!selectedTicker) return;
    let cancelled = false;
    void chartWorkspaceLoad(selectedTicker).then((res) => {
      if (cancelled) return;
      if (res.ok) {
        setChartAnnotations(res.data.annotations);
        setChartAiMessages(res.data.aiChatMessages);
      }
      if (!cancelled) setChartWorkspaceReady(true);
    });
    return () => { cancelled = true; };
  }, [selectedTicker]);

  useEffect(() => {
    if (!selectedTicker || !chartWorkspaceReady) return;
    const seq = ++chartSaveSeq.current;
    const t = setTimeout(() => {
      if (seq !== chartSaveSeq.current) return;
      void chartWorkspaceSave(selectedTicker, { annotations: chartAnnotations, aiChatMessages: chartAiMessages });
    }, 750);
    return () => clearTimeout(t);
  }, [chartAnnotations, chartAiMessages, selectedTicker, chartWorkspaceReady]);

  const handleChartAiAnnotations = useCallback((anns: ChartAnnotation[]) => {
    setChartAnnotations((prev) => [
      ...prev.filter((a) => a.origin === "user"),
      ...anns.map((a) => ({ ...a, origin: "ai" as const })),
    ]);
  }, []);

  const [workflowEditor, setWorkflowEditor] = useState<{
    scanRowId: number;
    ticker: string;
    status: NoteStatus;
    comment: string;
  } | null>(null);
  const [savingWorkflowEditor, setSavingWorkflowEditor] = useState(false);
  const [deletingRunId, setDeletingRunId] = useState<number | null>(null);
  const [newScreeningName, setNewScreeningName] = useState("");
  const [creatingRun, setCreatingRun] = useState(false);
  const [addTickerBusy, setAddTickerBusy] = useState(false);
  const [aiSelectedRow, setAiSelectedRow] = useState<ScreeningRow | null>(null);

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
        const hrn = parsed.hasRowNote;
        const nh = parsed.noteHighlighted;
        const nc = parsed.noteComment;
        const tagsRaw = parsed.noteTagsAny;
        setFiltersState({
          ...DEFAULT_FILTERS,
          ...(typeof statusRaw === "string" ? { status: statusRaw as Filters["status"] } : {}),
          ...(hrn === "any" || hrn === "yes" || hrn === "no" ? { hasRowNote: hrn } : {}),
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

  const highlightedSymbols = useMemo(() => {
    const symbols = new Set<string>();
    for (const row of rows) {
      const note = rowNotes.get(row.scan_row_id);
      if (note?.highlighted && row.symbol) symbols.add(row.symbol);
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
    const out: { row: ScreeningRow; pivot: EntryMarker }[] = [];
    for (const row of rows) {
      if (!row.symbol) continue;
      const p = entryFromMetadata(rowNotes.get(row.scan_row_id)?.metadata_json);
      if (p) out.push({ row, pivot: p });
    }
    out.sort((a, b) => (a.row.symbol ?? "").localeCompare(b.row.symbol ?? ""));
    return out;
  }, [rows, rowNotes]);

  const hasAnyEntryMarkers = tradeMonitoringRows.length > 0;

  useEffect(() => {
    if (activeView === "tradeMonitoring" && !hasAnyEntryMarkers) {
      setActiveView("charts");
    }
  }, [activeView, hasAnyEntryMarkers]);

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

  function getTickerMeta(ticker: string): { sector: string; industry: string; subSector: string } {
    const row = rowBySymbol.get(ticker);
    return {
      sector: row?.sector ?? "",
      industry: row?.industry ?? row?.subSector ?? "",
      subSector: row?.subSector ?? "",
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

  function getTickerEntryMarker(ticker: string): EntryMarker | null {
    const row = rowBySymbol.get(ticker);
    if (!row) return null;
    return entryFromMetadata(rowNotes.get(row.scan_row_id)?.metadata_json);
  }

  function getTickerComment(ticker: string): string | null {
    const row = rowBySymbol.get(ticker);
    if (!row) return null;
    return rowNotes.get(row.scan_row_id)?.comment ?? null;
  }

  async function setTickerEntryMarker(
    ticker: string,
    point: ChartPoint,
    direction?: "long" | "short",
    takeProfit?: number | null,
    stopLoss?: number | null,
  ) {
    const row = rowBySymbol.get(ticker);
    if (!row) return;
    const prev = rowNotes.get(row.scan_row_id);
    const rest = { ...(prev?.metadata_json ?? {}) };
    delete (rest as { pivot_points?: unknown }).pivot_points;
    delete (rest as { pivot?: unknown }).pivot;
    const nextMetadata: Record<string, unknown> = {
      ...rest,
      entry: {
        barIdx: point.barIdx,
        date: point.date,
        price: point.price,
        ...(direction ? { direction } : {}),
        ...(takeProfit != null ? { take_profit: takeProfit } : {}),
        ...(stopLoss != null ? { stop_loss: stopLoss } : {}),
      },
    };
    await upsertRowNote(row, { metadataJson: nextMetadata });
  }

  async function clearTickerEntryMarker(ticker: string) {
    const row = rowBySymbol.get(ticker);
    if (!row) return;
    const prev = rowNotes.get(row.scan_row_id);
    const rest = { ...(prev?.metadata_json ?? {}) };
    delete (rest as { entry?: unknown }).entry;
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

  async function handleCreateScreening() {
    const name = newScreeningName.trim();
    if (!name || creatingRun) return;
    setCreatingRun(true);
    try {
      const res = await screeningsCreateRun(name);
      if (!res.ok) {
        window.alert(res.error);
        return;
      }
      setNewScreeningName("");
      router.push(`/protected/screenings?run=${res.data.id}`);
      router.refresh();
    } finally {
      setCreatingRun(false);
    }
  }

  async function handleAddTickerFromSearch() {
    if (selectedRunId == null || addTickerBusy) return;
    const raw = search.trim();
    if (!raw) return;
    setAddTickerBusy(true);
    try {
      const resolved = await relationshipsResolveTicker(raw);
      if (!resolved.ok) {
        window.alert(resolved.error);
        return;
      }
      const sym = resolved.data.canonicalTicker;
      if (rows.some((r) => r.symbol === sym)) {
        window.alert(`${sym} is already in this screening.`);
        return;
      }
      const res = await screeningsAddTicker(selectedRunId, sym);
      if (!res.ok) {
        window.alert(res.error);
        return;
      }
      setSearch("");
      router.refresh();
    } finally {
      setAddTickerBusy(false);
    }
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
      if (filters.symbolContains?.trim()) {
        const q = filters.symbolContains.trim().toUpperCase();
        if (!r.symbol?.toUpperCase().includes(q)) return false;
      }

      const note = rowNotes.get(r.scan_row_id);
      const hasSavedNote = note !== undefined;
      if (filters.hasRowNote === "yes" && !hasSavedNote) return false;
      if (filters.hasRowNote === "no" && hasSavedNote) return false;

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

  /** No visible rows for this search; query looks like a ticker and is not already in the screening. */
  const searchAddTickerOffer = useMemo(() => {
    if (selectedRunId == null) return false;
    const q = search.trim();
    if (!q) return false;
    if (filtered.length > 0) return false;
    if (q.length > 16) return false;
    if (!/^[A-Za-z][A-Za-z0-9.\-]*$/.test(q)) return false;
    const upper = q.toUpperCase();
    if (rows.some((r) => r.symbol === upper)) return false;
    return true;
  }, [selectedRunId, search, filtered.length, rows]);

  const filteredSymbols = useMemo(() => filtered.map(r => r.symbol).filter(Boolean) as string[], [filtered]);

  const { quotes, loading: quotesLoading } = useQuotes(filteredSymbols);

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

  function buildAiMessage(r: ScreeningRow): string {
    const parts: string[] = [];
    if (r.RS_Rank != null) parts.push(`RS Rank: ${r.RS_Rank}`);
    if (r.adr_pct != null) parts.push(`ADR: ${r.adr_pct.toFixed(1)}%`);
    if (r.vol_ratio_today != null) parts.push(`Vol ratio: ${r.vol_ratio_today.toFixed(2)}`);
    if (r.up_down_vol_ratio != null) parts.push(`Up/down vol ratio: ${r.up_down_vol_ratio.toFixed(2)}`);
    if (r.within_buy_range != null) parts.push(`In buy range: ${r.within_buy_range}`);
    if (r.extended != null) parts.push(`Extended: ${r.extended}`);
    if (r.accumulation != null) parts.push(`Accumulation: ${r.accumulation}`);
    if (r.rs_line_new_high != null) parts.push(`RS line new high: ${r.rs_line_new_high}`);
    if (r.PriceOverSMA150And200) parts.push(`Price > SMA150 & SMA200: true`);
    if (r.SMA150AboveSMA200) parts.push(`SMA150 > SMA200: true`);
    if (r.SMA50AboveSMA150And200) parts.push(`SMA50 > SMA150 & SMA200: true`);
    if (r.SMA200Slope) parts.push(`SMA200 slope up: true`);
    if (r.PriceAbove25Percent52WeekLow) parts.push(`Price > 25% above 52w low: true`);
    if (r.PriceWithin25Percent52WeekHigh) parts.push(`Price within 25% of 52w high: true`);
    if (r.RSOver70) parts.push(`RS > 70: true`);
    if (r.eps_growth_yoy != null) parts.push(`EPS growth YoY: ${r.eps_growth_yoy.toFixed(0)}%`);
    if (r.rev_growth_yoy != null) parts.push(`Revenue growth YoY: ${r.rev_growth_yoy.toFixed(0)}%`);
    if (r.eps_accelerating != null) parts.push(`EPS accelerating: ${r.eps_accelerating}`);
    if (r.roe != null) parts.push(`ROE: ${r.roe.toFixed(1)}%`);
    if (r.inst_pct_accumulating != null) parts.push(`Inst. accumulating: ${r.inst_pct_accumulating.toFixed(0)}%`);
    if (r.sector) parts.push(`Sector: ${r.sector}`);
    if (r.industry) parts.push(`Industry: ${r.industry}`);
    if (r.sector_rank != null && r.total_sectors != null) parts.push(`Sector rank: ${r.sector_rank}/${r.total_sectors}`);

    return `Analyse this stock as a potential swing trade setup:\n\nSymbol: ${r.symbol}\n${parts.join("\n")}\n\nGive a concise assessment: setup quality, entry criteria, key risks, and whether this is worth acting on now.`;
  }

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

  /** Many symbols at once — same filtered list. */
  const multiSymbolViewTabs: ScreeningsPrimaryTabDef[] = [
    { id: "results", label: "Results", icon: <List className="w-3.5 h-3.5" /> },
    { id: "quotes", label: "Quotes", icon: <TrendingUp className="w-3.5 h-3.5" /> },
    { id: "sentiment", label: "Sentiment", icon: <Gauge className="w-3.5 h-3.5" /> },
  ];

  /** One selected ticker — row highlight or prev/next in the tab bar. */
  const deepDiveViewTabs: ScreeningsPrimaryTabDef[] = [
    { id: "charts", label: "Charts", icon: <BarChart2 className="w-3.5 h-3.5" /> },
    { id: "news", label: "News Trend", icon: <Newspaper className="w-3.5 h-3.5" /> },
    { id: "relationship", label: "Relationships", icon: <Activity className="w-3.5 h-3.5" /> },
  ];

  const tradeMonitoringDisabled = !hasAnyEntryMarkers;
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
    <div className="flex flex-col h-full min-h-0 w-full">
      {/* Collapsible: scan runs + search + filters */}
      <div className={`shrink-0 transition-all duration-200 overflow-hidden ${collapsed ? "max-h-0 opacity-0" : "max-h-[2000px] opacity-100"}`}>
        {/* Scan runs */}
        <div className="flex flex-col gap-2 mb-4">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between sm:gap-3">
            <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide shrink-0">
              Scan runs
            </p>
            <form
              className="flex flex-wrap items-center gap-2 min-w-0"
              onSubmit={(e) => {
                e.preventDefault();
                void handleCreateScreening();
              }}
            >
              <input
                type="text"
                value={newScreeningName}
                onChange={(e) => setNewScreeningName(e.target.value)}
                placeholder="New screening name…"
                maxLength={120}
                disabled={creatingRun}
                className="min-w-[10rem] flex-1 sm:flex-initial sm:w-56 rounded-md border border-input bg-background px-2.5 py-1.5 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring disabled:opacity-60"
                aria-label="New screening name"
              />
              <button
                type="submit"
                disabled={creatingRun || !newScreeningName.trim()}
                className="inline-flex items-center gap-1.5 shrink-0 rounded-md border border-border bg-background px-2.5 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-muted disabled:pointer-events-none disabled:opacity-40"
              >
                {creatingRun ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                ) : (
                  <FolderPlus className="h-3.5 w-3.5" aria-hidden />
                )}
                Create screening
              </button>
            </form>
          </div>
          {runs.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No screenings yet. Name one above and click Create — then add tickers from Charts or the Add to screening control.
            </p>
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

        {/* Search + count */}
        <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-start sm:gap-3 mb-2">
          <div className="flex flex-col gap-1.5 min-w-0 shrink-0 w-full max-w-[min(100%,20rem)] sm:w-56">
            <div className="relative w-full">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" />
              <input
                type="text"
                placeholder={
                  selectedRunId != null
                    ? "Search rows, or type a symbol to add…"
                    : "Search symbol or any row field…"
                }
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key !== "Enter") return;
                  if (!searchAddTickerOffer || addTickerBusy) return;
                  e.preventDefault();
                  void handleAddTickerFromSearch();
                }}
                disabled={addTickerBusy}
                className="w-full pl-8 pr-3 py-1.5 text-sm rounded-md border border-input bg-background focus:outline-none focus:ring-1 focus:ring-ring disabled:opacity-60"
                aria-describedby={searchAddTickerOffer ? "screenings-search-add-hint" : undefined}
              />
            </div>
            {searchAddTickerOffer ? (
              <div
                id="screenings-search-add-hint"
                className="flex flex-col gap-1.5 rounded-md border border-border bg-muted/30 px-2.5 py-2 text-xs"
              >
                <p className="text-muted-foreground leading-snug">
                  No matches in this screening for{" "}
                  <span className="font-mono font-medium text-foreground">{search.trim().toUpperCase()}</span>.
                </p>
                <button
                  type="button"
                  disabled={addTickerBusy}
                  onClick={() => void handleAddTickerFromSearch()}
                  className="inline-flex w-fit items-center gap-1.5 rounded-md border border-border bg-background px-2 py-1 font-medium text-foreground transition-colors hover:bg-muted disabled:pointer-events-none disabled:opacity-40"
                >
                  {addTickerBusy ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin shrink-0" aria-hidden />
                  ) : (
                    <Plus className="h-3.5 w-3.5 shrink-0" aria-hidden />
                  )}
                  Add to this screening
                </button>
              </div>
            ) : null}
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

      </div>

      {/* View tabs */}
      <div className="flex flex-col gap-2 border-b border-border pb-px shrink-0">
        <div className="flex flex-wrap items-end gap-x-0 gap-y-1">
          {!addFilterOpen && (
            <>
              <button
                type="button"
                onClick={() => setCollapsed(c => !c)}
                className="mr-1 p-1.5 rounded-md border border-border text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
                title={collapsed ? "Show filters" : "Hide filters"}
              >
                {collapsed ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronUp className="w-3.5 h-3.5" />}
              </button>
              <div
                className="flex flex-wrap items-end gap-1 rounded-md bg-muted/30 px-1 pt-1 pb-0"
                role="group"
                aria-label="List views — multiple symbols from your filter"
              >
                <span className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground px-2 pb-2 shrink-0 max-sm:hidden">
                  Multi-symbol
                </span>
                {multiSymbolViewTabs.map((tab) => (
                  <button
                    key={tab.id}
                    type="button"
                    onClick={() => setActiveView(tab.id)}
                    className={`flex items-center gap-1.5 px-3 py-2 text-sm font-medium transition-colors border-b-2 -mb-px rounded-t-md ${
                      activeView === tab.id
                        ? "border-foreground text-foreground bg-background"
                        : "border-transparent text-muted-foreground hover:text-foreground"
                    }`}
                  >
                    {tab.icon}
                    {tab.label}
                  </button>
                ))}
              </div>
              <div
                className="hidden sm:block w-px shrink-0 self-stretch min-h-[2.25rem] bg-border mx-0.5"
                role="separator"
                aria-orientation="vertical"
                aria-hidden
              />
              <div
                className="flex flex-wrap items-end gap-1 rounded-md bg-muted/30 px-1 pt-1 pb-0"
                role="group"
                aria-label="Deep dive — one ticker at a time"
              >
                <span className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground px-2 pb-2 shrink-0 max-sm:hidden">
                  Deep dive
                </span>
                {deepDiveViewTabs.map((tab) => (
                  <button
                    key={tab.id}
                    type="button"
                    onClick={() => setActiveView(tab.id)}
                    className={`flex items-center gap-1.5 px-3 py-2 text-sm font-medium transition-colors border-b-2 -mb-px rounded-t-md ${
                      activeView === tab.id
                        ? "border-foreground text-foreground bg-background"
                        : "border-transparent text-muted-foreground hover:text-foreground"
                    }`}
                  >
                    {tab.icon}
                    {tab.label}
                  </button>
                ))}
              </div>
              <div
                className="hidden sm:block w-px shrink-0 self-stretch min-h-[2.25rem] bg-border mx-0.5"
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
                className={`flex items-center gap-1.5 px-3 py-2 text-sm font-medium transition-colors border-b-2 -mb-px rounded-t-md ${
                  activeView === "tradeMonitoring"
                    ? "border-foreground text-foreground bg-muted/30"
                    : "border-transparent text-muted-foreground hover:text-foreground"
                } ${tradeMonitoringDisabled ? "opacity-40 cursor-not-allowed hover:text-muted-foreground" : ""}`}
              >
                <Activity className="w-3.5 h-3.5" />
                Trade monitoring
              </button>
            </>
          )}
          <AddFilterWidget
            open={addFilterOpen}
            onOpen={() => setAddFilterOpen(true)}
            onClose={() => setAddFilterOpen(false)}
            filters={filters}
            setFilters={setFilters}
            noteStageOptions={noteStageOptions}
            noteTagOptions={noteTagOptions}
            boolKeys={boolFilterKeys}
            numKeys={numFilterKeys}
            categoricalStringCols={categoricalStringCols}
            freeStringKeys={freeStringKeys}
          />
        </div>
      </div>

      {/* View content — scrollable area */}
      <div className={`flex-1 min-h-0 ${isDeepDiveView(activeView) && filteredSymbols.length > 0 ? "overflow-hidden" : "overflow-y-auto"}`}>
        {rows.length === 0 ? (
          <div className="text-sm text-muted-foreground py-8 text-center">
            {selectedRun ? "No results for this run." : "Select a scan run to view results."}
          </div>
        ) : isDeepDiveView(activeView) && filteredSymbols.length > 0 ? (
          <div className="flex h-full min-h-0 gap-0">
            <div className="hidden sm:flex sm:flex-col w-56 shrink-0 xl:w-64 border-r border-border h-full">
              <TickerSidebar
                symbols={filteredSymbols}
                quotes={quotes}
                selectedTicker={selectedTicker}
                onSelect={setSelectedTicker}
                getTickerMeta={getTickerMeta}
                getStatus={getTickerStatus}
                getSymbolNote={getTickerComment}
                dismissedSymbols={dismissedSymbols}
                highlightedSymbols={highlightedSymbols}
                onContextMenu={handleContextMenu}
              />
            </div>
            <div className="flex-1 min-w-0 min-h-0 flex flex-col gap-4 overflow-y-auto">
              {activeView === "charts" ? (
                <div className="flex flex-col gap-3 w-full min-h-0">
                  <ChartDateRangePicker onChange={setChartDateRange} />
                  <div className="flex items-stretch w-full min-h-0">
                    <div className="flex-1 min-w-0">
                      <TickerChartsPanel
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
                        getEntryMarker={getTickerEntryMarker}
                        onSetEntryMarker={setTickerEntryMarker}
                        onClearEntryMarker={clearTickerEntryMarker}
                        showChevronSymbolNav={false}
                        screeningToolbar={false}
                        showSymbolHeadline={false}
                        showChartFrame={false}
                        annotations={chartAnnotations}
                        onChartData={(rows: OhlcBar[]) => { ohlcvDataRef.current = rows; }}
                        onAnnotationAdd={(ann) => setChartAnnotations((prev) => [...prev, ann])}
                        onAnnotationDelete={(id) => setChartAnnotations((prev) => prev.filter((a) => a.id !== id))}
                        dateRange={chartDateRange}
                      />
                    </div>
                    {selectedTicker && (
                      <div className="w-[320px] shrink-0 flex flex-col border-l border-border">
                        <ChartAiChat
                          key={selectedTicker}
                          symbol={selectedTicker}
                          ohlcData={ohlcvDataRef.current}
                          annotations={chartAnnotations}
                          onAnnotations={handleChartAiAnnotations}
                          messages={chartAiMessages}
                          setMessages={setChartAiMessages}
                          onSaveEntry={(price, direction, takeProfit, stopLoss) => {
                            const ohlc = ohlcvDataRef.current;
                            const lastIdx = ohlc.length - 1;
                            const last = ohlc[lastIdx];
                            if (!last) return;
                            void setTickerEntryMarker(selectedTicker, {
                              barIdx: lastIdx,
                              date: last.date,
                              price,
                              open: last.open,
                              high: last.high,
                              low: last.low,
                              close: last.close,
                            }, direction, takeProfit, stopLoss);
                          }}
                          side
                        />
                      </div>
                    )}
                  </div>
                </div>
              ) : activeView === "relationship" ? (
                <ScreeningsRelationshipNetworkPanel
                  symbols={filteredSymbols}
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
          </div>
        ) : activeView === "results" ? (
          <>
            {filtered.length === 0 ? (
              <div className="text-sm text-muted-foreground py-8 text-center">
                No stocks match the current filters.
              </div>
            ) : (
              <div className="overflow-x-auto border border-border">
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
                      <th className="px-3 py-2 text-center text-xs font-medium text-muted-foreground uppercase tracking-wide w-8">
                        AI
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {filtered.map((row, i) => {
                      const isSelected = row.symbol === selectedTicker;
                      const isAiSelected = aiSelectedRow?.scan_row_id === row.scan_row_id;
                      const note = rowNotes.get(row.scan_row_id);
                      const isDismissed = note?.status === "dismissed";
                      const isHighlighted = !!note?.highlighted;
                      const status = note?.status ?? "active";
                      const statusStripe: Record<string, string> = {
                        dismissed: "border-l-rose-400",
                        watchlist: "border-l-amber-400",
                        pipeline: "border-l-sky-400",
                        active: "border-l-emerald-400",
                      };
                      const stripe = isDismissed || isHighlighted || isSelected
                        ? statusStripe[status] ?? "border-l-transparent"
                        : "";
                      return (
                        <tr
                          key={row.scan_row_id ?? row.symbol ?? i}
                          onClick={() => row.symbol && setSelectedTicker(row.symbol)}
                          onDoubleClick={() => row.symbol && void openTickerWorkflowEditor(row.symbol)}
                          onContextMenu={(e) => row.symbol && handleContextMenu(row.symbol, e)}
                          className={`group cursor-pointer transition-colors border-l-[3px] ${stripe || "border-l-transparent"} ${isDismissed ? "opacity-40" : ""} ${isHighlighted ? "bg-amber-500/10" : ""} ${isSelected ? "bg-foreground/10 ring-1 ring-inset ring-foreground/20" : "hover:bg-muted/30"}`}
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
                          <td className="px-2 py-1.5 text-center" onClick={e => e.stopPropagation()}>
                            <button
                              type="button"
                              title={`Analyse ${row.symbol} with AI`}
                              onClick={() => setAiSelectedRow(isAiSelected ? null : row)}
                              className={`p-1 rounded transition-colors ${isAiSelected ? "text-primary bg-primary/10" : "text-muted-foreground hover:text-foreground hover:bg-muted"}`}
                            >
                              <Bot className="w-3.5 h-3.5" />
                            </button>
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
            quotes={quotes}
            loading={quotesLoading}
            selectedTicker={selectedTicker}
            onSelect={setSelectedTicker}
            onOpenWorkflowEditor={openTickerWorkflowEditor}
            dismissedSymbols={dismissedSymbols}
            highlightedSymbols={highlightedSymbols}
            getStatus={getTickerStatus}
          />
        ) : activeView === "tradeMonitoring" ? (
          <TradeMonitoringView
            entries={tradeMonitoringRows}
            quotes={quotes}
            loadingQuotes={quotesLoading}
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
            dismissedSymbols={dismissedSymbols}
            highlightedSymbols={highlightedSymbols}
            getStatus={getTickerStatus}
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
      {aiSelectedRow && (
        <AiAnalysisPanel
          key={aiSelectedRow.scan_row_id}
          title={`Analyse ${aiSelectedRow.symbol}`}
          system="You are a swing trading assistant. You analyse stock screening data and give setup assessments based on trend template criteria, relative strength, volume action, and fundamentals. Be direct and concise."
          userMessage={buildAiMessage(aiSelectedRow)}
          symbol={aiSelectedRow.symbol}
          cacheKey={String(aiSelectedRow.scan_row_id)}
          onClose={() => setAiSelectedRow(null)}
        />
      )}
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

      {contextMenu && (() => {
        const cm = contextMenu;
        const note = [...rowNotes.values()].find(n => n.ticker === cm.ticker);
        return (
          <TickerContextMenu
            ticker={cm.ticker}
            x={cm.x}
            y={cm.y}
            onClose={() => setContextMenu(null)}
            isDismissed={dismissedSymbols.has(cm.ticker)}
            onDismiss={() => dismissTicker(cm.ticker)}
            onRestore={() => restoreTicker(cm.ticker)}
            status={(note?.status ?? "active") as ContextMenuNoteStatus}
            onSetStatus={(s) => setTickerStatus(cm.ticker, s)}
            hasComment={tickerHasComment(cm.ticker)}
            onEditComment={() => editTickerComment(cm.ticker)}
            onCopyOhlcv={activeView === "charts" && ohlcvDataRef.current.length > 0 ? () => {
              const header = "date,open,high,low,close,volume";
              const lines = ohlcvDataRef.current.map(
                d => `${d.date},${d.open},${d.high},${d.low},${d.close},${d.volume}`
              );
              void navigator.clipboard.writeText([header, ...lines].join("\n"));
            } : null}
          />
        );
      })()}
    </div>
  );
}
