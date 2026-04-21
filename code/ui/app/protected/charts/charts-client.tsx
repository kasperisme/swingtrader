"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Loader2 } from "lucide-react";
import { chartWorkspaceLoad, chartWorkspaceSave, type ChartAiChatMessage } from "@/app/actions/chart-workspace";
import { relationshipsResolveTicker } from "@/app/actions/relationships";
import { TickerSearchCombobox } from "@/components/ticker-search-combobox";
import {
  TickerChartsPanel,
  type ChartAnnotation,
  type ChartPoint,
  type OhlcBar,
  type PivotMarker,
  type TickerChartNoteStatus,
} from "@/components/ticker-charts";
import { ChartAiChat } from "@/components/chart-ai-chat";
import { AddToScreening } from "@/components/add-to-screening";

const DEFAULT_TICKERS = ["SPY", "QQQ", "IWM"] as const;

type QuickRange = "7d" | "30d" | "90d" | "1y" | "3y" | "custom";

const pad2 = (n: number) => String(n).padStart(2, "0");

function localDateStr(d: Date): string {
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
}

function parseTickersParam(raw: string | undefined): string[] {
  if (!raw?.trim()) return [...DEFAULT_TICKERS];
  const parts = raw
    .split(/[\s,]+/)
    .map((s) => s.trim().toUpperCase())
    .filter(Boolean);
  const uniq = [...new Set(parts)];
  return uniq.length > 0 ? uniq : [...DEFAULT_TICKERS];
}

type Props = {
  tickersParam: string | undefined;
  suggestionTickers: string[];
};

export function ChartsPageClient({
  tickersParam,
  suggestionTickers,
}: Props) {
  const initial = useMemo(() => parseTickersParam(tickersParam), [tickersParam]);
  const [symbols, setSymbols] = useState<string[]>(() => initial);
  const [selectedTicker, setSelectedTicker] = useState<string | null>(
    () => initial[0] ?? null,
  );
  const [searchInput, setSearchInput] = useState(
    () => initial[0] ?? "AAPL",
  );
  const [resolveError, setResolveError] = useState<string | null>(null);
  const [resolving, setResolving] = useState(false);
  const [pivots, setPivots] = useState<Record<string, PivotMarker | null>>({});
  const [chartData, setChartData] = useState<OhlcBar[]>([]);
  const [annotations, setAnnotations] = useState<ChartAnnotation[]>([]);
  const [aiChatMessages, setAiChatMessages] = useState<ChartAiChatMessage[]>([]);
  const [workspaceReady, setWorkspaceReady] = useState(false);
  const saveSeq = useRef(0);

  const [quickRange, setQuickRange] = useState<QuickRange>("1y");
  const [dateFrom, setDateFrom] = useState<string>("");
  const [dateTo, setDateTo] = useState<string>("");

  const todayStr = useMemo(() => localDateStr(new Date()), []);

  function applyQuickRange(range: QuickRange) {
    setQuickRange(range);
    if (range === "custom") return;
    const days =
      range === "7d" ? 7 : range === "30d" ? 30 : range === "90d" ? 90 : range === "1y" ? 365 : 365 * 3;
    const end = new Date();
    const start = new Date(end);
    start.setDate(start.getDate() - days);
    setDateFrom(localDateStr(start));
    setDateTo(localDateStr(end));
  }

  useEffect(() => {
    applyQuickRange("1y");
  }, []);

  const dateRange = useMemo<{ from: string; to: string } | undefined>(() => {
    if (!dateFrom || !dateTo) return undefined;
    return { from: dateFrom, to: dateTo };
  }, [dateFrom, dateTo]);

  useEffect(() => {
    setChartData([]);
  }, [selectedTicker]);

  useEffect(() => {
    setWorkspaceReady(false);
    if (!selectedTicker) {
      setAnnotations([]);
      setAiChatMessages([]);
      return;
    }
    setAnnotations([]);
    setAiChatMessages([]);
    let cancelled = false;
    void chartWorkspaceLoad(selectedTicker).then((res) => {
      if (cancelled) return;
      if (res.ok) {
        setAnnotations(res.data.annotations);
        setAiChatMessages(res.data.aiChatMessages);
      } else {
        console.error("chartWorkspaceLoad:", res.error);
      }
      if (!cancelled) setWorkspaceReady(true);
    });
    return () => {
      cancelled = true;
    };
  }, [selectedTicker]);

  useEffect(() => {
    if (!selectedTicker || !workspaceReady) return;
    const seq = ++saveSeq.current;
    const t = setTimeout(() => {
      if (seq !== saveSeq.current) return;
      void chartWorkspaceSave(selectedTicker, {
        annotations,
        aiChatMessages,
      });
    }, 750);
    return () => {
      clearTimeout(t);
    };
  }, [annotations, aiChatMessages, selectedTicker, workspaceReady]);

  const dismissed = useMemo(() => new Set<string>(), []);

  useEffect(() => {
    if (selectedTicker) setSearchInput(selectedTicker);
  }, [selectedTicker]);

  const comboboxOptions = useMemo(() => {
    const base = new Set<string>();
    for (const t of suggestionTickers) base.add(t);
    for (const t of symbols) base.add(t);
    const q = searchInput.trim().toUpperCase();
    if (q) base.add(q);
    return Array.from(base).filter(Boolean).sort((a, b) => a.localeCompare(b));
  }, [searchInput, suggestionTickers, symbols]);

  const applyResolvedTicker = useCallback(async () => {
    setResolveError(null);
    setResolving(true);
    try {
      const resolved = await relationshipsResolveTicker(searchInput);
      if (!resolved.ok) {
        setResolveError(resolved.error);
        return;
      }
      const canonical = resolved.data.canonicalTicker;
      setSymbols((prev) =>
        prev.includes(canonical) ? prev : [...prev, canonical],
      );
      setSelectedTicker(canonical);
      setSearchInput(canonical);
    } finally {
      setResolving(false);
    }
  }, [searchInput]);

  const getPivotMarker = useCallback(
    (ticker: string) => pivots[ticker] ?? null,
    [pivots],
  );
  const onSetPivotMarker = useCallback((ticker: string, point: ChartPoint) => {
    setPivots((prev) => ({
      ...prev,
      [ticker]: {
        barIdx: point.barIdx,
        date: point.date,
        price: point.price,
      },
    }));
  }, []);
  const onClearPivotMarker = useCallback((ticker: string) => {
    setPivots((prev) => {
      const next = { ...prev };
      delete next[ticker];
      return next;
    });
  }, []);

  const handleAiAnnotations = useCallback((aiAnnotations: ChartAnnotation[]) => {
    setAnnotations((prev) => [
      ...prev.filter((a) => a.origin === "user"),
      ...aiAnnotations.map((a) => ({ ...a, origin: "ai" as const })),
    ]);
  }, []);

  const handleAnnotationAdd = useCallback((ann: ChartAnnotation) => {
    setAnnotations((prev) => [...prev, ann]);
  }, []);

  const handleAnnotationDelete = useCallback((id: string) => {
    setAnnotations((prev) => prev.filter((a) => a.id !== id));
  }, []);

  const noop = useCallback(() => {}, []);
  const getStatus = useCallback((_ticker: string): TickerChartNoteStatus => "active", []);
  const onSetStatus = useCallback((_t: string, _s: TickerChartNoteStatus) => {}, []);
  const hasComment = useCallback(() => false, []);
  const getTickerMeta = useCallback(
    (_ticker: string) => ({ sector: "", industry: "" }),
    [],
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-3 md:grid-cols-6">
        <TickerSearchCombobox
          className="md:col-span-5"
          value={searchInput}
          onChange={setSearchInput}
          onSubmit={() => void applyResolvedTicker()}
          options={comboboxOptions}
          placeholder="Search ticker or alias…"
        />
        <button
          type="button"
          onClick={() => void applyResolvedTicker()}
          className="h-9 rounded-md border border-border bg-background px-3 text-sm font-medium text-foreground transition-colors hover:bg-muted"
          disabled={resolving}
        >
          {resolving ? (
            <span className="inline-flex items-center justify-center gap-2">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading…
            </span>
          ) : (
            "Explore"
          )}
        </button>
      </div>
      {resolveError ? (
        <p className="text-sm text-destructive" role="alert">
          {resolveError}
        </p>
      ) : null}

      {/* Date range toolbar — same design as news-trends */}
      <div className="flex items-stretch rounded-xl border border-border bg-card overflow-x-auto overflow-y-visible">
        <div className="flex items-center px-3 py-2 border-r border-border shrink-0">
          <span className="text-[10px] font-medium text-muted-foreground/60 uppercase tracking-wide">
            Range
          </span>
        </div>
        {(["7d", "30d", "90d", "1y", "3y"] as QuickRange[]).map((r) => (
          <button
            key={r}
            onClick={() => applyQuickRange(r)}
            className={`text-[11px] px-3 py-2 transition-colors cursor-pointer border-r border-border ${
              quickRange === r
                ? "bg-foreground text-background"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            {r}
          </button>
        ))}
        <div className="flex items-center gap-1.5 px-3 py-2 border-r border-border shrink-0">
          <input
            type="date"
            value={dateFrom}
            max={dateTo || todayStr}
            onChange={(e) => {
              setDateFrom(e.target.value);
              setQuickRange("custom");
            }}
            className="text-[11px] bg-transparent text-foreground focus:outline-none cursor-pointer"
          />
          <span className="text-[10px] text-muted-foreground/40">—</span>
          <input
            type="date"
            value={dateTo}
            min={dateFrom}
            max={todayStr}
            onChange={(e) => {
              setDateTo(e.target.value);
              setQuickRange("custom");
            }}
            className="text-[11px] bg-transparent text-foreground focus:outline-none cursor-pointer"
          />
        </div>
      </div>

      <div className="rounded-lg border border-border overflow-hidden">
        <TickerChartsPanel
          symbols={symbols}
          selectedTicker={selectedTicker}
          onSelect={setSelectedTicker}
          dismissed={dismissed}
          onDismiss={noop}
          onRestore={noop}
          getStatus={getStatus}
          onSetStatus={onSetStatus}
          hasComment={hasComment}
          onEditComment={noop}
          getTickerMeta={getTickerMeta}
          getPivotMarker={getPivotMarker}
          onSetPivotMarker={onSetPivotMarker}
          onClearPivotMarker={onClearPivotMarker}
          screeningToolbar={false}
          showChevronSymbolNav={false}
          showSymbolHeadline={false}
          annotations={annotations}
          onChartData={setChartData}
          onAnnotationAdd={handleAnnotationAdd}
          onAnnotationDelete={handleAnnotationDelete}
          symbolPicker={selectedTicker ? <AddToScreening ticker={selectedTicker} /> : undefined}
          dateRange={dateRange}
        />
        {selectedTicker && (
          <ChartAiChat
            key={selectedTicker}
            symbol={selectedTicker}
            ohlcData={chartData}
            annotations={annotations}
            onAnnotations={handleAiAnnotations}
            messages={aiChatMessages}
            setMessages={setAiChatMessages}
          />
        )}
      </div>
    </div>
  );
}