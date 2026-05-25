"use client";

import {
  useState,
  useMemo,
  useEffect,
  useCallback,
  useRef,
  type ReactNode,
} from "react";
import {
  ChevronLeft,
  ChevronRight,
  RotateCcw,
  Trash2,
  MessageSquare,
  Copy,
  Minus,
  SquareDashed,
  TrendingUp,
  MousePointer2,
} from "lucide-react";
import { CandlestickSvg } from "./candlestick-svg";
import type { AnnotationRole, ChartAnnotation, ChartPoint, OhlcBar, EntryMarker } from "./types";

export type TickerChartNoteStatus =
  | "active"
  | "dismissed"
  | "watchlist"
  | "pipeline";

export type TickerChartsPanelProps = {
  symbols: string[];
  selectedTicker: string | null;
  onSelect: (ticker: string) => void;
  dismissed: Set<string>;
  onDismiss: (ticker: string) => void;
  onRestore: (ticker: string) => void;
  getStatus: (ticker: string) => TickerChartNoteStatus;
  onSetStatus: (ticker: string, status: TickerChartNoteStatus) => void;
  hasComment: (ticker: string) => boolean;
  onEditComment: (ticker: string) => void;
  getTickerMeta: (ticker: string) => { sector: string; industry: string; subSector?: string };
  getEntryMarker: (ticker: string) => EntryMarker | null;
  onSetEntryMarker: (
    ticker: string,
    point: ChartPoint,
    direction?: "long" | "short",
    takeProfit?: number | null,
    stopLoss?: number | null,
  ) => void;
  onClearEntryMarker: (ticker: string) => void;
  /** When false, hides dismiss / status / note controls (e.g. standalone research page). */
  screeningToolbar?: boolean;
  /** Optional control rendered before the “next” chevron (e.g. screenings symbol dropdown). */
  symbolPicker?: ReactNode;
  /** When false, hides prev/next chevrons and ←/→ symbol stepping (standalone charts page). */
  showChevronSymbolNav?: boolean;
  /** When false, hides the large symbol, sector line, and “i / n” counter (e.g. charts page). */
  showSymbolHeadline?: boolean;
  /** Logged trade executions to show as buy/sell triangles on the chart. */
  tradeMarkers?: Array<{ date: string; price: number; side: "buy" | "sell"; position_side: "long" | "short" }>;
  /** Annotations to overlay on the chart (AI + user). */
  annotations?: ChartAnnotation[];
  /** Called whenever OHLC data loads or updates for the selected ticker. */
  onChartData?: (rows: OhlcBar[]) => void;
  /** Called when the user draws a new annotation. */
  onAnnotationAdd?: (ann: ChartAnnotation) => void;
  /** Called when the user deletes an annotation by clicking it. */
  onAnnotationDelete?: (id: string) => void;
  /** When false, removes bordered chart frame (used in screenings deep-dive). */
  showChartFrame?: boolean;
  /** Date range to pass to the OHLC fetch (controls initial from/to). */
  dateRange?: { from: string; to: string };
  /** OHLC granularity: "1hour" | "4hour" | "1day" | "1week". */
  interval?: string;
  /** Optional external close reference (e.g. quote previousClose) for "vs entry". */
  getReferenceClose?: (ticker: string) => number | null;
  /** When true, the chart sizes its viewBox to the parent's actual pixels so
   * it fills both axes (used in the caveman Tinder-style card layout). */
  fillContainer?: boolean;
};

export function TickerChartsPanel({
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
  getEntryMarker,
  onSetEntryMarker,
  onClearEntryMarker,
  screeningToolbar = true,
  symbolPicker,
  showChevronSymbolNav = true,
  showSymbolHeadline = true,
  tradeMarkers,
  annotations = [],
  onChartData: onChartDataProp,
  onAnnotationAdd,
  onAnnotationDelete,
  showChartFrame = true,
  dateRange,
  interval,
  getReferenceClose,
  fillContainer = false,
}: TickerChartsPanelProps) {
  const symbol = useMemo(() => {
    if (symbols.length === 0) return "";
    if (selectedTicker != null && symbols.includes(selectedTicker)) {
      return selectedTicker;
    }
    return symbols[0] ?? "";
  }, [symbols, selectedTicker]);

  /** Index in `symbols` for prev/next stepping — derived from the charted symbol. */
  const idx = useMemo(() => {
    if (symbols.length === 0) return 0;
    const i = symbols.indexOf(symbol);
    return i >= 0 ? i : 0;
  }, [symbols, symbol]);

  useEffect(() => {
    if (!showChevronSymbolNav) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "ArrowLeft") onSelect(symbols[Math.max(0, idx - 1)]);
      if (e.key === "ArrowRight")
        onSelect(symbols[Math.min(symbols.length - 1, idx + 1)]);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [idx, symbols, onSelect, showChevronSymbolNav]);

  const [activePoint, setActivePoint] = useState<ChartPoint | null>(null);
  const activePointRef = useRef<ChartPoint | null>(null);
  activePointRef.current = activePoint;
  const [entryMenu, setEntryMenu] = useState<{
    x: number;
    y: number;
    pointSnapshot: ChartPoint | null;
  } | null>(null);
  const entryMenuRef = useRef<HTMLDivElement>(null);
  const [entryEditor, setEntryEditor] = useState<{
    x: number;
    y: number;
    direction: "long" | "short";
    entry: string;
    target: string;
    stop: string;
  } | null>(null);
  const entryEditorRef = useRef<HTMLDivElement>(null);
  const [chartLastClose, setChartLastClose] = useState<number | null>(null);
  const [chartData, setChartData] = useState<OhlcBar[]>([]);
  const [copyState, setCopyState] = useState<"idle" | "ok" | "err">("idle");
  const [drawingMode, setDrawingMode] = useState<"none" | "horizontal" | "zone" | "trend_line">("none");
  const [drawingRole, setDrawingRole] = useState<AnnotationRole>("info");
  // Touch / no-hover device: right-click and hover affordances don't exist,
  // so entry guidance and gestures differ.
  const [isTouch, setIsTouch] = useState(false);
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const mq = window.matchMedia("(hover: none) and (pointer: coarse)");
    const update = () => setIsTouch(mq.matches);
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, []);

  const onChartMetrics = useCallback((m: { lastClose: number } | null) => {
    setChartLastClose(m?.lastClose ?? null);
  }, []);
  const onChartData = useCallback((rows: OhlcBar[]) => {
    setChartData(rows);
    onChartDataProp?.(rows);
  }, [onChartDataProp]);

  useEffect(() => {
    setChartLastClose(null);
    setChartData([]);
    setCopyState("idle");
    setEntryEditor(null);
  }, [symbol]);

  const entryMarker = getEntryMarker(symbol);

  const entryVsHeader = useMemo(() => {
    if (!entryMarker) return null;
    const quoteRefClose = getReferenceClose?.(symbol) ?? null;
    const refPrice = quoteRefClose ?? chartLastClose;
    if (refPrice == null) return null;
    const entryPrice = entryMarker.price;
    const d = refPrice - entryPrice;
    const dp = Math.abs(entryPrice) > 1e-9 ? (d / entryPrice) * 100 : 0;
    const source = quoteRefClose != null ? "Prev close" : "Last close";
    return { source, d, dp };
  }, [entryMarker, getReferenceClose, symbol, chartLastClose]);

  async function copyOhlcvToClipboard() {
    if (chartData.length === 0) return;
    const header = "date,open,high,low,close,volume";
    const lines = chartData.map(
      (d) =>
        `${d.date},${d.open},${d.high},${d.low},${d.close},${d.volume}`,
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
    if (!entryMenu) return;
    function onPointerDown(e: PointerEvent) {
      if (entryMenuRef.current?.contains(e.target as Node)) return;
      setEntryMenu(null);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setEntryMenu(null);
    }
    document.addEventListener("pointerdown", onPointerDown, true);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown, true);
      document.removeEventListener("keydown", onKey);
    };
  }, [entryMenu]);

  useEffect(() => {
    if (!entryEditor) return;
    function onPointerDown(e: PointerEvent) {
      if (entryEditorRef.current?.contains(e.target as Node)) return;
      setEntryEditor(null);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setEntryEditor(null);
    }
    document.addEventListener("pointerdown", onPointerDown, true);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown, true);
      document.removeEventListener("keydown", onKey);
    };
  }, [entryEditor]);

  function saveEntryEditor() {
    if (!entryEditor || !entryMarker) return;
    const entryPrice = Number.parseFloat(entryEditor.entry);
    if (!Number.isFinite(entryPrice)) return;
    const tpRaw = entryEditor.target.trim();
    const slRaw = entryEditor.stop.trim();
    const tp = tpRaw === "" ? null : Number.parseFloat(tpRaw);
    const sl = slRaw === "" ? null : Number.parseFloat(slRaw);
    const point: ChartPoint = {
      barIdx: entryMarker.barIdx,
      date: entryMarker.date,
      price: entryPrice,
      open: 0,
      high: 0,
      low: 0,
      close: 0,
    };
    onSetEntryMarker(
      symbol,
      point,
      entryEditor.direction,
      tp != null && Number.isFinite(tp) ? tp : null,
      sl != null && Number.isFinite(sl) ? sl : null,
    );
    setEntryEditor(null);
  }

  if (symbols.length === 0) {
    return (
      <p className="text-sm text-muted-foreground py-8 text-center">
        No symbols to show.
      </p>
    );
  }

  const meta = getTickerMeta(symbol);
  const status = getStatus(symbol);
  const commentExists = hasComment(symbol);

  const footerTail = screeningToolbar
    ? `${symbols.length} stocks in current filter`
    : `${symbols.length} ${symbols.length === 1 ? "symbol" : "symbols"}`;

  const footerNavHint = showChevronSymbolNav
    ? "Use ← → arrow keys or buttons to navigate · "
    : "";

  const entryHint = isTouch
    ? "Long-press chart to add an entry · tap it to edit"
    : "Right-click chart for entry";

  const showTrailingStepNav = showChevronSymbolNav || symbolPicker != null;

  return (
    <div
      className={`flex flex-col ${
        fillContainer ? "h-full min-h-0 gap-0" : "gap-4"
      }`}
    >
      {/* Header toolbar. Skipped in fillContainer mode (caveman) — the wrapping
          card already provides the symbol header + range chips + quick-action
          bar, and the chart needs every pixel of vertical space inside the
          Tinder card. Skipping also avoids overlap with the absolute-positioned
          mobile segment progress bar that sits at top:0 of the chart. */}
      {!fillContainer && (
      <div className="flex items-center gap-3">
        {showChevronSymbolNav ? (
          <button
            type="button"
            onClick={() => onSelect(symbols[Math.max(0, idx - 1)])}
            disabled={idx === 0}
            className="p-1.5 rounded-md border border-border hover:bg-muted disabled:opacity-30 transition-colors"
            title="Previous (←)"
          >
            <ChevronLeft className="w-4 h-4" />
          </button>
        ) : null}

        {showSymbolHeadline ? (
          <>
            <span className="font-mono font-bold text-lg">{symbol}</span>
            {(meta.sector || meta.industry) && (
              <span
                className="text-xs text-muted-foreground max-w-[260px] truncate"
                title={[meta.sector, meta.industry].filter(Boolean).join(" · ")}
              >
                {[meta.sector, meta.industry].filter(Boolean).join(" · ")}
              </span>
            )}
            <span className="text-sm text-muted-foreground">
              {idx + 1} / {symbols.length}
            </span>
          </>
        ) : null}

        {screeningToolbar && (
          <>
            {dismissed.has(symbol) ? (
              <button
                type="button"
                onClick={() => onRestore(symbol)}
                title="Restore"
                className="flex items-center gap-1.5 text-xs px-2 py-1 rounded border border-border text-emerald-500 hover:bg-muted transition-colors"
              >
                <RotateCcw className="w-3.5 h-3.5" /> Restore
              </button>
            ) : (
              <button
                type="button"
                onClick={() => onDismiss(symbol)}
                title="Dismiss"
                className="flex items-center gap-1.5 text-xs px-2 py-1 rounded border border-border text-muted-foreground hover:text-rose-500 hover:border-rose-400 transition-colors"
              >
                <Trash2 className="w-3.5 h-3.5" /> Dismiss
              </button>
            )}

            <select
              value={status}
              onChange={(e) =>
                onSetStatus(symbol, e.target.value as TickerChartNoteStatus)
              }
              className="px-2 py-1 text-xs rounded border border-input bg-background focus:outline-none focus:ring-1 focus:ring-ring"
              title="Status"
            >
              <option value="active">Active</option>
              <option value="dismissed">Dismissed</option>
              <option value="watchlist">Watchlist</option>
              <option value="pipeline">Pipeline</option>
            </select>

            <button
              type="button"
              onClick={() => onEditComment(symbol)}
              title={commentExists ? "Edit note" : "Add note"}
              className={`flex items-center gap-1.5 text-xs px-2 py-1 rounded border border-border transition-colors ${commentExists ? "text-sky-500 hover:bg-muted" : "text-muted-foreground hover:text-sky-500 hover:border-sky-400"}`}
            >
              <MessageSquare className="w-3.5 h-3.5" />{" "}
              {commentExists ? "Edit note" : "Add note"}
            </button>
          </>
        )}

        {entryVsHeader && entryMarker && (
          <div
            className="flex flex-col items-end gap-0.5 text-right shrink-0 min-w-0"
            title={`Entry $${entryMarker.price.toFixed(2)} · ${entryVsHeader.source} vs entry`}
          >
            <span className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
              vs entry
            </span>
            <span
              className={`text-xs font-semibold tabular-nums whitespace-nowrap ${entryVsHeader.d >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-rose-500"}`}
            >
              {entryVsHeader.source}: {entryVsHeader.d >= 0 ? "+" : ""}
              {entryVsHeader.d.toFixed(2)} ({entryVsHeader.d >= 0 ? "+" : ""}
              {entryVsHeader.dp.toFixed(2)}%)
            </span>
          </div>
        )}

        {screeningToolbar && (
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
          {copyState === "ok"
            ? "Copied"
            : copyState === "err"
              ? "Copy failed"
              : "Copy OHLCV"}
        </button>
        )}

        {showTrailingStepNav ? (
          <div className="ml-auto flex items-center gap-2">
            {symbolPicker}
            {showChevronSymbolNav ? (
              <button
                type="button"
                onClick={() =>
                  onSelect(symbols[Math.min(symbols.length - 1, idx + 1)])
                }
                disabled={idx === symbols.length - 1}
                className="p-1.5 rounded-md border border-border hover:bg-muted disabled:opacity-30 transition-colors"
                title="Next (→)"
              >
                <ChevronRight className="w-4 h-4" />
              </button>
            ) : null}
          </div>
        ) : null}
      </div>
      )}

      {/* Drawing toolbar */}
      {onAnnotationAdd && (
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-[11px] text-muted-foreground">Draw:</span>
          {([
            { mode: "none", icon: <MousePointer2 className="w-3.5 h-3.5" />, label: "Select" },
            { mode: "horizontal", icon: <Minus className="w-3.5 h-3.5" />, label: "Horizontal" },
            { mode: "zone", icon: <SquareDashed className="w-3.5 h-3.5" />, label: "Zone" },
            { mode: "trend_line", icon: <TrendingUp className="w-3.5 h-3.5" />, label: "Trend Line" },
          ] as const).map(({ mode, icon, label }) => (
            <button
              key={mode}
              type="button"
              title={label}
              onClick={() => setDrawingMode(mode)}
              className={`flex items-center gap-1 text-[11px] px-2 py-1 rounded border transition-colors ${
                drawingMode === mode
                  ? "border-foreground bg-muted text-foreground"
                  : "border-border text-muted-foreground hover:text-foreground hover:border-foreground/40"
              }`}
            >
              {icon}
              {label}
            </button>
          ))}
          <select
            value={drawingRole}
            onChange={(e) => setDrawingRole(e.target.value as AnnotationRole)}
            className="px-2 py-1 text-[11px] rounded border border-input bg-background focus:outline-none focus:ring-1 focus:ring-ring"
            title="Annotation role"
          >
            <option value="info">Info</option>
            <option value="support">Support</option>
            <option value="resistance">Resistance</option>
            <option value="entry">Entry</option>
            <option value="stop">Stop</option>
            <option value="target">Target</option>
          </select>
          {drawingMode !== "none" && (
            <span className="text-[10px] text-muted-foreground italic">
              {drawingMode === "horizontal" ? "Click chart to place line" : "Click two points on chart"}
            </span>
          )}
        </div>
      )}

      <div
        className={
          showChartFrame
            ? "relative border border-border rounded-lg p-4 bg-background"
            : fillContainer
              ? "relative flex-1 min-h-0"
              : "relative"
        }
        title="Drag left/right to pan time · Drag up/down to pan price · Double-click to reset price pan · Right-click for entry options"
        data-swipe-ignore
        onContextMenu={(e) => {
          e.preventDefault();
          setEntryMenu({
            x: e.clientX,
            y: e.clientY,
            pointSnapshot: activePointRef.current,
          });
        }}
      >
        <CandlestickSvg
          key={`${symbol}-${interval ?? "1day"}`}
          symbol={symbol}
          onPointChange={setActivePoint}
          entryMarker={entryMarker}
          tradeMarkers={tradeMarkers}
          onChartMetrics={onChartMetrics}
          onChartData={onChartData}
          onAutoEntry={(point) => onSetEntryMarker(symbol, point)}
          onEntryEdit={
            entryMarker
              ? (cx, cy) =>
                  setEntryEditor({
                    x: cx,
                    y: cy,
                    direction: entryMarker.direction ?? "long",
                    entry: String(entryMarker.price),
                    target:
                      entryMarker.take_profit != null
                        ? String(entryMarker.take_profit)
                        : "",
                    stop:
                      entryMarker.stop_loss != null
                        ? String(entryMarker.stop_loss)
                        : "",
                  })
              : undefined
          }
          annotations={annotations}
          drawingMode={drawingMode}
          drawingRole={drawingRole}
          onAnnotationAdd={onAnnotationAdd}
          onAnnotationDelete={onAnnotationDelete}
          dateRange={dateRange}
          interval={interval}
          fillContainer={fillContainer}
        />
      </div>

      {entryMenu && (
        <div
          ref={entryMenuRef}
          role="menu"
          className="fixed z-[100] min-w-[200px] rounded-md border border-border bg-popover py-1 text-popover-foreground shadow-md"
          style={{
            left: Math.min(entryMenu.x, window.innerWidth - 210),
            top: Math.min(entryMenu.y, window.innerHeight - 140),
          }}
          onPointerDown={(e) => e.stopPropagation()}
        >
          <div className="px-2 py-1.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
            Entry
          </div>
          {entryMarker && (
            <div
              className="px-2 pb-1.5 text-[11px] text-muted-foreground border-b border-border truncate"
              title={`${entryMarker.date} @ $${entryMarker.price.toFixed(2)}`}
            >
              Current: {entryMarker.date} @ ${entryMarker.price.toFixed(2)}
            </div>
          )}
          {!entryMenu.pointSnapshot && (
            <div className="px-2 pb-1 text-[11px] text-muted-foreground border-b border-border">
              Move crosshair on chart, then right-click to capture an entry
              point.
            </div>
          )}
          <button
            type="button"
            role="menuitem"
            className="flex w-full items-center px-3 py-2 text-left text-sm hover:bg-muted disabled:opacity-40 disabled:pointer-events-none"
            disabled={!entryMenu.pointSnapshot}
            onClick={() => {
              if (entryMenu.pointSnapshot)
                onSetEntryMarker(symbol, entryMenu.pointSnapshot);
              setEntryMenu(null);
            }}
          >
            Set entry at crosshair
          </button>
          <button
            type="button"
            role="menuitem"
            className="flex w-full items-center px-3 py-2 text-left text-sm text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-40 disabled:pointer-events-none"
            disabled={!entryMarker}
            onClick={() => {
              onClearEntryMarker(symbol);
              setEntryMenu(null);
            }}
          >
            Clear entry
          </button>
        </div>
      )}

      {entryEditor && (
        <div
          ref={entryEditorRef}
          className="fixed z-[100] w-[220px] rounded-md border border-border bg-popover p-3 text-popover-foreground shadow-md"
          style={{
            left: Math.min(entryEditor.x, window.innerWidth - 232),
            top: Math.min(entryEditor.y, window.innerHeight - 260),
          }}
          onPointerDown={(e) => e.stopPropagation()}
        >
          <div className="mb-2 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
            Edit position
          </div>
          <div className="space-y-2">
            <label className="flex items-center justify-between gap-2 text-xs">
              <span className="text-muted-foreground">Direction</span>
              <select
                className="h-7 w-[120px] rounded border border-border bg-background px-1.5 text-xs"
                value={entryEditor.direction}
                onChange={(e) =>
                  setEntryEditor((p) =>
                    p ? { ...p, direction: e.target.value as "long" | "short" } : p,
                  )
                }
              >
                <option value="long">Long</option>
                <option value="short">Short</option>
              </select>
            </label>
            <label className="flex items-center justify-between gap-2 text-xs">
              <span className="text-muted-foreground">Entry</span>
              <input
                type="number"
                step="any"
                inputMode="decimal"
                className="h-7 w-[120px] rounded border border-border bg-background px-1.5 text-xs"
                value={entryEditor.entry}
                onChange={(e) =>
                  setEntryEditor((p) => (p ? { ...p, entry: e.target.value } : p))
                }
              />
            </label>
            <label className="flex items-center justify-between gap-2 text-xs">
              <span className="text-muted-foreground">Target</span>
              <input
                type="number"
                step="any"
                inputMode="decimal"
                placeholder="—"
                className="h-7 w-[120px] rounded border border-border bg-background px-1.5 text-xs"
                value={entryEditor.target}
                onChange={(e) =>
                  setEntryEditor((p) => (p ? { ...p, target: e.target.value } : p))
                }
              />
            </label>
            <label className="flex items-center justify-between gap-2 text-xs">
              <span className="text-muted-foreground">Stop</span>
              <input
                type="number"
                step="any"
                inputMode="decimal"
                placeholder="—"
                className="h-7 w-[120px] rounded border border-border bg-background px-1.5 text-xs"
                value={entryEditor.stop}
                onChange={(e) =>
                  setEntryEditor((p) => (p ? { ...p, stop: e.target.value } : p))
                }
              />
            </label>
          </div>
          <div className="mt-3 flex items-center justify-between gap-2">
            <button
              type="button"
              className="text-xs text-muted-foreground hover:text-destructive"
              onClick={() => {
                onClearEntryMarker(symbol);
                setEntryEditor(null);
              }}
            >
              Clear
            </button>
            <div className="flex items-center gap-2">
              <button
                type="button"
                className="rounded border border-border px-2 py-1 text-xs hover:bg-muted"
                onClick={() => setEntryEditor(null)}
              >
                Cancel
              </button>
              <button
                type="button"
                className="rounded bg-primary px-2 py-1 text-xs font-medium text-primary-foreground hover:opacity-90"
                onClick={saveEntryEditor}
              >
                Save
              </button>
            </div>
          </div>
        </div>
      )}

      <p className="text-xs text-muted-foreground text-center">
        {footerNavHint}{entryHint} · {footerTail}
      </p>
    </div>
  );
}
