"use client";

import React, {
  useState,
  useMemo,
  useEffect,
  useCallback,
  useRef,
  type ReactNode,
} from "react";
import { useRouter } from "next/navigation";
import {
  Search,
  ChevronDown,
  ChevronUp,
  ChevronLeft,
  ChevronRight,
  Loader2,
  Trash2,
  RotateCcw,
  Star,
  MessageSquare,
  Activity,
  Copy,
  Plus,
  Bot,
  Bell,
  FolderPlus,
  Sparkles,
  Calendar,
  Target,
  TrendingUp,
  Check as CheckIcon,
  Building2,
  ExternalLink,
  Gauge,
  Newspaper,
  ArrowUpRight,
} from "lucide-react";
import Link from "next/link";
import { AiAnalysisPanel } from "@/components/ai-analysis-panel";
import { CLUSTERS } from "../vectors/dimensions";
import { relationshipsResolveTicker } from "@/app/actions/relationships";
import {
  TickerChartsPanel,
  entryFromMetadata,
  type ChartPoint,
  type EntryMarker,
} from "@/components/ticker-charts";
import {
  bulkAnalyzeScanRun,
  getBulkAnalysisJob,
  screeningsAddTicker,
  screeningsCreateRun,
  screeningsSoftDeleteRun,
  screeningsUpsertDismissNote,
  screeningsGetUserTrades,
  screeningsGetTickerSentimentHeadRows,
  type BulkAnalysisJob,
  type LoggedTrade,
  type ScreeningTickerSentimentHeadRow,
} from "@/app/actions/screenings";
import {
  fmpGetCompanyProfile,
  type FmpCompanyProfile,
} from "@/app/actions/fmp";
import {
  collectAllRowDataKeys,
  getRowDataValue,
  inferBooleanFilterKeys,
  inferNumericFilterKeys,
  isBooleanColumn,
  isNumericColumn,
  MAX_CATEGORICAL_STRING_OPTIONS,
  orderedDataColumnKeys,
  uniqueStringValuesForKey,
} from "./screenings-row-data";
import { AddFilterWidget } from "./screenings-filter-bar";
import {
  DEFAULT_SCREENINGS_FILTERS,
  type ScreeningsFilters,
  countScreeningsFilterRules,
  normalizeScreeningsFilters,
} from "./screenings-filters-model";
import { TickerSidebar } from "./ticker-sidebar";
import { MobileTickerBar } from "./mobile-ticker-bar";
import {
  TickerContextMenu,
  type NoteStatus as ContextMenuNoteStatus,
} from "./ticker-context-menu";
import { AgentAlarmDialog } from "./agent-alarm-dialog";
import type {
  OhlcBar,
  ChartAnnotation,
} from "@/components/ticker-charts/types";
import { useQuotes, type FmpQuote } from "@/lib/use-quotes";
import {
  chartWorkspaceLoad,
  chartWorkspaceSave,
  type ChartAiChatMessage,
} from "@/app/actions/chart-workspace";
import { ChartAiChat } from "@/components/chart-ai-chat";
import { MobileAiChatSheet } from "@/components/mobile-ai-chat-sheet";
import { BulkAiPanel } from "@/components/bulk-ai-panel";
import {
  ChartDateRangePicker,
  type ChartGranularity,
} from "@/components/chart-date-range-picker";
import {
  DEEP_DIVE_VIEWS,
  isDeepDiveView,
  type ScanRun,
  type ScreeningRow,
  type ScanRowNote,
  type NoteStatus,
  type ViewTab,
} from "./screenings-types";
import { Check, DataCell } from "./screenings-data-cell";
import { QuotesView } from "./screenings-quotes-view";
import { ScreeningsRelationshipNetworkPanel } from "./screenings-relationship-panel";
import { SentimentView } from "./screenings-sentiment-view";
import { StockNewsTrendView } from "./screenings-news-trend-view";
import { ScreeningsArticlesView } from "./screenings-articles-view";
import { TradeMonitoringView } from "./screenings-trade-monitoring-view";
import { buildScreeningsAiMessage } from "./screenings-build-ai-message";
import { filterAndSortScreeningRows } from "./screenings-filter-rows";
import {
  TECH_CRITERIA,
  screeningsColumnHeaderShort,
} from "./screenings-tech-criteria";
import { ScreeningsSortIcon } from "./screenings-sort-icon";
import {
  SCREENINGS_DEEP_DIVE_TABS,
  SCREENINGS_MULTI_SYMBOL_TABS,
} from "./screenings-view-tab-presets";
import { ScreeningsMobileViewPicker } from "./screenings-mobile-view-picker";
import { useCavemanMode } from "@/lib/caveman-mode";

export type { ScanRun, ScreeningRow, ScanRowNote } from "./screenings-types";

// ─── filter state (model: screenings-filters-model.ts) ───────────────────────

type Filters = ScreeningsFilters;
const DEFAULT_FILTERS = DEFAULT_SCREENINGS_FILTERS;

const OPTIMISTIC_ROW_ID = -1;

function createOptimisticScreeningRow(
  runId: number,
  symbol: string,
): ScreeningRow {
  return {
    scan_row_id: OPTIMISTIC_ROW_ID,
    run_id: runId,
    symbol,
    rowData: {},
    sector: "",
    industry: "",
    subSector: "",
    RS_Rank: null,
    Passed: false,
    PASSED_FUNDAMENTALS: false,
    PriceOverSMA150And200: false,
    SMA150AboveSMA200: false,
    SMA50AboveSMA150And200: false,
    SMA200Slope: false,
    PriceAbove25Percent52WeekLow: false,
    PriceWithin25Percent52WeekHigh: false,
    RSOver70: false,
    adr_pct: null,
    vol_ratio_today: null,
    up_down_vol_ratio: null,
    accumulation: null,
    rs_line_new_high: null,
    within_buy_range: null,
    extended: null,
    increasing_eps: false,
    beat_estimate: false,
    eps_growth_yoy: null,
    rev_growth_yoy: null,
    eps_accelerating: null,
    three_yr_annual_eps_25pct: null,
    roe: null,
    roe_above_17pct: null,
    passes_oneil_fundamentals: null,
    sector_is_leader: null,
    sector_rank: null,
    total_sectors: null,
    inst_shares_increasing: null,
    inst_pct_accumulating: null,
  };
}

/** Sort column: `symbol` or any key present in rowData (discovered per run). */
type SortKey = string;
type SortDir = "asc" | "desc";

// Caveman date range presets. 1M uses hourly candles (intraday detail for a
// short window); the longer ranges roll up to daily so the chart stays
// readable. State lives in the parent so the desktop chip strip and the
// mobile swipe arrows around the chart stay in sync.
const CAVEMAN_RANGES = [
  {
    id: "1m",
    label: "1 month",
    shortLabel: "1M",
    days: 30,
    granularity: "1hour" as ChartGranularity,
  },
  {
    id: "6m",
    label: "6 months",
    shortLabel: "6M",
    days: 180,
    granularity: "1day" as ChartGranularity,
  },
  {
    id: "1y",
    label: "1 year",
    shortLabel: "1Y",
    days: 365,
    granularity: "1day" as ChartGranularity,
  },
] as const;

type CavemanRangeId = (typeof CAVEMAN_RANGES)[number]["id"];
const CAVEMAN_DEFAULT_RANGE_ID: CavemanRangeId = "6m";

// Human-readable label for a chart granularity, used in the chart title.
function granularityLabel(g: ChartGranularity): string {
  switch (g) {
    case "1hour":
      return "Hourly";
    case "4hour":
      return "4-Hour";
    case "1week":
      return "Weekly";
    case "1day":
    default:
      return "Daily";
  }
}

// Approximate a "1 month / 6 months / 1 year / …" label from an arbitrary
// from→to range. Caveman uses a known preset; businessman date picker can
// produce anything, so we bucket by days.
function rangeLabelFromDates(
  range: { from: string; to: string } | undefined,
): string {
  if (!range) return "—";
  const ms =
    new Date(range.to).getTime() - new Date(range.from).getTime();
  const days = Math.round(ms / 86400000);
  if (!Number.isFinite(days) || days <= 0) return "—";
  if (days <= 10) return "1 week";
  if (days <= 45) return "1 month";
  if (days <= 100) return "3 months";
  if (days <= 220) return "6 months";
  if (days <= 730) return "1 year";
  if (days <= 1500) return "3 years";
  return "5 years";
}

// Convert a CavemanRange id into the from/to range the chart pipeline expects.
function cavemanRangeToDates(
  id: CavemanRangeId,
): { from: string; to: string; granularity: ChartGranularity } | null {
  const preset = CAVEMAN_RANGES.find((r) => r.id === id);
  if (!preset) return null;
  const end = new Date();
  const start = new Date(end);
  start.setDate(start.getDate() - preset.days);
  const pad2 = (n: number) => String(n).padStart(2, "0");
  const fmt = (d: Date) =>
    `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
  return {
    from: fmt(start),
    to: fmt(end),
    granularity: preset.granularity,
  };
}

// Desktop chip strip (sm and up). Controlled component — parent owns state.
function CavemanRangeChips({
  activeId,
  onSelect,
}: {
  activeId: CavemanRangeId;
  onSelect: (id: CavemanRangeId) => void;
}) {
  return (
    <div
      className="hidden sm:flex items-center gap-1 px-1 py-2"
      role="radiogroup"
      aria-label="Chart time range"
    >
      <span className="text-[10px] font-medium uppercase tracking-[0.1em] text-muted-foreground mr-1">
        Range
      </span>
      {CAVEMAN_RANGES.map((r) => {
        const active = activeId === r.id;
        return (
          <button
            key={r.id}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onSelect(r.id)}
            className={`min-h-[36px] px-3 py-1.5 text-xs font-mono uppercase tracking-[0.1em] rounded-md border transition-colors ${
              active
                ? "border-foreground bg-foreground text-background"
                : "border-border text-muted-foreground hover:text-foreground hover:border-foreground/40"
            }`}
          >
            {r.label}
          </button>
        );
      })}
    </div>
  );
}

// Tinder-style mobile chart navigation. Three pieces:
//   - A segment progress bar pinned at the very top of the chart card,
//     showing which range is active and tappable to jump directly.
//   - Two absolutely-positioned chevron tap zones on the chart's left/right
//     edges for thumb-friendly stepping (the chart's center keeps pan/zoom).
// Caller renders this inside a `relative` container that wraps the chart.
function CavemanRangeMobileSwipe({
  activeId,
  onPrev,
  onNext,
  onSelect,
}: {
  activeId: CavemanRangeId;
  onPrev: () => void;
  onNext: () => void;
  onSelect: (id: CavemanRangeId) => void;
}) {
  return (
    <>
      {/* Segment progress — same pattern as Tinder photo-deck pagination */}
      <div
        className="sm:hidden absolute top-0 left-0 right-0 z-10 flex items-center gap-1 px-2 pt-1.5 pb-1 pointer-events-none"
        aria-hidden
      >
        {CAVEMAN_RANGES.map((r) => {
          const active = r.id === activeId;
          return (
            <button
              key={r.id}
              type="button"
              onClick={() => onSelect(r.id)}
              aria-label={`Show ${r.label}`}
              className="pointer-events-auto flex-1 h-1.5 flex items-center justify-center group"
            >
              <span
                className={`block h-[3px] w-full rounded-full transition-colors ${
                  active ? "bg-foreground" : "bg-foreground/25"
                } group-active:bg-foreground/60`}
              />
            </button>
          );
        })}
      </div>
      <button
        type="button"
        onClick={onPrev}
        aria-label="Previous time range"
        className="sm:hidden absolute left-1 top-1/2 -translate-y-1/2 z-10 flex items-center justify-center h-11 w-11 rounded-full border border-border bg-background/85 backdrop-blur-sm text-foreground shadow-md active:bg-muted/80"
      >
        <ChevronLeft className="h-5 w-5" />
      </button>
      <button
        type="button"
        onClick={onNext}
        aria-label="Next time range"
        className="sm:hidden absolute right-1 top-1/2 -translate-y-1/2 z-10 flex items-center justify-center h-11 w-11 rounded-full border border-border bg-background/85 backdrop-blur-sm text-foreground shadow-md active:bg-muted/80"
      >
        <ChevronRight className="h-5 w-5" />
      </button>
    </>
  );
}

// Hero symbol headline for the deep-dive Charts surface. The chart panel's
// built-in headline brings the entire screenings toolbar with it; we render
// our own so we control the typography (mono numbers, tight tracking, single
// accent on change) and so the right-hand range-picker slot stays free for
// either the businessman picker or the caveman chip strip.
function DeepDiveSymbolHeader({
  symbol,
  quote,
  meta,
  rightSlot,
}: {
  symbol: string;
  quote: FmpQuote | null | undefined;
  meta: { sector: string; industry: string; subSector?: string };
  rightSlot: ReactNode;
}) {
  const change = quote?.change ?? null;
  const changePct = quote?.changePercentage ?? null;
  const dir =
    change == null ? "flat" : change >= 0 ? "up" : "down";
  const changeColor =
    dir === "up"
      ? "text-emerald-500"
      : dir === "down"
        ? "text-rose-500"
        : "text-muted-foreground";

  return (
    <div className="border-b border-border bg-background px-3 pt-3 pb-2">
      <div className="flex items-start justify-between gap-3">
        {/* Left column: symbol + subtitle (company / sector / industry). */}
        <div className="flex min-w-0 flex-col gap-1">
          <span
            className="font-mono font-semibold tracking-[-0.02em] tabular-nums text-2xl leading-none sm:text-3xl"
            title={quote?.name ?? symbol}
          >
            {symbol || "—"}
          </span>
          <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[10px] font-mono uppercase tracking-[0.12em] text-muted-foreground/80">
            {quote?.name ? (
              <span className="truncate normal-case tracking-normal text-foreground/70 font-sans text-xs">
                {quote.name}
              </span>
            ) : null}
            {quote?.name && (meta.sector || meta.industry) ? (
              <span aria-hidden className="text-muted-foreground/40">
                ·
              </span>
            ) : null}
            {meta.sector ? (
              <span className="truncate">{meta.sector}</span>
            ) : null}
            {meta.sector && meta.industry ? (
              <span aria-hidden className="text-muted-foreground/40">
                ·
              </span>
            ) : null}
            {meta.industry ? (
              <span className="truncate">{meta.industry}</span>
            ) : null}
          </div>
        </div>
        {/* Right column: price on top, change underneath. Range slot
            (chip strip or date picker) renders next to it on desktop; on
            mobile the slot is invisible because CavemanRangeChips uses
            `hidden sm:flex` internally. */}
        <div className="flex shrink-0 items-start gap-4">
          <div className="flex flex-col items-end gap-0.5">
            <span className="font-mono tabular-nums text-lg sm:text-xl text-foreground leading-none">
              {quote ? `$${quote.price.toFixed(2)}` : "—"}
            </span>
            {quote ? (
              <span
                className={`font-mono tabular-nums text-xs sm:text-sm leading-none ${changeColor}`}
              >
                {change != null && change >= 0 ? "+" : ""}
                {change != null ? change.toFixed(2) : "—"}
                {changePct != null && (
                  <span className="ml-1 opacity-80">
                    ({changePct >= 0 ? "+" : ""}
                    {changePct.toFixed(2)}%)
                  </span>
                )}
              </span>
            ) : null}
          </div>
          {rightSlot}
        </div>
      </div>
    </div>
  );
}

// Caveman quick-actions strip. The full context menu (right-click on a
// sidebar row) stays available, but right-click is invisible to non-technical
// users — they need explicit, labelled buttons for the three most common
// actions: status change, note edit, agent alarm setup. Renders below the
// symbol header, only in caveman mode.
function CavemanQuickActions({
  ticker,
  status,
  isDismissed,
  onSetStatus,
  onDismiss,
  onRestore,
  hasNote,
  onEditNote,
  onSetupAgent,
}: {
  ticker: string;
  status: NoteStatus;
  isDismissed: boolean;
  onSetStatus: (s: Exclude<NoteStatus, "dismissed">) => void;
  onDismiss: () => void;
  onRestore: () => void;
  hasNote: boolean;
  onEditNote: () => void;
  onSetupAgent: () => void;
}) {
  const stageStatus: Exclude<NoteStatus, "dismissed"> =
    status === "dismissed" ? "active" : (status as Exclude<NoteStatus, "dismissed">);
  const stages: { value: Exclude<NoteStatus, "dismissed">; label: string }[] = [
    { value: "active", label: "Active" },
    { value: "watchlist", label: "Watch" },
    { value: "pipeline", label: "Pipeline" },
  ];
  return (
    <div className="flex flex-wrap items-center gap-3 px-3 py-2 border-b border-border bg-muted/15">
      <div className="flex items-center gap-1.5">
        <span className="text-[10px] font-mono uppercase tracking-[0.12em] text-muted-foreground">
          Status
        </span>
        <div
          role="radiogroup"
          aria-label={`Status for ${ticker}`}
          className="flex items-center rounded-md border border-border bg-background overflow-hidden"
        >
          {stages.map((s) => {
            const active = stageStatus === s.value && !isDismissed;
            return (
              <button
                key={s.value}
                type="button"
                role="radio"
                aria-checked={active}
                onClick={() => onSetStatus(s.value)}
                disabled={isDismissed}
                className={`min-h-[32px] px-3 py-1 text-[11px] font-mono uppercase tracking-[0.08em] transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${
                  active
                    ? "bg-foreground text-background"
                    : "text-muted-foreground hover:text-foreground hover:bg-muted"
                }`}
              >
                {s.label}
              </button>
            );
          })}
        </div>
        {isDismissed ? (
          <button
            type="button"
            onClick={onRestore}
            className="inline-flex items-center gap-1.5 min-h-[32px] rounded-md border border-emerald-500/40 bg-emerald-500/10 px-2.5 py-1 text-[11px] font-mono uppercase tracking-[0.08em] text-emerald-600 dark:text-emerald-400 transition-colors hover:bg-emerald-500/20"
            title={`Restore ${ticker}`}
          >
            <RotateCcw className="w-3 h-3" />
            Restore
          </button>
        ) : (
          <button
            type="button"
            onClick={onDismiss}
            className="inline-flex items-center gap-1.5 min-h-[32px] rounded-md border border-border bg-background px-2.5 py-1 text-[11px] font-mono uppercase tracking-[0.08em] text-muted-foreground transition-colors hover:text-rose-500 hover:border-rose-500/40 hover:bg-rose-500/10"
            title={`Dismiss ${ticker}`}
          >
            <Trash2 className="w-3 h-3" />
            Dismiss
          </button>
        )}
      </div>
      <div className="flex items-center gap-2 ml-auto">
        <button
          type="button"
          onClick={onEditNote}
          className={`inline-flex items-center gap-1.5 min-h-[32px] rounded-md border bg-background px-2.5 py-1 text-[11px] font-mono uppercase tracking-[0.08em] transition-colors hover:bg-muted ${
            hasNote
              ? "border-amber-500/40 text-amber-600 dark:text-amber-400"
              : "border-border text-foreground"
          }`}
          title={hasNote ? "Edit note" : "Add note"}
        >
          <MessageSquare className="w-3 h-3" />
          {hasNote ? "Edit note" : "Add note"}
        </button>
        <button
          type="button"
          onClick={onSetupAgent}
          className="inline-flex items-center gap-1.5 min-h-[32px] rounded-md border border-amber-500/40 bg-amber-500/10 px-2.5 py-1 text-[11px] font-mono uppercase tracking-[0.08em] text-amber-600 dark:text-amber-400 transition-colors hover:bg-amber-500/20"
          title="Setup agent alarm"
        >
          <Bell className="w-3 h-3" />
          Agent alarm
        </button>
      </div>
    </div>
  );
}

// Mobile-only floating action bar. Tinder-style bottom toolbar pinned above
// the MobileTickerBar. Renders three labelled pills (Status / Note / Agent)
// and surfaces stage changes through a bottom-sheet popover — full-height
// targets so non-technical users don't fight tiny tap zones.
function CavemanMobileActionBar({
  ticker,
  status,
  isDismissed,
  onSetStatus,
  onDismiss,
  onRestore,
  hasNote,
  onEditNote,
  onSetupAgent,
}: {
  ticker: string;
  status: NoteStatus;
  isDismissed: boolean;
  onSetStatus: (s: Exclude<NoteStatus, "dismissed">) => void;
  onDismiss: () => void;
  onRestore: () => void;
  hasNote: boolean;
  onEditNote: () => void;
  onSetupAgent: () => void;
}) {
  const [statusOpen, setStatusOpen] = useState(false);

  const stageLabel = isDismissed
    ? "Dismissed"
    : status === "watchlist"
      ? "Watch"
      : status === "pipeline"
        ? "Pipeline"
        : "Active";

  const stageTone = isDismissed
    ? "border-rose-500/40 bg-rose-500/10 text-rose-500"
    : "border-border bg-card text-foreground";

  const stages: { value: Exclude<NoteStatus, "dismissed">; label: string }[] = [
    { value: "active", label: "Active" },
    { value: "watchlist", label: "Watch" },
    { value: "pipeline", label: "Pipeline" },
  ];
  const currentStage =
    status === "dismissed"
      ? null
      : (status as Exclude<NoteStatus, "dismissed">);

  return (
    <>
      <div className="sm:hidden shrink-0 border-t border-border bg-background/95 backdrop-blur-md">
        <div className="flex items-center gap-2 px-3 py-2 pb-[max(0.5rem,env(safe-area-inset-bottom))]">
          <button
            type="button"
            onClick={() => setStatusOpen(true)}
            className={`flex-1 min-h-[44px] inline-flex items-center justify-center gap-1.5 rounded-full border px-3 text-[12px] font-mono uppercase tracking-[0.1em] transition-colors active:scale-[0.98] ${stageTone}`}
            aria-haspopup="dialog"
            aria-expanded={statusOpen}
            aria-label={`Status: ${stageLabel}. Tap to change.`}
          >
            <span className="truncate">{stageLabel}</span>
            <ChevronUp className="h-3 w-3 opacity-60 shrink-0" />
          </button>
          <button
            type="button"
            onClick={onEditNote}
            className={`flex-1 min-h-[44px] inline-flex items-center justify-center gap-1.5 rounded-full border px-3 text-[12px] font-mono uppercase tracking-[0.1em] transition-colors active:scale-[0.98] ${
              hasNote
                ? "border-amber-500/40 bg-amber-500/10 text-amber-600 dark:text-amber-400"
                : "border-border bg-card text-foreground"
            }`}
            aria-label={hasNote ? "Edit note" : "Add note"}
          >
            <MessageSquare className="h-3.5 w-3.5 shrink-0" />
            Note
          </button>
          <button
            type="button"
            onClick={onSetupAgent}
            className="flex-1 min-h-[44px] inline-flex items-center justify-center gap-1.5 rounded-full border border-amber-500/40 bg-amber-500/10 px-3 text-[12px] font-mono uppercase tracking-[0.1em] text-amber-600 dark:text-amber-400 transition-colors active:scale-[0.98]"
            aria-label="Setup agent alarm"
          >
            <Bell className="h-3.5 w-3.5 shrink-0" />
            Agent
          </button>
        </div>
      </div>

      {statusOpen && (
        <>
          <div
            className="sm:hidden fixed inset-0 z-40 bg-black/40"
            onClick={() => setStatusOpen(false)}
            aria-hidden
          />
          <div
            className="sm:hidden fixed inset-x-0 bottom-0 z-50 border-t border-border bg-background rounded-t-2xl shadow-2xl"
            role="dialog"
            aria-label={`Change status for ${ticker}`}
          >
            <div className="flex items-center justify-center py-2">
              <div className="h-1 w-10 rounded-full bg-border" />
            </div>
            <div className="px-2 pb-[max(1rem,env(safe-area-inset-bottom))]">
              <div className="px-3 pb-2 text-[10px] font-mono uppercase tracking-[0.14em] text-muted-foreground">
                Set stage for {ticker}
              </div>
              {stages.map((s) => {
                const checked = currentStage === s.value && !isDismissed;
                return (
                  <button
                    key={s.value}
                    type="button"
                    onClick={() => {
                      onSetStatus(s.value);
                      setStatusOpen(false);
                    }}
                    className="w-full flex items-center justify-between px-3 py-3 text-sm transition-colors hover:bg-muted/40 active:bg-muted"
                  >
                    <span>{s.label}</span>
                    {checked && (
                      <CheckIcon className="h-4 w-4 text-foreground" />
                    )}
                  </button>
                );
              })}
              <div className="border-t border-border my-1" />
              <button
                type="button"
                onClick={() => {
                  if (isDismissed) onRestore();
                  else onDismiss();
                  setStatusOpen(false);
                }}
                className={`w-full flex items-center gap-2 px-3 py-3 text-sm transition-colors ${
                  isDismissed
                    ? "text-emerald-600 dark:text-emerald-400 hover:bg-emerald-500/10"
                    : "text-rose-500 hover:bg-rose-500/10"
                }`}
              >
                {isDismissed ? (
                  <RotateCcw className="h-4 w-4" />
                ) : (
                  <Trash2 className="h-4 w-4" />
                )}
                {isDismissed ? "Restore ticker" : "Dismiss ticker"}
              </button>
            </div>
          </div>
        </>
      )}
    </>
  );
}

// Tinder-style info cards. Rendered below the chart on mobile-caveman only,
// when the user scrolls. Each card is a small white block with a small-caps
// title and a few "label → value" rows. Builds context for non-technical
// users in plain numeric form (snapshot, 52-week position, screen verdict).
function InfoCard({
  icon,
  title,
  children,
}: {
  icon: ReactNode;
  title: string;
  children: ReactNode;
}) {
  return (
    <section className="rounded-xl border border-border bg-card overflow-hidden flex flex-col shadow-sm">
      {/* Header band — high-contrast Tinder-style section header. Solid
          tinted background, inverted icon badge, sentence-case title at
          text-sm/font-semibold so it reads as an unmistakable heading. */}
      <header className="flex items-center gap-2.5 border-b border-border bg-muted/50 px-4 py-3">
        <span className="flex h-7 w-7 items-center justify-center rounded-md bg-foreground text-background">
          {icon}
        </span>
        <h3 className="text-sm font-semibold text-foreground leading-none">
          {title}
        </h3>
      </header>
      <div className="flex flex-col gap-2.5 px-4 py-4">{children}</div>
    </section>
  );
}

function InfoRow({
  label,
  value,
  tone,
}: {
  label: string;
  value: ReactNode;
  tone?: "default" | "positive" | "negative" | "muted";
}) {
  const toneCls =
    tone === "positive"
      ? "text-emerald-500"
      : tone === "negative"
        ? "text-rose-500"
        : tone === "muted"
          ? "text-muted-foreground"
          : "text-foreground";
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className={`font-mono text-sm font-medium tabular-nums ${toneCls}`}>
        {value}
      </span>
    </div>
  );
}

function formatLargeNumber(n: number, prefix = ""): string {
  if (!Number.isFinite(n)) return "—";
  const abs = Math.abs(n);
  if (abs >= 1e12) return `${prefix}${(n / 1e12).toFixed(2)}T`;
  if (abs >= 1e9) return `${prefix}${(n / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${prefix}${(n / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `${prefix}${(n / 1e3).toFixed(1)}K`;
  return `${prefix}${n.toFixed(2)}`;
}

// Slim article preview card for the mobile-caveman scroll stack. Calls the
// same /api/news/semantic-search endpoint the public articles page uses,
// scoped via the ticker tag. Shows up to 5 most recent headlines; the
// footer link drops the user into the full Articles deep-dive tab.
type ArticlePreviewItem = {
  article_id: number;
  title: string | null;
  source: string | null;
  slug: string | null;
  published_at: string | null;
};

function ArticlesInfoCard({ symbol }: { symbol: string }) {
  const [items, setItems] = useState<ArticlePreviewItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!symbol) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    void fetch("/api/news/semantic-search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query: symbol,
        tags: [symbol],
        limit: 5,
        lookback_days: 90,
        mode: "tags",
      }),
    })
      .then((r) => r.json())
      .then((data: { results?: ArticlePreviewItem[]; error?: string }) => {
        if (cancelled) return;
        if (!data?.results) throw new Error(data?.error ?? "Search failed");
        setItems(data.results);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Search failed");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [symbol]);

  return (
    <InfoCard
      icon={<Newspaper className="w-3.5 h-3.5 text-muted-foreground" />}
      title="Recent articles"
    >
      {loading ? (
        <div className="flex items-center gap-2 text-muted-foreground">
          <Loader2 className="h-3 w-3 animate-spin" />
          <span className="text-xs">Loading articles for {symbol}…</span>
        </div>
      ) : error ? (
        <p className="text-xs text-rose-500">{error}</p>
      ) : items.length === 0 ? (
        <p className="text-xs text-muted-foreground">
          No recent articles tagged{" "}
          <span className="font-mono text-foreground">{symbol}</span>.
        </p>
      ) : (
        <div className="flex flex-col gap-3">
          <ul className="-mx-1 divide-y divide-border/60">
            {items.map((item) => (
              <li key={item.article_id}>
                <Link
                  href={
                    item.slug
                      ? `/articles/${item.slug}`
                      : `/articles/${item.article_id}`
                  }
                  className="group block px-1 py-2 transition-colors hover:bg-muted/30"
                >
                  <p className="line-clamp-2 text-sm font-medium leading-snug text-foreground">
                    {item.title || "Untitled"}
                  </p>
                  <div className="mt-1 flex items-center gap-1.5 text-[10px] font-mono uppercase tracking-[0.1em] text-muted-foreground">
                    <span className="truncate">
                      {item.source || "feed"}
                    </span>
                    <span className="text-muted-foreground/40">·</span>
                    <span>
                      {item.published_at
                        ? formatArticleAge(item.published_at)
                        : "—"}
                    </span>
                  </div>
                </Link>
              </li>
            ))}
          </ul>
          <Link
            href={`/articles?tag=${encodeURIComponent(symbol)}`}
            className="inline-flex w-fit items-center gap-1 text-[11px] font-mono uppercase tracking-[0.1em] text-amber-600 dark:text-amber-400 hover:underline"
          >
            <ArrowUpRight className="h-3 w-3" />
            See all articles for {symbol}
          </Link>
        </div>
      )}
    </InfoCard>
  );
}

function formatArticleAge(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const diff = Date.now() - d.getTime();
  if (diff < 0) return "now";
  const m = 60_000;
  const h = 60 * m;
  const day = 24 * h;
  const wk = 7 * day;
  if (diff < h) return `${Math.max(1, Math.floor(diff / m))}m`;
  if (diff < day) return `${Math.floor(diff / h)}h`;
  if (diff < wk) return `${Math.floor(diff / day)}d`;
  return `${Math.floor(diff / wk)}w`;
}

// Sentiment card. Aggregates `sentiment_score` over 7 / 30 / 90 day
// windows for the selected ticker — same data the multi-symbol Sentiment
// view uses, just narrowed to one symbol and rendered as bar rows so it
// fits in the mobile info stack.
function SentimentInfoCard({
  symbol,
  rows,
}: {
  symbol: string;
  rows: ScreeningTickerSentimentHeadRow[];
}) {
  const stats = useMemo(() => {
    const now = Date.now();
    const cutoff = (days: number) =>
      new Date(now - days * 86400000).toISOString().slice(0, 10);
    const targets = [
      { label: "7 days", cutoff: cutoff(7) },
      { label: "30 days", cutoff: cutoff(30) },
      { label: "90 days", cutoff: cutoff(90) },
    ] as const;
    const out = targets.map((t) => {
      let total = 0;
      let count = 0;
      for (const r of rows) {
        if (r.ticker.toUpperCase() !== symbol) continue;
        const day = r.article_ts.slice(0, 10);
        if (day < t.cutoff) continue;
        if (Number.isFinite(r.sentiment_score)) {
          total += r.sentiment_score;
          count += 1;
        }
      }
      return { label: t.label, total, count };
    });
    const maxAbs = Math.max(0.01, ...out.map((s) => Math.abs(s.total)));
    return { rows: out, maxAbs };
  }, [rows, symbol]);

  const totalArticles = useMemo(
    () =>
      rows.reduce(
        (acc, r) => (r.ticker.toUpperCase() === symbol ? acc + 1 : acc),
        0,
      ),
    [rows, symbol],
  );

  return (
    <InfoCard
      icon={<Gauge className="w-3.5 h-3.5 text-muted-foreground" />}
      title="Sentiment"
    >
      {totalArticles === 0 ? (
        <p className="text-xs text-muted-foreground">
          No recent articles tagged with this ticker.
        </p>
      ) : (
        <>
          <div className="flex flex-col gap-2">
            {stats.rows.map((s) => {
              const pct =
                stats.maxAbs > 0 ? Math.abs(s.total) / stats.maxAbs : 0;
              const pos = s.total >= 0;
              const negligible = Math.abs(s.total) < 0.01;
              return (
                <div
                  key={s.label}
                  className="grid grid-cols-[minmax(0,4rem)_minmax(0,1fr)_auto] items-center gap-2"
                >
                  <span className="text-[10px] font-mono uppercase tracking-[0.1em] text-muted-foreground">
                    {s.label}
                  </span>
                  <div className="relative h-1.5 rounded-full bg-muted overflow-hidden">
                    <div className="absolute inset-y-0 left-1/2 w-px bg-border" />
                    <div
                      className={`absolute top-0 h-full rounded-full ${
                        pos
                          ? "bg-emerald-500 left-1/2"
                          : "bg-rose-400 right-1/2"
                      }`}
                      style={{ width: `${pct * 50}%` }}
                    />
                  </div>
                  <span
                    className={`font-mono text-xs tabular-nums w-14 text-right ${
                      negligible
                        ? "text-muted-foreground"
                        : pos
                          ? "text-emerald-500"
                          : "text-rose-400"
                    }`}
                  >
                    {s.total >= 0 ? "+" : ""}
                    {s.total.toFixed(2)}
                  </span>
                </div>
              );
            })}
          </div>
          <p className="text-[10px] font-mono uppercase tracking-[0.1em] text-muted-foreground/70">
            Across {totalArticles} article{totalArticles === 1 ? "" : "s"} ·
            past 120 days
          </p>
        </>
      )}
    </InfoCard>
  );
}

// Company card with expand/collapse for the (often long) FMP description.
// Keeps the expanded state local so toggling doesn't disturb the other
// info-card scroll positions in the parent stack.
function CompanyInfoCard({ profile }: { profile: FmpCompanyProfile }) {
  const [expanded, setExpanded] = useState(false);
  const employees =
    profile.fullTimeEmployees != null
      ? Number(profile.fullTimeEmployees)
      : null;
  const employeesLabel =
    employees != null && Number.isFinite(employees) && employees > 0
      ? formatLargeNumber(employees)
      : null;
  const ipoYear = profile.ipoDate?.slice(0, 4) ?? null;
  const websiteHost = (() => {
    if (!profile.website) return null;
    try {
      return new URL(profile.website).host.replace(/^www\./, "");
    } catch {
      return profile.website;
    }
  })();
  // Heuristic — only show the expand control if there's enough text to be
  // worth expanding (line-clamp-4 with text-xs leading-relaxed clips around
  // ~320 chars on a 358-px-wide card).
  const description = profile.description?.trim() ?? "";
  const isClampable = description.length > 280;

  return (
    <InfoCard
      icon={<Building2 className="w-3.5 h-3.5 text-muted-foreground" />}
      title="Company"
    >
      {profile.companyName ? (
        <p className="text-sm font-medium leading-snug text-foreground">
          {profile.companyName}
        </p>
      ) : null}
      {description ? (
        <div className="flex flex-col gap-1.5">
          <p
            className={`text-xs leading-relaxed text-muted-foreground ${
              isClampable && !expanded ? "line-clamp-4" : ""
            }`}
          >
            {description}
          </p>
          {isClampable && (
            <button
              type="button"
              onClick={() => setExpanded((v) => !v)}
              className="inline-flex w-fit items-center gap-1 text-[11px] font-mono uppercase tracking-[0.1em] text-foreground/70 transition-colors hover:text-foreground"
              aria-expanded={expanded}
            >
              {expanded ? (
                <>
                  <ChevronUp className="h-3 w-3" />
                  Show less
                </>
              ) : (
                <>
                  <ChevronDown className="h-3 w-3" />
                  Read more
                </>
              )}
            </button>
          )}
        </div>
      ) : null}
      {profile.ceo ? <InfoRow label="CEO" value={profile.ceo} /> : null}
      {(profile.sector || profile.industry) && (
        <InfoRow
          label="Sector · Industry"
          value={
            [profile.sector, profile.industry]
              .filter(Boolean)
              .join(" · ") || "—"
          }
        />
      )}
      {(profile.exchange || profile.exchangeFullName) && (
        <InfoRow
          label="Exchange"
          value={profile.exchangeFullName ?? profile.exchange ?? "—"}
        />
      )}
      {(employeesLabel || ipoYear) && (
        <InfoRow
          label="Employees · IPO"
          value={[employeesLabel, ipoYear].filter(Boolean).join(" · ") || "—"}
        />
      )}
      {profile.country ? (
        <InfoRow label="HQ" value={profile.country} />
      ) : null}
      {websiteHost && profile.website ? (
        <a
          href={profile.website}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex w-fit items-center gap-1 text-[11px] font-mono uppercase tracking-[0.1em] text-amber-600 dark:text-amber-400 hover:underline"
        >
          <ExternalLink className="h-3 w-3" />
          {websiteHost}
        </a>
      ) : null}
    </InfoCard>
  );
}

function CavemanInfoCards({
  symbol,
  quote,
  profile,
  sentimentRows,
}: {
  symbol: string;
  quote: FmpQuote | null | undefined;
  profile: FmpCompanyProfile | null;
  sentimentRows: ScreeningTickerSentimentHeadRow[];
}) {
  const yearLow = quote?.yearLow ?? null;
  const yearHigh = quote?.yearHigh ?? null;
  const price = quote?.price ?? null;
  const pctFrom52wHigh =
    yearHigh != null && price != null && yearHigh > 0
      ? ((price - yearHigh) / yearHigh) * 100
      : null;
  const positionPct =
    yearLow != null &&
    yearHigh != null &&
    yearHigh > yearLow &&
    price != null
      ? ((price - yearLow) / (yearHigh - yearLow)) * 100
      : null;

  return (
    <>
      {profile && <CompanyInfoCard profile={profile} />}

      <SentimentInfoCard symbol={symbol} rows={sentimentRows} />

      <InfoCard
        icon={<Activity className="w-3.5 h-3.5 text-muted-foreground" />}
        title="Snapshot"
      >
        <InfoRow
          label="Today's range"
          value={
            quote?.dayLow != null && quote?.dayHigh != null
              ? `$${quote.dayLow.toFixed(2)} – $${quote.dayHigh.toFixed(2)}`
              : "—"
          }
        />
        <InfoRow
          label="Open"
          value={quote?.open != null ? `$${quote.open.toFixed(2)}` : "—"}
        />
        <InfoRow
          label="Volume"
          value={
            quote?.volume != null ? formatLargeNumber(quote.volume) : "—"
          }
        />
        <InfoRow
          label="Market cap"
          value={
            quote?.marketCap != null
              ? formatLargeNumber(quote.marketCap, "$")
              : "—"
          }
        />
      </InfoCard>

      <InfoCard
        icon={<Calendar className="w-3.5 h-3.5 text-muted-foreground" />}
        title="52-week position"
      >
        {positionPct != null && yearLow != null && yearHigh != null ? (
          <div className="flex flex-col gap-1.5">
            <div className="flex items-center justify-between text-[10px] font-mono uppercase tracking-[0.1em] text-muted-foreground">
              <span>${yearLow.toFixed(2)}</span>
              <span>${yearHigh.toFixed(2)}</span>
            </div>
            <div className="relative h-1.5 rounded-full bg-muted">
              <div
                className="absolute top-0 left-0 h-full rounded-full bg-foreground/30"
                style={{
                  width: `${Math.min(100, Math.max(0, positionPct))}%`,
                }}
              />
              <div
                className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 h-3 w-3 rounded-full bg-foreground border-2 border-background"
                style={{
                  left: `${Math.min(100, Math.max(0, positionPct))}%`,
                }}
                aria-label={`Current price at ${positionPct.toFixed(0)}% of 52-week range`}
              />
            </div>
          </div>
        ) : (
          <p className="text-xs text-muted-foreground">No range data.</p>
        )}
        <InfoRow
          label="From 52w high"
          value={
            pctFrom52wHigh != null ? `${pctFrom52wHigh.toFixed(1)}%` : "—"
          }
          tone={
            pctFrom52wHigh == null
              ? "muted"
              : pctFrom52wHigh >= -10
                ? "positive"
                : pctFrom52wHigh >= -25
                  ? "default"
                  : "muted"
          }
        />
        <InfoRow
          label="vs 50-day MA"
          value={
            quote?.priceAvg50 != null && price != null
              ? `${(((price - quote.priceAvg50) / quote.priceAvg50) * 100).toFixed(1)}%`
              : "—"
          }
          tone={
            quote?.priceAvg50 != null && price != null
              ? price >= quote.priceAvg50
                ? "positive"
                : "negative"
              : "muted"
          }
        />
        <InfoRow
          label="vs 200-day MA"
          value={
            quote?.priceAvg200 != null && price != null
              ? `${(((price - quote.priceAvg200) / quote.priceAvg200) * 100).toFixed(1)}%`
              : "—"
          }
          tone={
            quote?.priceAvg200 != null && price != null
              ? price >= quote.priceAvg200
                ? "positive"
                : "negative"
              : "muted"
          }
        />
      </InfoCard>
      {/* The Screen verdict + Fundamentals cards (RS Rank, Trend Template
          flags, EPS growth, ROE, …) used to render here. They surface the
          custom screening row data and the user explicitly asked to drop
          them from the mobile-caveman scroll stack — caveman is meant to
          stay non-technical. The data remains accessible via the
          businessman deep-dive tabs and the right-side AI chat. */}
      <ArticlesInfoCard symbol={symbol} />
    </>
  );
}

// ─── main component ──────────────────────────────────────────────────────────

export function ScreeningsUI({
  runs,
  rows: incomingRows,
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
  // Mirror server rows into local state so optimistic inserts (e.g. "add ticker")
  // are visible instantly without waiting for router.refresh() to round-trip.
  const [rows, setRows] = useState<ScreeningRow[]>(incomingRows);
  // Symbols added in this session — pinned to the top of the filtered list
  // and exempted from filter exclusions until the user changes run.
  const [recentlyAdded, setRecentlyAdded] = useState<Set<string>>(new Set());

  useEffect(() => {
    setRows(incomingRows);
  }, [incomingRows]);

  useEffect(() => {
    setRecentlyAdded(new Set());
  }, [selectedRunId]);
  const [search, setSearch] = useState("");
  const [filters, setFiltersState] = useState<Filters>(DEFAULT_FILTERS);

  const setFilters = useCallback(
    (f: Filters | ((prev: Filters) => Filters)) => {
      setFiltersState((prev) => {
        const next = typeof f === "function" ? f(prev) : f;
        try {
          localStorage.setItem("screenings-filters", JSON.stringify(next));
        } catch {
          /* ignore */
        }
        return next;
      });
    },
    [],
  );
  const [sortKey, setSortKeyState] = useState<SortKey>("RS_Rank");
  const [sortDir, setSortDirState] = useState<SortDir>("desc");

  function setSortKey(k: SortKey) {
    setSortKeyState(k);
    try {
      localStorage.setItem("screenings-sort-key", k);
    } catch {
      /* ignore */
    }
  }
  function setSortDir(d: SortDir | ((prev: SortDir) => SortDir)) {
    setSortDirState((prev) => {
      const next = typeof d === "function" ? d(prev) : d;
      try {
        localStorage.setItem("screenings-sort-dir", next);
      } catch {
        /* ignore */
      }
      return next;
    });
  }
  const [activeView, setActiveView] = useState<ViewTab>("charts");
  const [collapsed, setCollapsed] = useState(false);

  // Caveman mode = simplified UI for non-technical users. Hides multi-symbol
  // tabs, advanced filters, drawing tools and dense sidebar columns. Keeps
  // scan-run switching, ticker add and screening creation intact.
  const { isCaveman } = useCavemanMode();

  // Caveman-mode active range. Shared between the desktop chip strip in the
  // symbol header and the mobile chart-edge swipe arrows. The effect below
  // emits to the chart pipeline whenever this changes in caveman mode.
  const [cavemanRangeId, setCavemanRangeId] = useState<CavemanRangeId>(
    CAVEMAN_DEFAULT_RANGE_ID,
  );

  // When caveman flips on, force the deep-dive Charts view and collapse the
  // AI side panel. Users can re-expand chat manually.
  useEffect(() => {
    if (!isCaveman) return;
    if (activeView !== "charts") setActiveView("charts");
  }, [isCaveman, activeView]);

  // Sync caveman range → chart pipeline. Whenever the active caveman range
  // changes (chip click on desktop, arrow tap on mobile), translate it to
  // from/to + granularity for the chart fetch. Also runs on initial mount.
  useEffect(() => {
    if (!isCaveman) return;
    const r = cavemanRangeToDates(cavemanRangeId);
    if (!r) return;
    setChartGranularity(r.granularity);
    setChartDateRange({ from: r.from, to: r.to });
  }, [isCaveman, cavemanRangeId]);

  const stepCavemanRange = useCallback((delta: number) => {
    setCavemanRangeId((current) => {
      const n = CAVEMAN_RANGES.length;
      const i = CAVEMAN_RANGES.findIndex((r) => r.id === current);
      const next = CAVEMAN_RANGES[(i + delta + n) % n];
      return next?.id ?? current;
    });
  }, []);

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
  const [showDismissedInList, setShowDismissedInList] = useState<boolean>(() => {
    if (typeof window === "undefined") return false;
    try {
      return localStorage.getItem("screenings-show-dismissed") === "1";
    } catch {
      return false;
    }
  });
  const toggleShowDismissedInList = useCallback(() => {
    setShowDismissedInList((prev) => {
      const next = !prev;
      try {
        localStorage.setItem("screenings-show-dismissed", next ? "1" : "0");
      } catch {
        /* ignore */
      }
      return next;
    });
  }, []);
  const [contextMenu, setContextMenu] = useState<{
    ticker: string;
    x: number;
    y: number;
  } | null>(null);
  const [agentAlarmTicker, setAgentAlarmTicker] = useState<string | null>(null);
  const ohlcvDataRef = useRef<OhlcBar[]>([]);
  const openTickerActionsMenu = useCallback((ticker: string, x: number, y: number) => {
    setContextMenu({ ticker, x, y });
  }, []);
  const handleContextMenu = useCallback(
    (ticker: string, e: React.MouseEvent) => {
      e.preventDefault();
      openTickerActionsMenu(ticker, e.clientX, e.clientY);
    },
    [openTickerActionsMenu],
  );
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);
  // FMP company profile for the selected ticker. Drives the "Company" info
  // card under the chart. Cached per-symbol via a Map so flipping back to a
  // previously-viewed ticker is instant.
  const companyProfileCacheRef = useRef<Map<string, FmpCompanyProfile>>(
    new Map(),
  );
  const [companyProfile, setCompanyProfile] =
    useState<FmpCompanyProfile | null>(null);
  useEffect(() => {
    if (!selectedTicker) {
      setCompanyProfile(null);
      return;
    }
    const sym = selectedTicker.trim().toUpperCase();
    const cached = companyProfileCacheRef.current.get(sym);
    if (cached) {
      setCompanyProfile(cached);
      return;
    }
    let cancelled = false;
    void fmpGetCompanyProfile(sym).then((res) => {
      if (cancelled) return;
      if (res.ok) {
        companyProfileCacheRef.current.set(sym, res.data);
        setCompanyProfile(res.data);
      } else {
        setCompanyProfile(null);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [selectedTicker]);

  // Per-ticker sentiment rows (same source as the multi-symbol Sentiment
  // view: `ticker_sentiment_heads_v`). Drives the Sentiment info card in the
  // mobile-caveman scroll stack. Cached per-symbol — flipping tickers reads
  // from the cache instantly.
  const sentimentCacheRef = useRef<
    Map<string, ScreeningTickerSentimentHeadRow[]>
  >(new Map());
  const [tickerSentimentRows, setTickerSentimentRows] = useState<
    ScreeningTickerSentimentHeadRow[]
  >([]);
  useEffect(() => {
    if (!selectedTicker) {
      setTickerSentimentRows([]);
      return;
    }
    const sym = selectedTicker.trim().toUpperCase();
    const cached = sentimentCacheRef.current.get(sym);
    if (cached) {
      setTickerSentimentRows(cached);
      return;
    }
    let cancelled = false;
    void screeningsGetTickerSentimentHeadRows([sym]).then((res) => {
      if (cancelled) return;
      if (res.ok) {
        sentimentCacheRef.current.set(sym, res.data);
        setTickerSentimentRows(res.data);
      } else {
        setTickerSentimentRows([]);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [selectedTicker]);
  const [chartAnnotations, setChartAnnotations] = useState<ChartAnnotation[]>(
    [],
  );
  const [chartAiMessages, setChartAiMessages] = useState<ChartAiChatMessage[]>(
    [],
  );
  const [chartAiOpen, setChartAiOpen] = useState(true);
  const [mobileChatOpen, setMobileChatOpen] = useState(false);
  const [chatMode, setChatMode] = useState<"ticker" | "bulk">("ticker");
  const [streamingTickers, setStreamingTickers] = useState<Set<string>>(
    new Set(),
  );
  const [chartWorkspaceReady, setChartWorkspaceReady] = useState(false);
  const chartSaveSeq = useRef(0);
  const selectedTickerRef = useRef(selectedTicker);
  selectedTickerRef.current = selectedTicker;
  const tickerMessagesCache = useRef(new Map<string, ChartAiChatMessage[]>());
  // Mirror of the sidebar's currently-visible sort order, so dismiss/advance
  // logic can jump to the closest ticker the user actually sees.
  const sortedSidebarOrderRef = useRef<string[]>([]);
  const [chartDateRange, setChartDateRange] = useState<
    { from: string; to: string } | undefined
  >();
  const [chartGranularity, setChartGranularity] =
    useState<ChartGranularity>("1day");

  useEffect(() => {
    setChartWorkspaceReady(false);
    setChartAnnotations([]);

    // If there's cached messages for this ticker (e.g. from an in-flight stream
    // that was running while the user navigated away), restore from cache
    // instead of reloading from DB.
    const cached = selectedTicker
      ? tickerMessagesCache.current.get(selectedTicker)
      : undefined;
    if (cached !== undefined) {
      setChartAiMessages(cached);
      setChartWorkspaceReady(true);
      return;
    }

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
    return () => {
      cancelled = true;
    };
  }, [selectedTicker]);

  // Scoped setter: writes to the per-ticker cache and only updates the display
  // state when the owning ticker is still active. This keeps in-flight streams
  // from clobbering a different ticker's chat, and lets results be restored
  // when the user navigates back.
  const scopedSetChartAiMessages = useCallback(
    (update: React.SetStateAction<ChartAiChatMessage[]>) => {
      const ticker = selectedTicker;
      if (!ticker) return;
      const currentCached = tickerMessagesCache.current.get(ticker) ?? [];
      const next =
        typeof update === "function" ? update(currentCached) : update;
      tickerMessagesCache.current.set(ticker, next);
      if (selectedTickerRef.current === ticker) {
        setChartAiMessages(next);
      }
    },
    [selectedTicker],
  );

  useEffect(() => {
    if (!selectedTicker || !chartWorkspaceReady) return;
    const seq = ++chartSaveSeq.current;
    const t = setTimeout(() => {
      if (seq !== chartSaveSeq.current) return;
      void chartWorkspaceSave(selectedTicker, {
        annotations: chartAnnotations,
        aiChatMessages: chartAiMessages,
      });
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
  const [bulkJob, setBulkJob] = useState<BulkAnalysisJob | null>(null);
  const [bulkStarting, setBulkStarting] = useState(false);
  const [bulkError, setBulkError] = useState<string | null>(null);

  // Load persisted UI preferences only after hydration to avoid SSR/client mismatch.
  useEffect(() => {
    try {
      const storedFilters = localStorage.getItem("screenings-filters");
      if (storedFilters) {
        const parsed = JSON.parse(storedFilters) as Record<string, unknown>;
        // Legacy keys (dynamicTruthys, dynamicNumericMins) merged into the
        // new shape via normalizeScreeningsFilters below, but we still want
        // to honor them if present in old persisted blobs.
        const legacy = parsed as {
          dynamicTruthys?: Record<string, boolean>;
          dynamicNumericMins?: Record<string, string>;
        };
        const normalized = normalizeScreeningsFilters(parsed);
        if (legacy.dynamicTruthys) {
          normalized.boolRequire = {
            ...normalized.boolRequire,
            ...legacy.dynamicTruthys,
          };
        }
        if (legacy.dynamicNumericMins) {
          normalized.numMin = { ...normalized.numMin, ...legacy.dynamicNumericMins };
        }
        setFiltersState(normalized);
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

  // ── Logged trades ─────────────────────────────────────────────────────────
  const [allTrades, setAllTrades] = useState<LoggedTrade[]>([]);

  useEffect(() => {
    void screeningsGetUserTrades().then((res) => {
      if (res.ok) setAllTrades(res.data);
    });
  }, []);

  const tradesByTicker = useMemo(() => {
    const map = new Map<string, LoggedTrade[]>();
    for (const t of allTrades) {
      const list = map.get(t.ticker) ?? [];
      list.push(t);
      map.set(t.ticker, list);
    }
    return map;
  }, [allTrades]);

  const activePositionSymbols = useMemo(() => {
    const set = new Set<string>();
    for (const [ticker, trades] of tradesByTicker) {
      const netLong = trades.reduce((acc, t) => {
        if (t.position_side !== "long") return acc;
        return t.side === "buy" ? acc + t.quantity : acc - t.quantity;
      }, 0);
      const netShort = trades.reduce((acc, t) => {
        if (t.position_side !== "short") return acc;
        return t.side === "sell" ? acc + t.quantity : acc - t.quantity;
      }, 0);
      if (netLong > 0 || netShort > 0) set.add(ticker);
    }
    return set;
  }, [tradesByTicker]);

  // ── Row-level workflow annotations ───────────────────────────────────────
  const [rowNotes, setRowNotes] = useState<Map<number, ScanRowNote>>(
    () => new Map(initialNotes.map((n) => [n.scan_row_id, n])),
  );

  useEffect(() => {
    setRowNotes(new Map(initialNotes.map((n) => [n.scan_row_id, n])));
  }, [selectedRunId, initialNotes]);

  // ── Bulk-analysis job polling ────────────────────────────────────────────
  useEffect(() => {
    if (selectedRunId == null) {
      setBulkJob(null);
      setBulkError(null);
      return;
    }
    let cancelled = false;

    const fetchJob = async () => {
      const res = await getBulkAnalysisJob(selectedRunId);
      if (cancelled) return;
      if (res.ok) {
        setBulkJob(res.data);
        setBulkError(null);
      }
    };

    void fetchJob();
    const interval = setInterval(() => {
      if (cancelled) return;
      // Slow the poll once the job has settled.
      if (bulkJob && (bulkJob.status === "done" || bulkJob.status === "error" || bulkJob.status === "cancelled")) {
        return;
      }
      void fetchJob();
    }, 4000);

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [selectedRunId, bulkJob?.status]);

  // Held in a ref because handleBulkAnalyze is defined before filteredSymbols
  // is computed (the memo lives further down). The ref is updated by an
  // effect after filteredSymbols is in scope, so the callback always reads
  // the latest snapshot at click time without a circular dependency.
  const bulkScopeRef = useRef<{
    filteredSymbols: string[];
    filtersActive: boolean;
    chartGranularity: ChartGranularity;
    chartDateRange: { from: string; to: string } | undefined;
  }>({
    filteredSymbols: [],
    filtersActive: false,
    chartGranularity: "1day",
    chartDateRange: undefined,
  });

  const handleBulkAnalyze = useCallback(async (userPrompt: string) => {
    if (selectedRunId == null || bulkStarting) return;
    if (bulkJob?.status === "queued" || bulkJob?.status === "running") return;
    setBulkStarting(true);
    setBulkError(null);
    try {
      // Snapshot the visible filtered tickers so the worker analyses exactly
      // the rows the user is looking at — not every ticker in the scan run.
      // Pass null (no subset) when no filters are active so the legacy
      // "analyse everything" path stays the default for unfiltered views.
      const {
        filtersActive,
        filteredSymbols: scopeSymbols,
        chartGranularity,
        chartDateRange,
      } = bulkScopeRef.current;
      const subset = filtersActive ? scopeSymbols : null;
      const res = await bulkAnalyzeScanRun(selectedRunId, userPrompt, subset, {
        granularity: chartGranularity,
        dateFrom: chartDateRange?.from ?? null,
        dateTo: chartDateRange?.to ?? null,
      });
      if (res.ok) {
        setBulkJob(res.data);
      } else {
        setBulkError(res.error);
      }
    } finally {
      setBulkStarting(false);
    }
  }, [selectedRunId, bulkStarting, bulkJob?.status]);

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

  async function upsertRowNote(
    row: ScreeningRow,
    patch: {
      status?: NoteStatus;
      highlighted?: boolean;
      comment?: string | null;
      metadataJson?: Record<string, unknown>;
    },
  ) {
    const now = new Date().toISOString();
    const prev = rowNotes.get(row.scan_row_id);
    const next: ScanRowNote = {
      scan_row_id: row.scan_row_id,
      run_id: row.run_id,
      ticker: row.symbol,
      user_id: prev?.user_id ?? "",
      status: patch.status ?? prev?.status ?? "active",
      highlighted: patch.highlighted ?? prev?.highlighted ?? false,
      comment:
        patch.comment !== undefined ? patch.comment : (prev?.comment ?? null),
      stage: prev?.stage ?? null,
      priority: prev?.priority ?? null,
      tags: prev?.tags ?? [],
      metadata_json: patch.metadataJson ?? prev?.metadata_json ?? {},
      created_at: prev?.created_at ?? now,
      updated_at: now,
    };

    setRowNotes((prevMap) => new Map(prevMap).set(row.scan_row_id, next));
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
      setRowNotes((prevMap) => {
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
    if (selectedTicker === ticker) {
      // Auto-advance to the closest non-dismissed ticker in the user's actual
      // visible sort order (sidebar sort), falling back to the source order
      // when the sidebar order isn't available yet.
      const visibleOrder = sortedSidebarOrderRef.current.length
        ? sortedSidebarOrderRef.current
        : filteredSymbols;
      const idx = visibleOrder.indexOf(ticker);
      const nextSymbol =
        visibleOrder
          .slice(idx + 1)
          .find((s) => !dismissedSymbols.has(s) && s !== ticker) ??
        visibleOrder
          .slice(0, idx)
          .reverse()
          .find((s) => !dismissedSymbols.has(s) && s !== ticker) ??
        null;
      setSelectedTicker(nextSymbol);
    }
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

  function getTickerMeta(ticker: string): {
    sector: string;
    industry: string;
    subSector: string;
  } {
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
    const row = rows.find((r) => r.scan_row_id === workflowEditor.scanRowId);
    if (!row) {
      setWorkflowEditor(null);
      return;
    }
    setSavingWorkflowEditor(true);
    try {
      const nextStatus = workflowEditor.status;
      const nextComment = workflowEditor.comment.trim()
        ? workflowEditor.comment.trim()
        : null;
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
    () =>
      [...inferBooleanFilterKeys(rows, dataColumnKeys)].sort((a, b) =>
        a.localeCompare(b),
      ),
    [rows, dataColumnKeys],
  );

  const numFilterKeys = useMemo(
    () =>
      [...inferNumericFilterKeys(rows, dataColumnKeys)].sort((a, b) =>
        a.localeCompare(b),
      ),
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
    const next = dataColumnKeys.includes("RS_Rank")
      ? "RS_Rank"
      : dataColumnKeys.includes("Passed")
        ? "Passed"
        : (dataColumnKeys[0] ?? "symbol");
    setSortKeyState(next);
    setSortDirState(
      next === "symbol" || ["sector", "industry", "subSector"].includes(next)
        ? "asc"
        : "desc",
    );
  }, [rows.length, dataColumnKeys, sortKey]);

  const visibleMultiSymbolTabs = SCREENINGS_MULTI_SYMBOL_TABS;

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

      // Optimistic insert — make the row visible instantly. The real row id and
      // any populated fields arrive on the next router.refresh().
      const optimisticRow = createOptimisticScreeningRow(selectedRunId, sym);
      setRows((prev) => [optimisticRow, ...prev]);
      setRecentlyAdded((prev) => {
        const next = new Set(prev);
        next.add(sym);
        return next;
      });
      setSearch("");

      const res = await screeningsAddTicker(selectedRunId, sym);
      if (!res.ok) {
        // Roll back optimistic insert.
        setRows((prev) =>
          prev.filter(
            (r) => !(r.symbol === sym && r.scan_row_id === OPTIMISTIC_ROW_ID),
          ),
        );
        setRecentlyAdded((prev) => {
          if (!prev.has(sym)) return prev;
          const next = new Set(prev);
          next.delete(sym);
          return next;
        });
        window.alert(res.error);
        return;
      }
      // Patch real id onto the optimistic row so any per-row keyed UI stabilises
      // before the server refresh swaps it for the canonical row.
      const newId = Number(res.data.id);
      setRows((prev) =>
        prev.map((r) =>
          r.symbol === sym && r.scan_row_id === OPTIMISTIC_ROW_ID
            ? { ...r, scan_row_id: newId }
            : r,
        ),
      );
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
        key === "symbol" ||
        key === "sector" ||
        key === "industry" ||
        key === "subSector";
      setSortDir(ascDefault ? "asc" : "desc");
    }
  }

  const filtered = useMemo(() => {
    const base = filterAndSortScreeningRows(
      rows,
      rowNotes,
      filters,
      search,
      sortKey,
      sortDir,
      activePositionSymbols,
    );
    if (recentlyAdded.size === 0) return base;
    // Pin recently-added rows to the top, bypassing filter exclusions so they
    // are always visible right after the user adds them.
    const pinned = rows.filter((r) => recentlyAdded.has(r.symbol));
    const pinnedSyms = new Set(pinned.map((r) => r.symbol));
    const rest = base.filter((r) => !pinnedSyms.has(r.symbol));
    return [...pinned, ...rest];
  }, [
    rows,
    rowNotes,
    filters,
    search,
    sortKey,
    sortDir,
    activePositionSymbols,
    recentlyAdded,
  ]);

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

  const filteredSymbols = useMemo(
    () => filtered.map((r) => r.symbol).filter(Boolean) as string[],
    [filtered],
  );

  // Mirror the current filter scope into a ref so handleBulkAnalyze (defined
  // earlier in the component, before filteredSymbols exists) can read the
  // latest values at click time.
  useEffect(() => {
    bulkScopeRef.current = {
      filteredSymbols,
      filtersActive: countScreeningsFilterRules(filters) > 0,
      chartGranularity,
      chartDateRange,
    };
  }, [filteredSymbols, filters, chartGranularity, chartDateRange]);

  /** Symbols visible in the deep-dive ticker list (sidebar + mobile sheet).
   * Dismissed symbols are hidden by default; user can toggle them back in. */
  const deepDiveListSymbols = useMemo(() => {
    if (showDismissedInList) return filteredSymbols;
    return filteredSymbols.filter((s) => !dismissedSymbols.has(s));
  }, [filteredSymbols, dismissedSymbols, showDismissedInList]);

  // Default selection: when the deep-dive lands without a ticker chosen, pick
  // the first one in the user's currently visible sort order (sidebar header).
  // Falls back to the raw list order only if the sidebar hasn't reported its
  // sort yet (briefly true on the very first mount).
  useEffect(() => {
    if (selectedTicker) return;
    const first =
      sortedSidebarOrderRef.current[0] ?? deepDiveListSymbols[0];
    if (first) setSelectedTicker(first);
  }, [selectedTicker, deepDiveListSymbols]);

  const hiddenDismissedInListCount = useMemo(() => {
    let count = 0;
    for (const s of filteredSymbols) {
      if (dismissedSymbols.has(s)) count++;
    }
    return count;
  }, [filteredSymbols, dismissedSymbols]);

  const { quotes, loading: quotesLoading } = useQuotes(
    filteredSymbols.slice(0, 50),
  );

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
      .map((e) => e.row.symbol)
      .filter((s): s is string => !!s && !seen.has(s));
    extras.sort((a, b) => a.localeCompare(b));
    for (const s of extras) {
      seen.add(s);
      out.push(s);
    }
    return out;
  }, [filteredSymbols, tradeMonitoringRows]);

  const filteredSymbolSet = useMemo(
    () => new Set(filteredSymbols),
    [filteredSymbols],
  );

  const selectedRun =
    runs.find((r) => r.id === selectedRunId) ?? runs[0] ?? null;

  const tradeMonitoringDisabled = !hasAnyEntryMarkers;
  const tradeMonitoringTitle = tradeMonitoringDisabled
    ? "Set a pivot on the Charts tab (right-click) to enable this view"
    : undefined;

  // ── Chat surface (shared between desktop side panel and mobile bottom sheet) ──
  const chatModeTabs = (
    <ChatModeTabs
      mode={chatMode}
      onChange={setChatMode}
      hasTicker={!!selectedTicker}
      selectedTicker={selectedTicker}
      bulkInFlight={
        bulkJob?.status === "queued" ||
        bulkJob?.status === "running" ||
        bulkStarting
      }
    />
  );

  const renderChatBody = (variant: "desktop" | "mobile") => {
    if (chatMode === "bulk") {
      return (
        <BulkAiPanel
          job={bulkJob}
          starting={bulkStarting}
          error={bulkError}
          onStart={handleBulkAnalyze}
          tickerCount={filteredSymbols.length}
          activeFilterCount={countScreeningsFilterRules(filters)}
          chartGranularity={chartGranularity}
          chartDateRange={chartDateRange}
          disabled={selectedRunId == null || rows.length === 0}
        />
      );
    }
    if (!selectedTicker) return <ChatEmptyTickerState />;
    return (
      <ChartAiChat
        key={`${variant}-${selectedTicker}`}
        symbol={selectedTicker}
        ohlcData={ohlcvDataRef.current}
        annotations={chartAnnotations}
        onAnnotations={handleChartAiAnnotations}
        messages={chartAiMessages}
        setMessages={scopedSetChartAiMessages}
        scanRowId={rowBySymbol.get(selectedTicker)?.scan_row_id}
        runId={rowBySymbol.get(selectedTicker)?.run_id}
        onStatusChange={({ status, comment, highlighted, ok }) => {
          if (!ok) return;
          const row = rowBySymbol.get(selectedTicker);
          if (!row) return;
          const now = new Date().toISOString();
          const prev = rowNotes.get(row.scan_row_id);
          const next: ScanRowNote = {
            scan_row_id: row.scan_row_id,
            run_id: row.run_id,
            ticker: row.symbol,
            user_id: prev?.user_id ?? "",
            status,
            highlighted: highlighted ?? prev?.highlighted ?? false,
            comment: comment ?? prev?.comment ?? null,
            stage: prev?.stage ?? null,
            priority: prev?.priority ?? null,
            tags: prev?.tags ?? [],
            metadata_json: prev?.metadata_json ?? {},
            created_at: prev?.created_at ?? now,
            updated_at: now,
          };
          setRowNotes((m) => new Map(m).set(row.scan_row_id, next));
        }}
        onLoadingChange={(loading) => {
          if (!selectedTicker) return;
          setStreamingTickers((prev) => {
            const next = new Set(prev);
            if (loading) next.add(selectedTicker);
            else next.delete(selectedTicker);
            return next;
          });
        }}
        onSaveEntry={(price, direction, takeProfit, stopLoss) => {
          const ohlc = ohlcvDataRef.current;
          const lastIdx = ohlc.length - 1;
          const last = ohlc[lastIdx];
          if (!last) return;
          void setTickerEntryMarker(
            selectedTicker,
            {
              barIdx: lastIdx,
              date: last.date,
              price,
              open: last.open,
              high: last.high,
              low: last.low,
              close: last.close,
            },
            direction,
            takeProfit,
            stopLoss,
          );
        }}
        isStreaming={streamingTickers.has(selectedTicker ?? "")}
        side={variant === "desktop"}
      />
    );
  };

  const tickerBarVisible =
    isDeepDiveView(activeView) && filteredSymbols.length > 0;

  return (
    <div className="flex flex-col h-full min-h-0 w-full pb-[env(safe-area-inset-bottom,0px)]">
      {/* Collapsible: scan runs + search + filters */}
      <div
        id="screenings-top-controls"
        className={`shrink-0 transition-all duration-200 overflow-hidden ${collapsed ? "max-h-0 opacity-0" : "max-h-[2000px] opacity-100"}`}
      >
        {/* Screenings — flat editorial tab strip + inline create form.
            Replaces the previous raised-card pill row. Per the project's
            "data terminal" aesthetic, each run is a column with a hairline
            bottom-border accent for active state — no rounded card chrome. */}
        <div className="flex items-end gap-3 border-b border-border mb-3 min-h-[3.25rem]">
          <span className="shrink-0 self-end pb-2 text-[10px] font-mono uppercase tracking-[0.14em] text-muted-foreground/70">
            Screenings
          </span>
          {runs.length === 0 ? (
            <p className="self-end pb-2 text-xs text-muted-foreground">
              No screenings yet. Name one and click Create — then add tickers
              from the search above.
            </p>
          ) : (
            <div
              data-tour="screen-runs"
              className="flex flex-1 min-w-0 items-end gap-x-4 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
            >
              {runs.map((run) => {
                const active = run.id === (selectedRun?.id ?? null);
                const busy = deletingRunId === run.id;
                return (
                  <div
                    key={run.id}
                    className={`relative group shrink-0 flex flex-col border-b-2 -mb-px transition-colors ${
                      active
                        ? "border-foreground"
                        : "border-transparent hover:border-foreground/30"
                    } ${busy ? "opacity-60" : ""}`}
                  >
                    <button
                      type="button"
                      onClick={() => selectRun(run.id)}
                      disabled={busy}
                      className={`text-left pl-1 pr-7 pt-2 pb-1.5 min-w-[5.5rem] max-w-[180px] transition-colors ${
                        active
                          ? "text-foreground"
                          : "text-muted-foreground hover:text-foreground"
                      }`}
                    >
                      <div className="font-mono text-[13px] font-semibold tabular-nums leading-tight">
                        {run.scan_date}
                      </div>
                      <div
                        className="text-[10px] uppercase tracking-[0.08em] opacity-70 truncate mt-0.5"
                        title={run.source}
                      >
                        {run.source}
                      </div>
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
                      className={`absolute right-0 top-1 p-1 rounded-sm text-muted-foreground/50 transition-all opacity-0 group-hover:opacity-100 focus:opacity-100 hover:text-rose-500 ${busy ? "pointer-events-none opacity-50" : ""}`}
                    >
                      {busy ? (
                        <Loader2 className="w-3 h-3 animate-spin" />
                      ) : (
                        <Trash2 className="w-3 h-3" />
                      )}
                    </button>
                  </div>
                );
              })}
            </div>
          )}
          <form
            data-tour="screen-create"
            className="shrink-0 self-end pb-2 flex items-center gap-1.5"
            onSubmit={(e) => {
              e.preventDefault();
              void handleCreateScreening();
            }}
          >
            <input
              type="text"
              value={newScreeningName}
              onChange={(e) => setNewScreeningName(e.target.value)}
              placeholder="New screening…"
              maxLength={120}
              disabled={creatingRun}
              className="w-44 sm:w-52 rounded-md border border-input bg-background px-2.5 py-1 text-xs placeholder:text-muted-foreground/70 focus:outline-none focus:ring-1 focus:ring-ring disabled:opacity-60"
              aria-label="New screening name"
            />
            <button
              type="submit"
              disabled={creatingRun || !newScreeningName.trim()}
              className="inline-flex items-center gap-1 shrink-0 rounded-md border border-border bg-background px-2 py-1 text-[11px] font-mono uppercase tracking-[0.08em] text-foreground transition-colors hover:bg-muted disabled:pointer-events-none disabled:opacity-40"
              title="Create screening"
            >
              {creatingRun ? (
                <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
              ) : (
                <FolderPlus className="h-3 w-3" aria-hidden />
              )}
              <span className="hidden sm:inline">Create</span>
            </button>
          </form>
        </div>

        {/* Search + count + (caveman) filter widget.
            In caveman mode the view-tabs row is hidden, so the AddFilterWidget
            lives here at the right edge — open it to access the same filter
            wizard businessman users get. When the wizard expands inline we
            hide the search/count siblings so it gets the full row, matching
            the businessman pattern. */}
        <div data-tour="screen-filters" className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center sm:gap-3 mb-2">
          {!(isCaveman && addFilterOpen) && (
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
                aria-describedby={
                  searchAddTickerOffer
                    ? "screenings-search-add-hint"
                    : undefined
                }
              />
            </div>
            {searchAddTickerOffer ? (
              <div
                id="screenings-search-add-hint"
                className="flex flex-col gap-1.5 rounded-md border border-border bg-muted/30 px-2.5 py-2 text-xs"
              >
                <p className="text-muted-foreground leading-snug">
                  No matches in this screening for{" "}
                  <span className="font-mono font-medium text-foreground">
                    {search.trim().toUpperCase()}
                  </span>
                  .
                </p>
                <button
                  type="button"
                  disabled={addTickerBusy}
                  onClick={() => void handleAddTickerFromSearch()}
                  className="inline-flex w-fit items-center gap-1.5 rounded-md border border-border bg-background px-2 py-1 font-medium text-foreground transition-colors hover:bg-muted disabled:pointer-events-none disabled:opacity-40"
                >
                  {addTickerBusy ? (
                    <Loader2
                      className="h-3.5 w-3.5 animate-spin shrink-0"
                      aria-hidden
                    />
                  ) : (
                    <Plus className="h-3.5 w-3.5 shrink-0" aria-hidden />
                  )}
                  Add to this screening
                </button>
              </div>
            ) : null}
          </div>
          )}
          {!isCaveman && dismissedCount > 0 && (() => {
            const showingDismissed =
              filters.statusIn.length === 1 && filters.statusIn[0] === "dismissed";
            return (
            <button
              onClick={() =>
                setFilters((prev) => ({
                  ...prev,
                  statusIn:
                    prev.statusIn.length === 1 && prev.statusIn[0] === "dismissed"
                      ? ["active"]
                      : ["dismissed"],
                  statusNotIn: [],
                }))
              }
              className={`flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-md border transition-colors ${showingDismissed ? "bg-foreground text-background border-foreground" : "border-border text-muted-foreground hover:text-foreground hover:border-foreground/40"}`}
              title={
                showingDismissed ? "Switch to active" : "Show dismissed"
              }
            >
              <Trash2 className="w-3.5 h-3.5" />
              {dismissedCount} dismissed
            </button>
            );
          })()}
          {!(isCaveman && addFilterOpen) && (
            isCaveman ? (
              <span className="text-sm text-muted-foreground ml-auto">
                {filtered.length} stock{filtered.length === 1 ? "" : "s"}
              </span>
            ) : (
              <span className="text-sm text-muted-foreground ml-auto">
                {filtered.length} shown
                {rows.length > 0 && ` / ${rows.length} screened`}
              </span>
            )
          )}
          {isCaveman && (
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
          )}
        </div>
      </div>

      {/* Collapse toggle — its own persistent rail on the seam between the
          collapsible top region and the body. Lives outside the view-tabs row
          so it stays reachable in caveman mode (where view-tabs are hidden)
          and when the top region is collapsed. Labelled so users don't have
          to decode a bare chevron. */}
      <div className="shrink-0 flex justify-center border-b border-border">
        <button
          type="button"
          onClick={() => setCollapsed((c) => !c)}
          className="group inline-flex items-center gap-1.5 -mb-px translate-y-1/2 rounded-full border border-border bg-background px-3 py-1 text-[10px] font-mono uppercase tracking-[0.14em] text-foreground shadow-sm transition-colors hover:border-foreground/40 hover:bg-muted focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 focus:ring-offset-background"
          title={collapsed ? "Show top controls" : "Hide top controls"}
          aria-expanded={!collapsed}
          aria-controls="screenings-top-controls"
        >
          {collapsed ? (
            <ChevronDown className="w-3 h-3 text-muted-foreground group-hover:text-foreground transition-colors" />
          ) : (
            <ChevronUp className="w-3 h-3 text-muted-foreground group-hover:text-foreground transition-colors" />
          )}
          {collapsed ? "Show controls" : "Hide controls"}
        </button>
      </div>

      {/* View tabs — hidden in caveman mode (the only view is Charts). */}
      {!isCaveman && (
      <div className="border-b border-border pb-px shrink-0">
        {/* Mobile-only view picker — its own row so it gets full width */}
        {!addFilterOpen && (
          <div className="sm:hidden mb-2">
            <ScreeningsMobileViewPicker
              activeView={activeView}
              onSelect={setActiveView}
              tradeMonitoringDisabled={tradeMonitoringDisabled}
              tradeMonitoringTitle={tradeMonitoringTitle}
            />
          </div>
        )}
        <div className="flex items-stretch relative">
          {/* Scrollable tab strip — desktop only */}
          <div className="hidden sm:block flex-1 min-w-0 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
            <div className="flex items-end gap-x-0 flex-nowrap min-w-max">
              {!addFilterOpen && (
                <>
                  <div
                    className="flex items-end gap-1 rounded-md bg-muted/30 px-1 pt-1 pb-0 shrink-0"
                    role="group"
                    aria-label="List views — multiple symbols from your filter"
                  >
                    <span className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground px-2 pb-2 shrink-0 hidden sm:inline">
                      Multi-symbol
                    </span>
                    {visibleMultiSymbolTabs.map((tab) => (
                      <button
                        key={tab.id}
                        type="button"
                        onClick={() => setActiveView(tab.id)}
                        className={`shrink-0 flex items-center gap-1.5 px-3 py-2 min-h-[44px] sm:min-h-0 sm:py-2 text-sm font-medium transition-colors border-b-2 -mb-px rounded-t-md ${
                          activeView === tab.id
                            ? "border-foreground text-foreground bg-background"
                            : "border-transparent text-muted-foreground hover:text-foreground"
                        }`}
                      >
                        {tab.icon}
                        <span className="ml-1.5">{tab.label}</span>
                      </button>
                    ))}
                  </div>
                  <div
                    className="w-px shrink-0 self-stretch min-h-[2.25rem] bg-border mx-0.5"
                    role="separator"
                    aria-orientation="vertical"
                    aria-hidden
                  />
                  <div
                    className="flex items-end gap-1 rounded-md bg-muted/30 px-1 pt-1 pb-0 shrink-0"
                    role="group"
                    aria-label="Deep dive — one ticker at a time"
                  >
                    <span className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground px-2 pb-2 shrink-0 hidden sm:inline">
                      Deep dive
                    </span>
                    {SCREENINGS_DEEP_DIVE_TABS.map((tab) => (
                      <button
                        key={tab.id}
                        type="button"
                        onClick={() => setActiveView(tab.id)}
                        className={`shrink-0 flex items-center gap-1.5 px-3 py-2 min-h-[44px] sm:min-h-0 sm:py-2 text-sm font-medium transition-colors border-b-2 -mb-px rounded-t-md ${
                          activeView === tab.id
                            ? "border-foreground text-foreground bg-background"
                            : "border-transparent text-muted-foreground hover:text-foreground"
                        }`}
                      >
                        {tab.icon}
                        <span className="ml-1.5">{tab.label}</span>
                      </button>
                    ))}
                  </div>
                  <div
                    className="w-px shrink-0 self-stretch min-h-[2.25rem] bg-border mx-0.5"
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
                    className={`shrink-0 flex items-center gap-1.5 px-3 py-2 min-h-[44px] sm:min-h-0 sm:py-2 text-sm font-medium transition-colors border-b-2 -mb-px rounded-t-md ${
                      activeView === "tradeMonitoring"
                        ? "border-foreground text-foreground bg-muted/30"
                        : "border-transparent text-muted-foreground hover:text-foreground"
                    } ${tradeMonitoringDisabled ? "opacity-40 cursor-not-allowed hover:text-muted-foreground" : ""}`}
                  >
                    <Activity className="w-3.5 h-3.5" />
                    <span className="ml-1.5">Trades</span>
                  </button>
                </>
              )}
            </div>
          </div>
          {/* AddFilterWidget lives outside overflow-x-auto so its dropdown can overlap the view */}
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
      )}

      {/* Main row: view content + global AI chat side panel (desktop) */}
      <div className="flex flex-1 min-h-0 min-w-0">
      {/* View content — scrollable area */}
      <div
        className={`flex-1 min-w-0 min-h-0 ${isDeepDiveView(activeView) && filteredSymbols.length > 0 ? "overflow-hidden" : "overflow-y-auto"}`}
      >
        {rows.length === 0 ? (
          <div className="text-sm text-muted-foreground py-8 text-center">
            {selectedRun
              ? "No results for this run."
              : "Select a scan run to view results."}
          </div>
        ) : isDeepDiveView(activeView) && filteredSymbols.length > 0 ? (
          <div className="flex flex-col h-full min-h-0">
            <div className="flex min-h-0 flex-1 items-stretch gap-0">
              <div className="hidden min-h-0 w-56 shrink-0 self-stretch border-r border-border sm:flex sm:flex-col sm:overflow-hidden xl:w-64">
                <TickerSidebar
                  symbols={deepDiveListSymbols}
                  quotes={quotes}
                  selectedTicker={selectedTicker}
                  onSelect={setSelectedTicker}
                  getTickerMeta={getTickerMeta}
                  getStatus={getTickerStatus}
                  getSymbolNote={getTickerComment}
                  dismissedSymbols={dismissedSymbols}
                  highlightedSymbols={highlightedSymbols}
                  activePositionSymbols={activePositionSymbols}
                  onContextMenu={handleContextMenu}
                  onOpenActions={(ticker, anchorEl) => {
                    const rect = anchorEl.getBoundingClientRect();
                    openTickerActionsMenu(ticker, rect.left + rect.width / 2, rect.bottom + 4);
                  }}
                  streamingTickers={streamingTickers}
                  getEntryMarker={getTickerEntryMarker}
                  hiddenDismissedCount={hiddenDismissedInListCount}
                  showDismissed={showDismissedInList}
                  onToggleShowDismissed={toggleShowDismissedInList}
                  onSortedOrderChange={(order) => {
                    sortedSidebarOrderRef.current = order;
                  }}
                  isCaveman={isCaveman}
                />
              </div>
              <div
                className={`flex-1 min-w-0 min-h-0 flex flex-col ${activeView === "charts" || activeView === "relationship" ? "overflow-hidden" : "overflow-y-auto gap-4"}`}
              >
                {activeView === "charts" ? (
                  <div className="flex-1 flex flex-col gap-3 w-full min-h-0">
                    <div className="flex-1 flex items-stretch w-full min-h-0">
                      <div
                        className={`flex-1 min-w-0 flex flex-col min-h-0 ${
                          isCaveman
                            ? "overflow-y-auto sm:overflow-hidden"
                            : ""
                        }`}
                      >
                        <DeepDiveSymbolHeader
                          symbol={selectedTicker ?? ""}
                          quote={
                            selectedTicker ? quotes[selectedTicker] : null
                          }
                          meta={
                            selectedTicker
                              ? getTickerMeta(selectedTicker)
                              : { sector: "", industry: "", subSector: "" }
                          }
                          rightSlot={
                            isCaveman ? (
                              <CavemanRangeChips
                                activeId={cavemanRangeId}
                                onSelect={setCavemanRangeId}
                              />
                            ) : (
                              <ChartDateRangePicker
                                onChange={setChartDateRange}
                                onGranularityChange={setChartGranularity}
                              />
                            )
                          }
                        />
                        {isCaveman && selectedTicker && (
                          // Desktop only: above-chart quick actions. On mobile
                          // the same actions are surfaced via the floating
                          // CavemanMobileActionBar pinned above the
                          // MobileTickerBar at the bottom of the viewport.
                          <div className="hidden sm:block">
                            <CavemanQuickActions
                              ticker={selectedTicker}
                              status={getTickerStatus(selectedTicker)}
                              isDismissed={dismissedSymbols.has(selectedTicker)}
                              onSetStatus={(s) =>
                                setTickerStatus(selectedTicker, s)
                              }
                              onDismiss={() => dismissTicker(selectedTicker)}
                              onRestore={() => restoreTicker(selectedTicker)}
                              hasNote={tickerHasComment(selectedTicker)}
                              onEditNote={() =>
                                editTickerComment(selectedTicker)
                              }
                              onSetupAgent={() =>
                                setAgentAlarmTicker(selectedTicker)
                              }
                            />
                          </div>
                        )}
                        {/* Chart title — range + granularity. Each graph gets
                            an explicit label so non-technical users always
                            know what timeframe they're looking at. */}
                        <div className="flex items-center justify-center px-3 py-1.5 sm:justify-start">
                          <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
                            {isCaveman
                              ? CAVEMAN_RANGES.find(
                                  (r) => r.id === cavemanRangeId,
                                )?.label ?? "—"
                              : rangeLabelFromDates(chartDateRange)}
                            <span
                              aria-hidden
                              className="mx-1.5 text-muted-foreground/40"
                            >
                              ·
                            </span>
                            {granularityLabel(chartGranularity)} chart
                          </span>
                        </div>
                        <div
                          className={`relative ${
                            isCaveman
                              ? "shrink-0 h-[calc(100%-9rem)] min-h-[50vh] mx-3 mb-1 rounded-2xl border border-border bg-card shadow-[0_4px_24px_-8px_rgba(0,0,0,0.25)] overflow-hidden sm:mx-0 sm:mb-0 sm:rounded-none sm:border-0 sm:bg-transparent sm:shadow-none sm:overflow-visible sm:flex-1 sm:min-h-0 sm:h-auto"
                              : "flex-1 min-h-0"
                          }`}
                        >
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
                            tradeMarkers={(selectedTicker ? (tradesByTicker.get(selectedTicker) ?? []) : []).map((t) => ({
                              date: t.executed_at.slice(0, 10),
                              price: t.price_per_unit,
                              side: t.side,
                              position_side: t.position_side,
                            }))}
                            showChevronSymbolNav={false}
                            screeningToolbar={false}
                            showSymbolHeadline={false}
                            showChartFrame={false}
                            fillContainer={isCaveman}
                            annotations={isCaveman ? [] : chartAnnotations}
                            onChartData={(rows: OhlcBar[]) => {
                              ohlcvDataRef.current = rows;
                            }}
                            onAnnotationAdd={
                              isCaveman
                                ? undefined
                                : (ann) =>
                                    setChartAnnotations((prev) => [...prev, ann])
                            }
                            onAnnotationDelete={
                              isCaveman
                                ? undefined
                                : (id) =>
                                    setChartAnnotations((prev) =>
                                      prev.filter((a) => a.id !== id),
                                    )
                            }
                            dateRange={chartDateRange}
                            interval={chartGranularity}
                            getReferenceClose={(ticker) => {
                              const q = quotes[ticker];
                              if (!q) return null;
                              return q.previousClose ?? q.price ?? null;
                            }}
                          />
                          {isCaveman && (
                            <CavemanRangeMobileSwipe
                              activeId={cavemanRangeId}
                              onPrev={() => stepCavemanRange(-1)}
                              onNext={() => stepCavemanRange(1)}
                              onSelect={setCavemanRangeId}
                            />
                          )}
                        </div>
                        {/* Tinder-style info stack below the chart on mobile.
                            Reveals additional ticker context as the user
                            scrolls down — same pattern as Tinder's profile
                            details below the photo deck. Mobile + caveman only. */}
                        {isCaveman && selectedTicker && (
                          <div className="sm:hidden flex flex-col gap-2.5 p-3 pb-6 bg-muted/15">
                            <CavemanInfoCards
                              symbol={selectedTicker.toUpperCase()}
                              quote={quotes[selectedTicker]}
                              profile={companyProfile}
                              sentimentRows={tickerSentimentRows}
                            />
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                ) : activeView === "relationship" ? (
                  <div className="flex-1 min-h-0 flex flex-col">
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
                  </div>
                ) : activeView === "articles" ? (
                  <div className="flex-1 min-h-0 flex flex-col">
                    <ScreeningsArticlesView selectedTicker={selectedTicker} />
                  </div>
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
            {/* Caveman floating action bar — pinned above the ticker nav,
                mobile only. Surfaces status / note / agent without consuming
                vertical chart space. */}
            {isCaveman && selectedTicker && (
              <CavemanMobileActionBar
                ticker={selectedTicker}
                status={getTickerStatus(selectedTicker)}
                isDismissed={dismissedSymbols.has(selectedTicker)}
                onSetStatus={(s) => setTickerStatus(selectedTicker, s)}
                onDismiss={() => dismissTicker(selectedTicker)}
                onRestore={() => restoreTicker(selectedTicker)}
                hasNote={tickerHasComment(selectedTicker)}
                onEditNote={() => editTickerComment(selectedTicker)}
                onSetupAgent={() => setAgentAlarmTicker(selectedTicker)}
              />
            )}

            {/* Mobile ticker nav bar — pinned at bottom on mobile, hidden on sm+ */}
            <MobileTickerBar
              symbols={deepDiveListSymbols}
              selectedTicker={selectedTicker}
              onSelect={setSelectedTicker}
              quotes={quotes}
              getStatus={getTickerStatus}
              dismissedSymbols={dismissedSymbols}
              highlightedSymbols={highlightedSymbols}
              getNote={getTickerComment}
              onOpenActions={(ticker, anchorEl) => {
                const rect = anchorEl.getBoundingClientRect();
                openTickerActionsMenu(ticker, rect.left + rect.width / 2, rect.bottom + 4);
              }}
              onEditNote={editTickerComment}
              onDismiss={dismissTicker}
              onRestore={restoreTicker}
              hiddenDismissedCount={hiddenDismissedInListCount}
              showDismissed={showDismissedInList}
              onToggleShowDismissed={toggleShowDismissedInList}
              onOpenChat={() => {
                if (!selectedTicker) setChatMode("bulk");
                setMobileChatOpen(true);
              }}
              chatHasIndicator={
                chartAiMessages.length > 0 ||
                bulkJob?.status === "running" ||
                bulkJob?.status === "queued"
              }
            />
          </div>
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
            activePositionSymbols={activePositionSymbols}
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

        {/* Desktop: collapsible AI chat toggle (always visible) */}
        <button
          type="button"
          onClick={() => setChartAiOpen((v) => !v)}
          className="hidden sm:flex items-center justify-center w-5 shrink-0 border-l border-border bg-background hover:bg-muted transition-colors"
          title={chartAiOpen ? "Collapse AI chat" : "Expand AI chat"}
        >
          {chartAiOpen ? (
            <ChevronRight className="w-3 h-3 text-muted-foreground" />
          ) : (
            <ChevronLeft className="w-3 h-3 text-muted-foreground" />
          )}
        </button>

        {/* Desktop: AI chat side panel (always available, regardless of view) */}
        {chartAiOpen && (
          <div className="hidden sm:flex w-[320px] shrink-0 flex-col border-l border-border min-h-0">
            {chatModeTabs}
            {renderChatBody("desktop")}
          </div>
        )}
      </div>

      {/* Mobile: AI chat bottom sheet (overlay; trigger lives in MobileTickerBar in deep-dive, FAB elsewhere) */}
      <MobileAiChatSheet
        open={mobileChatOpen}
        onOpen={() => {
          if (!selectedTicker) setChatMode("bulk");
          setMobileChatOpen(true);
        }}
        onClose={() => setMobileChatOpen(false)}
        title={
          chatMode === "bulk"
            ? "All tickers"
            : selectedTicker ?? "AI Chat"
        }
        hasIndicator={
          chatMode === "bulk"
            ? bulkJob?.status === "running" || bulkJob?.status === "queued"
            : chartAiMessages.length > 0
        }
        showTrigger={!tickerBarVisible}
      >
        <div className="flex flex-col h-full min-h-0">
          {chatModeTabs}
          <div className="flex-1 min-h-0 flex flex-col">
            {renderChatBody("mobile")}
          </div>
        </div>
      </MobileAiChatSheet>

      {aiSelectedRow && (
        <AiAnalysisPanel
          key={aiSelectedRow.scan_row_id}
          title={`Analyse ${aiSelectedRow.symbol}`}
          system="You are a swing trading assistant. You analyse stock screening data and give setup assessments based on trend template criteria, relative strength, volume action, and fundamentals. Be direct and concise."
          userMessage={buildScreeningsAiMessage(aiSelectedRow)}
          symbol={aiSelectedRow.symbol}
          cacheKey={String(aiSelectedRow.scan_row_id)}
          onClose={() => setAiSelectedRow(null)}
        />
      )}
      {workflowEditor && (
        <div
          className="fixed inset-0 z-50 bg-black/50 flex items-end sm:items-center justify-center sm:p-4"
          onClick={() => !savingWorkflowEditor && setWorkflowEditor(null)}
        >
          <div
            className="w-full max-w-md rounded-t-2xl sm:rounded-lg border border-border bg-background shadow-2xl flex flex-col gap-3 p-4 pb-[max(1rem,env(safe-area-inset-bottom))] sm:pb-4"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Mobile drag handle */}
            <div className="sm:hidden flex items-center justify-center -mt-1 mb-1">
              <div className="w-10 h-1 rounded-full bg-border" />
            </div>
            <div className="flex items-center justify-between">
              <h3 className="text-base font-semibold">Edit note</h3>
              <span className="font-mono text-sm text-muted-foreground">
                {workflowEditor.ticker}
              </span>
            </div>
            <label className="flex flex-col gap-1">
              <span className="text-xs text-muted-foreground">Note</span>
              <textarea
                value={workflowEditor.comment}
                onChange={(e) =>
                  setWorkflowEditor((prev) =>
                    prev ? { ...prev, comment: e.target.value } : prev,
                  )
                }
                rows={6}
                placeholder="What's the setup? Levels, catalysts, risks…"
                className="px-2.5 py-2 text-sm rounded border border-input bg-background focus:outline-none focus:ring-1 focus:ring-ring resize-y min-h-[6.5rem] sm:min-h-0"
                disabled={savingWorkflowEditor}
                autoFocus
              />
            </label>
            <div className="flex items-center justify-end gap-2 pt-1">
              <button
                type="button"
                onClick={() => setWorkflowEditor(null)}
                className="min-h-[44px] sm:min-h-0 px-3 py-1.5 text-sm rounded border border-border hover:bg-muted transition-colors"
                disabled={savingWorkflowEditor}
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => void saveWorkflowEditor()}
                className="min-h-[44px] sm:min-h-0 px-4 py-1.5 text-sm rounded bg-foreground text-background hover:opacity-90 transition-opacity disabled:opacity-50"
                disabled={savingWorkflowEditor}
              >
                {savingWorkflowEditor ? "Saving..." : "Save"}
              </button>
            </div>
          </div>
        </div>
      )}

      {contextMenu &&
        (() => {
          const cm = contextMenu;
          const note = [...rowNotes.values()].find(
            (n) => n.ticker === cm.ticker,
          );
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
              onCopyOhlcv={
                activeView === "charts" && ohlcvDataRef.current.length > 0
                  ? () => {
                      const header = "date,open,high,low,close,volume";
                      const lines = ohlcvDataRef.current.map(
                        (d) =>
                          `${d.date},${d.open},${d.high},${d.low},${d.close},${d.volume}`,
                      );
                      void navigator.clipboard.writeText(
                        [header, ...lines].join("\n"),
                      );
                    }
                  : null
              }
              onSetupAgentAlarm={() => setAgentAlarmTicker(cm.ticker)}
            />
          );
        })()}

      <AgentAlarmDialog
        ticker={agentAlarmTicker}
        open={agentAlarmTicker !== null}
        onClose={() => setAgentAlarmTicker(null)}
      />
    </div>
  );
}

function ChatModeTabs({
  mode,
  onChange,
  hasTicker,
  selectedTicker,
  bulkInFlight,
}: {
  mode: "ticker" | "bulk";
  onChange: (m: "ticker" | "bulk") => void;
  hasTicker: boolean;
  selectedTicker: string | null;
  bulkInFlight: boolean;
}) {
  const tabBase =
    "flex-1 inline-flex items-center justify-center gap-1.5 px-2 py-1.5 text-[12px] font-medium rounded-md transition-colors";
  const tabActive = "bg-background text-foreground shadow-sm";
  const tabInactive = "text-muted-foreground hover:text-foreground";

  return (
    <div className="shrink-0 px-2 py-2 border-b border-border">
      <div
        role="tablist"
        aria-label="AI chat scope"
        className="flex items-center gap-0.5 rounded-md bg-muted/50 p-0.5"
      >
        <button
          type="button"
          role="tab"
          aria-selected={mode === "ticker"}
          disabled={!hasTicker}
          onClick={() => onChange("ticker")}
          className={`${tabBase} ${mode === "ticker" ? tabActive : tabInactive} disabled:opacity-40 disabled:cursor-not-allowed`}
          title={hasTicker ? `Chat about ${selectedTicker}` : "Select a ticker first"}
        >
          <Bot className="w-3.5 h-3.5" />
          <span>{hasTicker && selectedTicker ? selectedTicker : "This ticker"}</span>
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={mode === "bulk"}
          onClick={() => onChange("bulk")}
          className={`${tabBase} ${mode === "bulk" ? tabActive : tabInactive}`}
          title="Run an analysis across every ticker in this screening"
        >
          {bulkInFlight ? (
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
          ) : (
            <Sparkles className="w-3.5 h-3.5" />
          )}
          <span>All tickers</span>
        </button>
      </div>
    </div>
  );
}

function ChatEmptyTickerState() {
  return (
    <div className="flex-1 min-h-0 flex flex-col items-center justify-center px-6 py-8 text-center gap-2">
      <Bot className="w-7 h-7 text-muted-foreground/40" />
      <p className="text-[12px] text-muted-foreground/80 leading-relaxed max-w-[18rem]">
        Pick a ticker on the left to chat about it, or switch to{" "}
        <span className="font-medium text-foreground/80">All tickers</span>{" "}
        to run a bulk analysis across the whole screening.
      </p>
    </div>
  );
}
