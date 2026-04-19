"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Loader2 } from "lucide-react";
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

const DEFAULT_TICKERS = ["SPY", "QQQ", "IWM"] as const;

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

  useEffect(() => {
    setAnnotations([]);
    setChartData([]);
  }, [selectedTicker]);

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
        />
        {selectedTicker && (
          <ChartAiChat
            key={selectedTicker}
            symbol={selectedTicker}
            ohlcData={chartData}
            annotations={annotations}
            onAnnotations={handleAiAnnotations}
          />
        )}
      </div>
    </div>
  );
}
