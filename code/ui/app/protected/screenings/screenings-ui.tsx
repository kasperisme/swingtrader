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
  FolderPlus,
  Sparkles,
} from "lucide-react";
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
  type BulkAnalysisJob,
  type LoggedTrade,
} from "@/app/actions/screenings";
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
} from "./screenings-filters-model";
import { TickerSidebar } from "./ticker-sidebar";
import { MobileTickerBar } from "./mobile-ticker-bar";
import {
  TickerContextMenu,
  type NoteStatus as ContextMenuNoteStatus,
} from "./ticker-context-menu";
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

export type { ScanRun, ScreeningRow, ScanRowNote } from "./screenings-types";

// ─── filter state (model: screenings-filters-model.ts) ───────────────────────

type Filters = ScreeningsFilters;
const DEFAULT_FILTERS = DEFAULT_SCREENINGS_FILTERS;

/** Sort column: `symbol` or any key present in rowData (discovered per run). */
type SortKey = string;
type SortDir = "asc" | "desc";

// ─── main component ──────────────────────────────────────────────────────────

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
  const [contextMenu, setContextMenu] = useState<{
    ticker: string;
    x: number;
    y: number;
  } | null>(null);
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
  const [chartAnnotations, setChartAnnotations] = useState<ChartAnnotation[]>(
    [],
  );
  const [chartAiMessages, setChartAiMessages] = useState<ChartAiChatMessage[]>(
    [],
  );
  const [chartAiOpen, setChartAiOpen] = useState(true);
  const [mobileChatOpen, setMobileChatOpen] = useState(false);
  const [streamingTickers, setStreamingTickers] = useState<Set<string>>(
    new Set(),
  );
  const [chartWorkspaceReady, setChartWorkspaceReady] = useState(false);
  const chartSaveSeq = useRef(0);
  const selectedTickerRef = useRef(selectedTicker);
  selectedTickerRef.current = selectedTicker;
  const tickerMessagesCache = useRef(new Map<string, ChartAiChatMessage[]>());
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
        const legacy = parsed as {
          dynamicTruthys?: Record<string, boolean>;
          dynamicNumericMins?: Record<string, string>;
        };
        const statusRaw = parsed.status;
        const hrn = parsed.hasRowNote;
        const nh = parsed.noteHighlighted;
        const nc = parsed.noteComment;
        const ap = parsed.activePosition;
        const tagsRaw = parsed.noteTagsAny;
        setFiltersState({
          ...DEFAULT_FILTERS,
          ...(typeof statusRaw === "string"
            ? {
                status:
                  statusRaw === "active"
                    ? "all"
                    : (statusRaw as Filters["status"]),
              }
            : {}),
          ...(hrn === "any" || hrn === "yes" || hrn === "no"
            ? { hasRowNote: hrn }
            : {}),
          ...(nh === "any" || nh === "yes" || nh === "no"
            ? { noteHighlighted: nh }
            : {}),
          ...(nc === "any" || nc === "with" || nc === "without"
            ? { noteComment: nc }
            : {}),
          ...(ap === "any" || ap === "yes" || ap === "no"
            ? { activePosition: ap }
            : {}),
          ...(typeof parsed.noteStage === "string"
            ? { noteStage: parsed.noteStage }
            : {}),
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
                noteTagsAny: tagsRaw.filter(
                  (t): t is string => typeof t === "string",
                ),
              }
            : {}),
          boolRequire: {
            ...DEFAULT_FILTERS.boolRequire,
            ...((parsed.boolRequire as Record<string, boolean> | undefined) ??
              {}),
            ...(legacy.dynamicTruthys ?? {}),
          },
          boolReject: {
            ...DEFAULT_FILTERS.boolReject,
            ...((parsed.boolReject as Record<string, boolean> | undefined) ??
              {}),
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
            ...((parsed.stringOneOf as Record<string, string[]> | undefined) ??
              {}),
          },
          stringContains: {
            ...DEFAULT_FILTERS.stringContains,
            ...((parsed.stringContains as Record<string, string> | undefined) ??
              {}),
          },
          stringEquals: {
            ...DEFAULT_FILTERS.stringEquals,
            ...((parsed.stringEquals as Record<string, string> | undefined) ??
              {}),
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

  const handleBulkAnalyze = useCallback(async (userPrompt: string) => {
    if (selectedRunId == null || bulkStarting) return;
    if (bulkJob?.status === "queued" || bulkJob?.status === "running") return;
    setBulkStarting(true);
    setBulkError(null);
    try {
      const res = await bulkAnalyzeScanRun(selectedRunId, userPrompt);
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
        key === "symbol" ||
        key === "sector" ||
        key === "industry" ||
        key === "subSector";
      setSortDir(ascDefault ? "asc" : "desc");
    }
  }

  const filtered = useMemo(
    () =>
      filterAndSortScreeningRows(
        rows,
        rowNotes,
        filters,
        search,
        sortKey,
        sortDir,
        activePositionSymbols,
      ),
    [rows, rowNotes, filters, search, sortKey, sortDir, activePositionSymbols],
  );

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

  return (
    <div className="flex flex-col h-full min-h-0 w-full pb-[env(safe-area-inset-bottom,0px)]">
      {/* Collapsible: scan runs + search + filters */}
      <div
        className={`shrink-0 transition-all duration-200 overflow-hidden ${collapsed ? "max-h-0 opacity-0" : "max-h-[2000px] opacity-100"}`}
      >
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
              No screenings yet. Name one above and click Create — then add
              tickers from Charts or the Add to screening control.
            </p>
          ) : (
            <div className="flex gap-2 overflow-x-auto pb-1 -mx-1 px-1 [scrollbar-width:thin]">
              {runs.map((run) => {
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
                      <div className="font-medium leading-tight">
                        {run.scan_date}
                      </div>
                      <div
                        className="text-xs opacity-80 truncate mt-0.5"
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
          {dismissedCount > 0 && (
            <button
              onClick={() =>
                setFilters((prev) => ({
                  ...prev,
                  status: prev.status === "dismissed" ? "active" : "dismissed",
                }))
              }
              className={`flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-md border transition-colors ${filters.status === "dismissed" ? "bg-foreground text-background border-foreground" : "border-border text-muted-foreground hover:text-foreground hover:border-foreground/40"}`}
              title={
                filters.status === "dismissed"
                  ? "Switch to active"
                  : "Show dismissed"
              }
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
      <div className="border-b border-border pb-px shrink-0">
        <div className="flex items-stretch relative">
          {/* Collapse toggle — fixed, not scrollable */}
          {!addFilterOpen && (
            <button
              type="button"
              onClick={() => setCollapsed((c) => !c)}
              className="shrink-0 self-center mr-1 p-1.5 rounded-md border border-border text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
              title={collapsed ? "Show filters" : "Hide filters"}
            >
              {collapsed ? (
                <ChevronDown className="w-3.5 h-3.5" />
              ) : (
                <ChevronUp className="w-3.5 h-3.5" />
              )}
            </button>
          )}
          {/* Bulk-analysis trigger — always visible (independent of collapse) */}
          {!addFilterOpen && selectedRunId != null && rows.length > 0 && (
            <div className="shrink-0 self-center mr-2">
              <BulkAnalyzeButton
                job={bulkJob}
                starting={bulkStarting}
                error={bulkError}
                onStart={handleBulkAnalyze}
              />
            </div>
          )}
          {/* Scrollable tab strip */}
          <div className="flex-1 min-w-0 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
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
                    {SCREENINGS_MULTI_SYMBOL_TABS.map((tab) => (
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

      {/* View content — scrollable area */}
      <div
        className={`flex-1 min-h-0 ${isDeepDiveView(activeView) && filteredSymbols.length > 0 ? "overflow-hidden" : "overflow-y-auto"}`}
      >
        {rows.length === 0 ? (
          <div className="text-sm text-muted-foreground py-8 text-center">
            {selectedRun
              ? "No results for this run."
              : "Select a scan run to view results."}
          </div>
        ) : isDeepDiveView(activeView) && filteredSymbols.length > 0 ? (
          <div className="flex flex-col h-full min-h-0">
            {/* Mobile ticker nav bar — hidden on sm+ */}
            <MobileTickerBar
              symbols={filteredSymbols}
              selectedTicker={selectedTicker}
              onSelect={setSelectedTicker}
              quotes={quotes}
              getStatus={getTickerStatus}
              dismissedSymbols={dismissedSymbols}
              highlightedSymbols={highlightedSymbols}
              onOpenActions={(ticker, anchorEl) => {
                const rect = anchorEl.getBoundingClientRect();
                openTickerActionsMenu(ticker, rect.left + rect.width / 2, rect.bottom + 4);
              }}
            />
            <div className="flex min-h-0 flex-1 items-stretch gap-0">
              <div className="hidden min-h-0 w-56 shrink-0 self-stretch border-r border-border sm:flex sm:flex-col sm:overflow-hidden xl:w-64">
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
                  activePositionSymbols={activePositionSymbols}
                  onContextMenu={handleContextMenu}
                  onOpenActions={(ticker, anchorEl) => {
                    const rect = anchorEl.getBoundingClientRect();
                    openTickerActionsMenu(ticker, rect.left + rect.width / 2, rect.bottom + 4);
                  }}
                  streamingTickers={streamingTickers}
                  getEntryMarker={getTickerEntryMarker}
                />
              </div>
              <div
                className={`flex-1 min-w-0 min-h-0 flex flex-col ${activeView === "charts" || activeView === "relationship" ? "overflow-hidden" : "overflow-y-auto gap-4"}`}
              >
                {activeView === "charts" ? (
                  <div className="flex-1 flex flex-col gap-3 w-full min-h-0">
                    <div className="flex-1 flex items-stretch w-full min-h-0">
                      <div className="flex-1 min-w-0">
                        <ChartDateRangePicker
                          onChange={setChartDateRange}
                          onGranularityChange={setChartGranularity}
                        />
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
                          annotations={chartAnnotations}
                          onChartData={(rows: OhlcBar[]) => {
                            ohlcvDataRef.current = rows;
                          }}
                          onAnnotationAdd={(ann) =>
                            setChartAnnotations((prev) => [...prev, ann])
                          }
                          onAnnotationDelete={(id) =>
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
                      </div>
                      {selectedTicker && (
                        <>
                          {/* Desktop: collapsible sidebar toggle + panel */}
                          <button
                            type="button"
                            onClick={() => setChartAiOpen((v) => !v)}
                            className="hidden sm:flex items-center justify-center w-5 shrink-0 border-l border-border bg-background hover:bg-muted transition-colors"
                            title={
                              chartAiOpen
                                ? "Collapse AI chat"
                                : "Expand AI chat"
                            }
                          >
                            {chartAiOpen ? (
                              <ChevronRight className="w-3 h-3 text-muted-foreground" />
                            ) : (
                              <ChevronLeft className="w-3 h-3 text-muted-foreground" />
                            )}
                          </button>
                          {chartAiOpen && (
                            <div className="hidden sm:flex w-[320px] shrink-0 flex-col border-l border-border">
                              <ChartAiChat
                                key={selectedTicker}
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
                                onSaveEntry={(
                                  price,
                                  direction,
                                  takeProfit,
                                  stopLoss,
                                ) => {
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
                                side
                              />
                            </div>
                          )}

                          {/* Mobile: FAB + bottom sheet */}
                          <MobileAiChatSheet
                            open={mobileChatOpen}
                            onOpen={() => setMobileChatOpen(true)}
                            onClose={() => setMobileChatOpen(false)}
                            title={selectedTicker}
                            hasIndicator={chartAiMessages.length > 0}
                          >
                            <ChartAiChat
                              key={`mobile-${selectedTicker}`}
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
                              onSaveEntry={(
                                price,
                                direction,
                                takeProfit,
                                stopLoss,
                              ) => {
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
                            />
                          </MobileAiChatSheet>
                        </>
                      )}
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
          </div>
        ) : activeView === "results" ? (
          <>
            {filtered.length === 0 ? (
              <div className="text-sm text-muted-foreground py-8 text-center">
                No stocks match the current filters.
              </div>
            ) : (
              <div className="overflow-x-auto border border-border">
                <table className="min-w-max w-full text-sm">
                  <thead className="bg-muted/40 border-b border-border">
                    <tr>
                      <th
                        className="sticky left-0 z-10 bg-muted/40 px-3 py-2 text-xs font-medium text-muted-foreground uppercase tracking-wide cursor-pointer select-none hover:text-foreground text-left whitespace-nowrap"
                        onClick={() => toggleSort("symbol")}
                      >
                        Symbol
                        <ScreeningsSortIcon
                          col="symbol"
                          sortKey={sortKey}
                          sortDir={sortDir}
                        />
                      </th>
                      {dataColumnKeys.map((k) => {
                        const boolCol = isBooleanColumn(rows, k);
                        return (
                          <th
                            key={k}
                            title={
                              TECH_CRITERIA.find((t) => t.key === k)?.label ?? k
                            }
                            className={`px-2 py-2 text-xs font-medium text-muted-foreground uppercase tracking-wide whitespace-nowrap cursor-pointer select-none hover:text-foreground ${
                              boolCol ? "text-center" : "text-left"
                            }`}
                            onClick={() => toggleSort(k)}
                          >
                            {screeningsColumnHeaderShort(k)}
                            <ScreeningsSortIcon
                            col={k}
                            sortKey={sortKey}
                            sortDir={sortDir}
                          />
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
                      const isAiSelected =
                        aiSelectedRow?.scan_row_id === row.scan_row_id;
                      const note = rowNotes.get(row.scan_row_id);
                      const isDismissed = note?.status === "dismissed";
                      const isHighlighted = !!note?.highlighted;
                      const hasPosition = activePositionSymbols.has(row.symbol ?? "");
                      const status = note?.status ?? "active";
                      const statusStripe: Record<string, string> = {
                        dismissed: "border-l-rose-400",
                        watchlist: "border-l-amber-400",
                        pipeline: "border-l-sky-400",
                        active: "border-l-emerald-400",
                      };
                      const stripe =
                        isDismissed || isHighlighted || isSelected
                          ? (statusStripe[status] ?? "border-l-transparent")
                          : "";
                      return (
                        <tr
                          key={row.scan_row_id ?? row.symbol ?? i}
                          onClick={() =>
                            row.symbol && setSelectedTicker(row.symbol)
                          }
                          onDoubleClick={() =>
                            row.symbol &&
                            void openTickerWorkflowEditor(row.symbol)
                          }
                          onContextMenu={(e) =>
                            row.symbol && handleContextMenu(row.symbol, e)
                          }
                          className={`group cursor-pointer transition-colors border-l-[3px] ${stripe || "border-l-transparent"} ${isDismissed ? "opacity-40" : ""} ${isHighlighted ? "bg-amber-500/10" : ""} ${isSelected ? "bg-foreground/10 ring-1 ring-inset ring-foreground/20" : "hover:bg-muted/30"}`}
                        >
                          <td
                            className={`sticky left-0 z-10 px-3 py-2 font-mono font-semibold whitespace-nowrap ${isSelected ? "bg-foreground/10" : isHighlighted ? "bg-amber-500/10" : "bg-background"}`}
                          >
                            <span className="flex items-center gap-1.5">
                              {hasPosition && (
                                <span
                                  className="shrink-0 w-1.5 h-1.5 rounded-full bg-emerald-400"
                                  title="Active position"
                                />
                              )}
                              {row.symbol ?? "—"}
                            </span>
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
                              <Check
                                value={vectorTickers.has(row.symbol ?? "")}
                              />
                            </div>
                          </td>
                          <td
                            className="px-2 py-1.5 text-center"
                            onClick={(e) => e.stopPropagation()}
                          >
                            <button
                              type="button"
                              title={`Analyse ${row.symbol} with AI`}
                              onClick={() =>
                                setAiSelectedRow(isAiSelected ? null : row)
                              }
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
                <summary className="cursor-pointer hover:text-foreground">
                  Column key
                </summary>
                <div className="mt-2 grid grid-cols-2 gap-x-6 gap-y-0.5 pl-2">
                  <div>
                    <span className="font-mono font-medium">Symbol</span> — From
                    scan row (not duplicated from{" "}
                    <code className="text-[10px]">row_data</code>)
                  </div>
                  {dataColumnKeys.map((k) => {
                    const tech = TECH_CRITERIA.find((t) => t.key === k);
                    return (
                      <div key={k}>
                        <span className="font-mono font-medium">
                          {screeningsColumnHeaderShort(k)}
                        </span>
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
                    <span className="font-mono font-medium">Vec</span> — Company
                    sensitivity vector in database
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
          className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4"
          onClick={() => !savingWorkflowEditor && setWorkflowEditor(null)}
        >
          <div
            className="w-full max-w-md rounded-lg border border-border bg-background p-4 shadow-xl flex flex-col gap-3"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between">
              <h3 className="text-base font-semibold">Workflow update</h3>
              <span className="font-mono text-sm text-muted-foreground">
                {workflowEditor.ticker}
              </span>
            </div>
            <label className="flex flex-col gap-1">
              <span className="text-xs text-muted-foreground">Status</span>
              <select
                value={workflowEditor.status}
                onChange={(e) =>
                  setWorkflowEditor((prev) =>
                    prev
                      ? { ...prev, status: e.target.value as NoteStatus }
                      : prev,
                  )
                }
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
                onChange={(e) =>
                  setWorkflowEditor((prev) =>
                    prev ? { ...prev, comment: e.target.value } : prev,
                  )
                }
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
            />
          );
        })()}
    </div>
  );
}

const BULK_ANALYZE_DEFAULT_PROMPT =
  "Run a swing-trading technical analysis. Highlight setup quality, key levels, and any risks.";

function BulkAnalyzeButton({
  job,
  starting,
  error,
  onStart,
}: {
  job: BulkAnalysisJob | null;
  starting: boolean;
  error: string | null;
  onStart: (userPrompt: string) => Promise<void> | void;
}) {
  const inFlight = job?.status === "queued" || job?.status === "running";
  const [panelOpen, setPanelOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const containerRef = useRef<HTMLDivElement | null>(null);

  // Seed the draft from the previous job's prompt when the panel opens.
  useEffect(() => {
    if (panelOpen) {
      setDraft((prev) => prev || job?.user_prompt || "");
    }
  }, [panelOpen, job?.user_prompt]);

  // Close on outside click or Esc.
  useEffect(() => {
    if (!panelOpen) return;
    const onDown = (e: MouseEvent) => {
      if (!containerRef.current) return;
      if (!containerRef.current.contains(e.target as Node)) setPanelOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setPanelOpen(false);
    };
    window.addEventListener("mousedown", onDown);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("mousedown", onDown);
      window.removeEventListener("keydown", onKey);
    };
  }, [panelOpen]);

  let label: string;
  let title: string;
  if (starting) {
    label = "Starting…";
    title = "Queueing bulk analysis";
  } else if (job?.status === "queued") {
    label = "Queued";
    title = "Job is queued — worker will pick it up within a minute";
  } else if (job?.status === "running") {
    const total = job.total_tickers || 0;
    const done = job.completed_tickers || 0;
    label = total ? `Running ${done}/${total}` : "Running…";
    title = `Bulk analysis in progress${job.failed_tickers ? ` — ${job.failed_tickers} failed` : ""}`;
  } else if (job?.status === "done") {
    const succeeded = Math.max(0, (job.completed_tickers ?? 0) - (job.failed_tickers ?? 0));
    label = `Re-analyze all (last: ${succeeded}/${job.total_tickers})`;
    title = "Bulk analysis completed — click to run again";
  } else if (job?.status === "error") {
    label = "Re-analyze all (last failed)";
    title = job.error_message || "Previous job errored";
  } else {
    label = "Analyze all";
    title = "Run a per-ticker technical analysis on every ticker in this screening";
  }

  const handleClick = () => {
    if (inFlight || starting) return;
    setPanelOpen((o) => !o);
  };

  const handleSubmit = async () => {
    const prompt = draft.trim() || BULK_ANALYZE_DEFAULT_PROMPT;
    setPanelOpen(false);
    await onStart(prompt);
  };

  return (
    <div ref={containerRef} className="relative flex flex-col gap-1">
      <button
        type="button"
        onClick={handleClick}
        disabled={starting || inFlight}
        title={title}
        className={`flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-md border transition-colors ${
          inFlight
            ? "border-primary/40 bg-primary/10 text-primary"
            : "border-border text-muted-foreground hover:text-foreground hover:border-foreground/40"
        } disabled:pointer-events-none disabled:opacity-60`}
      >
        {inFlight || starting ? (
          <Loader2 className="w-3.5 h-3.5 animate-spin" />
        ) : (
          <Sparkles className="w-3.5 h-3.5" />
        )}
        {label}
      </button>
      {error ? (
        <span className="text-[11px] text-destructive max-w-[16rem] truncate" title={error}>
          {error}
        </span>
      ) : null}

      {panelOpen && !inFlight && !starting ? (
        <div className="absolute z-50 top-full left-0 mt-2 w-[22rem] max-w-[90vw] rounded-md border border-border bg-popover text-popover-foreground shadow-lg p-3">
          <div className="flex flex-col gap-2">
            <label className="text-xs font-medium text-foreground">
              What should the analyst look for?
            </label>
            <textarea
              autoFocus
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
                  e.preventDefault();
                  void handleSubmit();
                }
              }}
              placeholder={BULK_ANALYZE_DEFAULT_PROMPT}
              rows={4}
              maxLength={2000}
              className="w-full text-xs rounded-md border border-input bg-background px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-ring resize-none"
            />
            <div className="flex items-center justify-between text-[11px] text-muted-foreground">
              <span>Runs locally on Ollama. ⌘/Ctrl+Enter to start.</span>
              <span>{draft.length}/2000</span>
            </div>
            <div className="flex items-center justify-end gap-2 pt-1">
              <button
                type="button"
                onClick={() => setPanelOpen(false)}
                className="text-xs px-2.5 py-1.5 rounded-md border border-border text-muted-foreground hover:text-foreground"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => void handleSubmit()}
                className="text-xs px-2.5 py-1.5 rounded-md border border-foreground bg-foreground text-background hover:opacity-90"
              >
                Start
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
