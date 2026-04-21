"use client";

import {
  useState,
  useEffect,
  useRef,
  useCallback,
  useMemo,
  type MouseEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { Loader2 } from "lucide-react";
import { fmpGetOhlc } from "@/app/actions/fmp";
import { readChartViewCache, putChartViewCache } from "@/lib/chart-view-cache";
import { subtractCalendarDays } from "@/lib/fmp-date-utils";
import type { ChartPoint, OhlcBar, PivotMarker, ChartAnnotation } from "./types";
import { resolvePivotBarIndex, ANNOTATION_COLORS } from "./types";

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

/** Default bars shown after load / symbol change. */
const CHART_DEFAULT_VIEWPORT_BARS = 120;
/** Hard cap on zoom-out width (bars). */
const CHART_MAX_VIEWPORT_BARS = 2500;
/** Zoom-in limit (bars). */
const CHART_MIN_VIEWPORT_BARS = 12;
/** Wheel zoom: multiply viewport width per step (out = widen). */
const CHART_ZOOM_WHEEL_FACTOR = 1.04;
/** When panning past the oldest loaded bar, fetch up to this many calendar days further back (FMP daily). */
const CHART_FETCH_PAST_DAYS = 400;
/** Stop requesting older history beyond this many years before today. */
const CHART_HISTORY_BACK_YEARS = 12;

function ohlcDateKey(date: string): string {
  return date.slice(0, 10);
}

function mergeOhlcSeries(older: OhlcBar[], current: OhlcBar[]): OhlcBar[] {
  const m = new Map<string, OhlcBar>();
  for (const row of older) m.set(ohlcDateKey(row.date), row);
  for (const row of current) m.set(ohlcDateKey(row.date), row);
  return [...m.values()].sort((a, b) => a.date.localeCompare(b.date));
}

/** Inclusive prefix sums of close — one O(n) pass when `data` changes. */
function buildClosePrefixSum(rows: OhlcBar[]): number[] {
  const n = rows.length;
  if (n === 0) return [];
  const pref = new Array<number>(n);
  let s = 0;
  for (let i = 0; i < n; i++) {
    s += rows[i]!.close;
    pref[i] = s;
  }
  return pref;
}

/** O(1) SMA(close) at global bar index `i` from prefix built by buildClosePrefixSum. */
function smaCloseFromPrefix(
  prefix: number[],
  period: number,
  i: number,
): number | null {
  if (prefix.length === 0 || i < period - 1) return null;
  const hi = prefix[i]!;
  const lo = i >= period ? prefix[i - period]! : 0;
  return (hi - lo) / period;
}

function smaPathD(
  closePrefix: number[],
  sliceStart: number,
  n: number,
  period: number,
  xOf: (localIdx: number) => number,
  toY: (p: number) => number,
): string {
  if (n < 2) return "";
  let d = "";
  let started = false;
  for (let li = 1; li < n; li++) {
    const g0 = sliceStart + li - 1;
    const g1 = sliceStart + li;
    const v0 = smaCloseFromPrefix(closePrefix, period, g0);
    const v1 = smaCloseFromPrefix(closePrefix, period, g1);
    if (v0 == null || v1 == null) {
      started = false;
      continue;
    }
    const x0 = xOf(li - 1);
    const y0 = toY(v0);
    const x1 = xOf(li);
    const y1 = toY(v1);
    if (!started) {
      d += `M${x0},${y0}L${x1},${y1}`;
      started = true;
    } else {
      d += `L${x1},${y1}`;
    }
  }
  return d;
}

export function CandlestickSvg({
  symbol,
  onPointChange,
  pivotMarker,
  onChartMetrics,
  onChartData,
  onAutoPivot,
  annotations = [],
  drawingMode = "none",
  drawingRole = "info",
  onAnnotationAdd,
  onAnnotationDelete,
  dateRange,
}: {
  symbol: string;
  onPointChange?: (point: ChartPoint | null) => void;
  pivotMarker?: PivotMarker | null;
  onChartMetrics?: (m: { lastClose: number } | null) => void;
  onChartData?: (rows: OhlcBar[]) => void;
  onAutoPivot?: (point: ChartPoint) => void;
  annotations?: ChartAnnotation[];
  drawingMode?: "none" | "horizontal" | "zone" | "trend_line";
  drawingRole?: import("./types").AnnotationRole;
  onAnnotationAdd?: (ann: ChartAnnotation) => void;
  onAnnotationDelete?: (id: string) => void;
  dateRange?: { from: string; to: string };
}) {
  const [data, setData] = useState<OhlcBar[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [crosshair, setCrosshair] = useState<Crosshair | null>(null);
  const [selBox, setSelBox] = useState<SelectionBox | null>(null);
  const [viewStart, setViewStart] = useState(0);
  const [viewportBars, setViewportBars] = useState(CHART_DEFAULT_VIEWPORT_BARS);
  const [isPanning, setIsPanning] = useState(false);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [priceOffset, setPriceOffset] = useState(0);
  const svgRef = useRef<SVGSVGElement>(null);
  const dataRef = useRef<OhlcBar[]>([]);
  const symbolRef = useRef(symbol);
  const viewStartRef = useRef(0);
  const sliceStartRef = useRef(0);
  const visibleLenRef = useRef(CHART_DEFAULT_VIEWPORT_BARS);
  const viewportBarsRef = useRef(CHART_DEFAULT_VIEWPORT_BARS);
  const loadingOlderRef = useRef(false);
  const pastExhaustedRef = useRef(false);
  const zoomAnchorRef = useRef<{ fraction: number } | null>(null);
  const lastPointKeyRef = useRef<string | null>(null);
  const panRef = useRef<
    | { mode: "idle" }
    | {
        mode: "candidate";
        pointerId: number;
        startClientX: number;
        startClientY: number;
        startViewStart: number;
        startPriceOffset: number;
      }
    | {
        mode: "panning";
        pointerId: number;
        originClientX: number;
        originViewStart: number;
      }
    | {
        mode: "price_panning";
        pointerId: number;
        originClientY: number;
        startPriceOffset: number;
      }
  >({ mode: "idle" });
  const suppressClickAfterPan = useRef(false);
  const [drawingFirstPoint, setDrawingFirstPoint] = useState<{ price: number; date: string } | null>(null);

  useEffect(() => {
    setDrawingFirstPoint(null);
  }, [drawingMode]);

  useEffect(() => {
    symbolRef.current = symbol;
    setPriceOffset(0);
  }, [symbol]);

  useEffect(() => {
    dataRef.current = data;
  }, [data]);

  useEffect(() => {
    viewportBarsRef.current = viewportBars;
  }, [viewportBars]);

  const cacheWriteTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    setData([]);
    setViewStart(0);
    setViewportBars(CHART_DEFAULT_VIEWPORT_BARS);
    setPriceOffset(0);
    pastExhaustedRef.current = false;
    const sym = symbol;

    void (async () => {
      try {
        // Read cached view and OHLC data in parallel.
        const [ohlcResult, cached] = await Promise.all([
          fmpGetOhlc(sym, undefined, dateRange),
          readChartViewCache(),
        ]);
        if (sym !== symbolRef.current) return; // navigated away

        if (!ohlcResult.ok) {
          setError("Failed to load chart data");
          return;
        }
        const rows = ohlcResult.data;
        setData(rows);
        const n = rows.length;
        const defaultLen = Math.min(CHART_DEFAULT_VIEWPORT_BARS, n);

        if (cached) {
          setViewportBars(cached.viewportBars);
          setPriceOffset(cached.priceOffset);
          // Scroll position is not cached globally — always show most recent bars.
          const restoredLen = Math.min(cached.viewportBars, n);
          setViewStart(restoredLen >= n ? 0 : n - restoredLen);
        } else {
          setViewportBars(defaultLen);
          setViewStart(defaultLen >= n ? 0 : n - defaultLen);
        }
      } catch {
        if (sym === symbolRef.current) setError("Failed to load chart data");
      } finally {
        if (sym === symbolRef.current) setLoading(false);
      }
    })();
  }, [symbol, dateRange?.from, dateRange?.to]);

  // Debounced cache write — fires 600 ms after the view settles.
  // Uses refs inside the timeout so values are always current when it fires.
  useEffect(() => {
    if (cacheWriteTimerRef.current) clearTimeout(cacheWriteTimerRef.current);
    cacheWriteTimerRef.current = setTimeout(() => {
      const vb = viewportBarsRef.current;
      putChartViewCache({ viewportBars: vb, priceOffset });
    }, 600);
    return () => {
      if (cacheWriteTimerRef.current) clearTimeout(cacheWriteTimerRef.current);
    };
  }, [symbol, viewStart, viewportBars, priceOffset]);

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

  useEffect(() => {
    console.log("[Chart] annotations prop changed:", annotations, "data bars:", data.length);
  }, [annotations, data.length]);

  // Allow viewStart to extend one bar past the last bar (future panning).
  // Constraint: at least 1 data bar must remain in viewport → viewStart ≤ data.length - 1.
  const sliceStart = useMemo(() => {
    if (data.length === 0) return 0;
    return Math.min(Math.max(0, viewStart), data.length - 1);
  }, [data.length, viewStart]);

  const displaySlice = useMemo(
    () => data.slice(sliceStart, sliceStart + viewportBars),
    [data, sliceStart, viewportBars],
  );

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

  const { priceMin: priceMinData, priceMax: priceMaxData, volMax } = useMemo(() => {
    if (displaySlice.length === 0) {
      return { priceMin: 0, priceMax: 1, volMax: 1 };
    }
    let lo = displaySlice[0]!.low;
    let hi = displaySlice[0]!.high;
    let vmax = displaySlice[0]!.volume;
    for (let i = 1; i < displaySlice.length; i++) {
      const d = displaySlice[i]!;
      if (d.low < lo) lo = d.low;
      if (d.high > hi) hi = d.high;
      if (d.volume > vmax) vmax = d.volume;
    }
    return {
      priceMin: lo * 0.99,
      priceMax: hi * 1.01,
      volMax: vmax,
    };
  }, [displaySlice]);

  // Apply vertical pan offset. Clamped to ±0.99 so at least one data bar stays visible.
  const priceDataRange = priceMaxData - priceMinData;
  const clampedPriceOffset = Math.min(0.99, Math.max(-0.99, priceOffset));
  const priceShift = clampedPriceOffset * priceDataRange;
  const priceMin = priceMinData - priceShift;
  const priceMax = priceMaxData - priceShift;

  const n = displaySlice.length;
  // barStep always spans the full viewport width so future/empty slots are proportional.
  const barStep = viewportBars > 1 ? chartW / viewportBars : chartW;
  const barW = Math.max(1, Math.min(12, chartW / Math.max(viewportBars, 1) - 1));
  const canPanTimescale = data.length > 0;

  viewStartRef.current = viewStart;
  sliceStartRef.current = sliceStart;
  visibleLenRef.current = viewportBars;

  const toY = useCallback((p: number) => {
    return PAD_T + chartH - ((p - priceMin) / (priceMax - priceMin)) * chartH;
  }, [priceMin, priceMax, chartH]);

  const toVolY = useCallback((v: number) => {
    const volH = H_VOL - 8;
    return H_PRICE + 16 + volH - (v / volMax) * volH;
  }, [volMax]);

  function xOf(localIdx: number) {
    return PAD_L + localIdx * barStep + barStep / 2;
  }

  const closePrefix = useMemo(() => buildClosePrefixSum(data), [data]);

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

  // X-axis ticks (local indices into displaySlice)
  const xTickIndices = useMemo(() => {
    if (n === 0) return [];
    const step = Math.ceil(n / 8);
    const idx: number[] = [];
    for (let i = 0; i < n; i += step) idx.push(i);
    return idx;
  }, [n]);

  const toPrice = useCallback((svgY: number): number => {
    return priceMin + (1 - (svgY - PAD_T) / chartH) * (priceMax - priceMin);
  }, [priceMin, chartH, priceMax, PAD_T]);

  const smaPathDefs = useMemo(() => {
    const xf = (localIdx: number) => PAD_L + localIdx * barStep + barStep / 2;
    return (
      [
        { period: 10, color: "#10b981", key: "10" },
        { period: 21, color: "#f97316", key: "21" },
        { period: 50, color: "#ef4444", key: "50" },
        { period: 200, color: "#6366f1", key: "200" },
      ] as const
    ).map(({ period, color, key }) => ({
      key,
      color,
      d: smaPathD(closePrefix, sliceStart, n, period, xf, toY),
    }));
  }, [closePrefix, sliceStart, n, barStep, toY]);

  const fetchOlderChunk = useCallback(async (): Promise<boolean> => {
    if (loadingOlderRef.current || pastExhaustedRef.current) return false;
    const current = dataRef.current;
    const sym = symbolRef.current;
    if (current.length === 0) return false;
    const oldest = ohlcDateKey(current[0].date);
    const today = new Date().toISOString().slice(0, 10);
    let fromYmd = subtractCalendarDays(oldest, CHART_FETCH_PAST_DAYS);
    const cap = subtractCalendarDays(today, 365 * CHART_HISTORY_BACK_YEARS);
    if (fromYmd < cap) fromYmd = cap;
    if (fromYmd >= oldest) {
      pastExhaustedRef.current = true;
      return false;
    }
    loadingOlderRef.current = true;
    setLoadingOlder(true);
    try {
      const res = await fmpGetOhlc(sym, "1day", { from: fromYmd, to: oldest });
      if (!res.ok || sym !== symbolRef.current) return false;
      const extra = res.data;
      if (extra.length === 0) {
        pastExhaustedRef.current = true;
        return false;
      }
      const merged = mergeOhlcSeries(extra, current);
      const before = current.length;
      if (merged.length === before) {
        pastExhaustedRef.current = true;
        return false;
      }
      const oldFirstKey = ohlcDateKey(current[0].date);
      let splitAt = merged.findIndex((b) => ohlcDateKey(b.date) === oldFirstKey);
      if (splitAt < 0) {
        splitAt = merged.findIndex((b) => ohlcDateKey(b.date) >= oldFirstKey);
      }
      if (splitAt <= 0) {
        pastExhaustedRef.current = true;
        return false;
      }
      const prepended = splitAt;
      setData(merged);
      setViewStart((vs) => {
        const n2 = merged.length;
        const len2 = Math.min(viewportBarsRef.current, n2);
        const maxS2 = Math.max(0, n2 - len2);
        return Math.min(Math.max(0, vs + prepended), maxS2);
      });
      return true;
    } finally {
      if (sym === symbolRef.current) {
        loadingOlderRef.current = false;
        setLoadingOlder(false);
      }
    }
  }, []);

  const ensureOlderHistoryForViewport = useCallback(
    async (targetBars: number) => {
      let iter = 0;
      while (
        dataRef.current.length < targetBars &&
        !pastExhaustedRef.current &&
        iter++ < 40
      ) {
        const grew = await fetchOlderChunk();
        if (!grew) break;
      }
    },
    [fetchOlderChunk],
  );

  const zoomWheelGenRef = useRef(0);

  useEffect(() => {
    if (loading || error || data.length === 0) return;
    const svg = svgRef.current;
    if (!svg) return;

    const onWheel = (e: WheelEvent) => {
      const rect = svg.getBoundingClientRect();
      if (rect.width <= 0) return;

      const dataLen = dataRef.current.length;
      if (dataLen === 0) return;

      const sliceStartNow = sliceStartRef.current;
      const visibleLenNow = visibleLenRef.current;
      if (visibleLenNow === 0) return;

      const scaleX = W / rect.width;
      const svgX = (e.clientX - rect.left) * scaleX;
      if (svgX < PAD_L || svgX > W - PAD_R) return;

      e.preventDefault();

      const barStepNow =
        visibleLenNow > 1 ? chartW / visibleLenNow : chartW;
      const rawLocal = (svgX - PAD_L - barStepNow / 2) / barStepNow;
      const localIdx = Math.max(
        0,
        Math.min(visibleLenNow - 1, Math.round(rawLocal)),
      );
      const anchorIdx = Math.min(
        dataLen - 1,
        Math.max(0, sliceStartNow + localIdx),
      );
      const anchorBar = dataRef.current[anchorIdx];
      const dateKey = anchorBar ? ohlcDateKey(anchorBar.date) : "";
      const f =
        visibleLenNow > 1
          ? Math.max(0, Math.min(1, (svgX - PAD_L) / chartW))
          : 0.5;

      const zoomOut = e.deltaY > 0;
      const curV = viewportBarsRef.current;
      const nextV = Math.round(
        curV * (zoomOut ? CHART_ZOOM_WHEEL_FACTOR : 1 / CHART_ZOOM_WHEEL_FACTOR),
      );
      const clampedV = Math.max(
        CHART_MIN_VIEWPORT_BARS,
        Math.min(CHART_MAX_VIEWPORT_BARS, nextV),
      );
      if (clampedV === curV) return;

      const maxS = Math.max(0, dataLen - 1);
      let nextStart = Math.round(
        anchorIdx - f * Math.max(Math.min(clampedV, dataLen) - 1, 0),
      );
      nextStart = Math.min(Math.max(0, nextStart), maxS);

      setViewportBars(clampedV);
      setViewStart(nextStart);

      if (clampedV > dataLen) {
        const targetViewport = clampedV;
        const anchorDateKey = dateKey;
        const anchorIdxFallback = anchorIdx;
        zoomAnchorRef.current = { fraction: f };
        const gen = ++zoomWheelGenRef.current;
        void (async () => {
          await ensureOlderHistoryForViewport(targetViewport);
          if (gen !== zoomWheelGenRef.current) return;
          const z = zoomAnchorRef.current;
          zoomAnchorRef.current = null;
          if (!z) return;
          const rows = dataRef.current;
          const dl = rows.length;
          if (dl === 0) return;
          let idx = rows.findIndex((b) => ohlcDateKey(b.date) === anchorDateKey);
          if (idx < 0) idx = Math.min(anchorIdxFallback, dl - 1);
          let effectiveViewport = targetViewport;
          if (targetViewport > dl && pastExhaustedRef.current) {
            effectiveViewport = dl;
            setViewportBars(dl);
          }
          const V = Math.min(effectiveViewport, dl);
          const maxS2 = Math.max(0, dl - 1);
          let ns = Math.round(idx - z.fraction * Math.max(V - 1, 0));
          ns = Math.min(Math.max(0, ns), maxS2);
          setViewStart(ns);
        })();
      }
    };

    svg.addEventListener("wheel", onWheel, { passive: false });
    return () => svg.removeEventListener("wheel", onWheel);
  }, [
    loading,
    error,
    data.length,
    chartW,
    ensureOlderHistoryForViewport,
  ]);

  function svgCoordsFromEvent(
    e: MouseEvent<SVGSVGElement> | ReactPointerEvent<SVGSVGElement>,
  ) {
    const svg = svgRef.current;
    if (!svg || n === 0) return null;
    const rect = svg.getBoundingClientRect();
    const scaleX = W / rect.width;
    const scaleY = H / rect.height;
    const svgX = (e.clientX - rect.left) * scaleX;
    const svgY = (e.clientY - rect.top) * scaleY;
    const rawLocal = (svgX - PAD_L - barStep / 2) / barStep;
    const localIdx = Math.max(0, Math.min(n - 1, Math.round(rawLocal)));
    const globalIdx = Math.min(
      data.length - 1,
      Math.max(0, sliceStart + localIdx),
    );
    return { barIdx: globalIdx, svgX, svgY };
  }

  function handlePointerDown(e: ReactPointerEvent<SVGSVGElement>) {
    e.preventDefault();
    if (e.button !== 0) return;
    if (e.shiftKey) return;
    if (selBox && !selBox.locked) return;
    if (drawingMode !== "none") return;
    if (!canPanTimescale) return;
    panRef.current = {
      mode: "candidate",
      pointerId: e.pointerId,
      startClientX: e.clientX,
      startClientY: e.clientY,
      startViewStart: sliceStart,
      startPriceOffset: priceOffset,
    };
  }

  function handlePointerMove(e: ReactPointerEvent<SVGSVGElement>) {
    const p = panRef.current;
    if (p.mode === "candidate" && (e.buttons & 1) === 1) {
      const dx = e.clientX - p.startClientX;
      const dy = e.clientY - p.startClientY;
      if (Math.abs(dx) > 6 && Math.abs(dx) > Math.abs(dy) * 0.65) {
        try { e.currentTarget.setPointerCapture(e.pointerId); } catch { /* already captured */ }
        panRef.current = {
          mode: "panning",
          pointerId: e.pointerId,
          originClientX: p.startClientX,
          originViewStart: p.startViewStart,
        };
        setIsPanning(true);
      } else if (Math.abs(dy) > 6 && Math.abs(dy) > Math.abs(dx) * 0.65) {
        try { e.currentTarget.setPointerCapture(e.pointerId); } catch { /* already captured */ }
        panRef.current = {
          mode: "price_panning",
          pointerId: e.pointerId,
          originClientY: p.startClientY,
          startPriceOffset: p.startPriceOffset,
        };
        setIsPanning(true);
      }
    }

    if (panRef.current.mode === "panning" && (e.buttons & 1) === 1) {
      const svg = svgRef.current;
      const rect = svg?.getBoundingClientRect();
      const scaleX = rect && rect.width > 0 ? W / rect.width : 1;
      const pan = panRef.current;
      const dxSvg = (e.clientX - pan.originClientX) * scaleX;
      const deltaBars = Math.round(dxSvg / barStep);
      // Right bound: keep at least one bar in viewport (last bar = data.length - 1).
      const maxS = Math.max(0, data.length - 1);
      const rawNext = pan.originViewStart - deltaBars;
      const next = Math.min(Math.max(0, rawNext), maxS);
      setViewStart(next);
      if (rawNext < 0 && sliceStart === 0 && !loadingOlderRef.current && !pastExhaustedRef.current) {
        void fetchOlderChunk();
      }
      return;
    }

    if (panRef.current.mode === "price_panning" && (e.buttons & 1) === 1) {
      const svg = svgRef.current;
      const rect = svg?.getBoundingClientRect();
      if (!rect || rect.height === 0) return;
      const pan = panRef.current;
      const scaleY = H / rect.height;
      const dyScreen = e.clientY - pan.originClientY;
      // Dragging up (negative dy) shifts view upward → see higher prices → positive offset.
      const delta = -(dyScreen * scaleY) / chartH;
      setPriceOffset(Math.min(0.99, Math.max(-0.99, pan.startPriceOffset + delta)));
      return;
    }

    const me = e as unknown as MouseEvent<SVGSVGElement>;
    const coords = svgCoordsFromEvent(me);
    if (!coords) return;
    setCrosshair((prev) => ({
      barIdx: coords.barIdx,
      svgY: coords.svgY,
      pinned: prev?.pinned ?? false,
    }));
    setSelBox((prev) =>
      prev && !prev.locked
        ? { ...prev, endX: coords.svgX, endY: coords.svgY }
        : prev,
    );
  }

  function handlePointerUp(e: ReactPointerEvent<SVGSVGElement>) {
    const p = panRef.current;
    if ((p.mode === "panning" || p.mode === "price_panning") && p.pointerId === e.pointerId) {
      try { e.currentTarget.releasePointerCapture(e.pointerId); } catch { /* not captured */ }
      setIsPanning(false);
      suppressClickAfterPan.current = true;
    }
    panRef.current = { mode: "idle" };
  }

  function handleClick(e: MouseEvent<SVGSVGElement>) {
    if (suppressClickAfterPan.current) {
      suppressClickAfterPan.current = false;
      return;
    }
    const coords = svgCoordsFromEvent(e);
    if (!coords) return;

    if (drawingMode !== "none" && onAnnotationAdd) {
      const price = toPrice(Math.max(PAD_T, Math.min(H_PRICE - PAD_B, coords.svgY)));
      const bar = data[coords.barIdx];
      if (!bar) return;

      if (drawingMode === "horizontal") {
        onAnnotationAdd({ id: crypto.randomUUID(), type: "horizontal", price, role: drawingRole, origin: "user" });
      } else if (drawingMode === "zone") {
        if (!drawingFirstPoint) {
          setDrawingFirstPoint({ price, date: bar.date });
        } else {
          onAnnotationAdd({ id: crypto.randomUUID(), type: "zone", priceTop: Math.max(price, drawingFirstPoint.price), priceBottom: Math.min(price, drawingFirstPoint.price), role: drawingRole, origin: "user" });
          setDrawingFirstPoint(null);
        }
      } else if (drawingMode === "trend_line") {
        if (!drawingFirstPoint) {
          setDrawingFirstPoint({ price, date: bar.date });
        } else {
          onAnnotationAdd({ id: crypto.randomUUID(), type: "trend_line", fromDate: drawingFirstPoint.date, fromPrice: drawingFirstPoint.price, toDate: bar.date, toPrice: price, role: drawingRole, origin: "user" });
          setDrawingFirstPoint(null);
        }
      }
      return;
    }

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

  function handleDoubleClick(e: MouseEvent<SVGSVGElement>) {
    const coords = svgCoordsFromEvent(e);
    if (!coords) return;
    // Double-click resets vertical price pan if active, otherwise pins crosshair.
    if (priceOffset !== 0) {
      setPriceOffset(0);
      return;
    }
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
      {loadingOlder ? (
        <div className="pointer-events-none absolute left-2 top-2 z-[5] flex items-center gap-1.5 rounded-md border border-border bg-background/90 px-2 py-1 text-xs text-muted-foreground">
          <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
          Loading older bars…
        </div>
      ) : null}
      <svg
        ref={svgRef}
        viewBox={`0 0 ${W} ${H}`}
        width="100%"
        className={`block select-none ${
          drawingMode !== "none"
            ? drawingFirstPoint ? "cursor-cell" : "cursor-crosshair"
            : isPanning
              ? "cursor-grabbing"
              : canPanTimescale
                ? "cursor-grab"
                : "cursor-default"
        }`}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={handlePointerUp}
        onClick={handleClick}
        onDoubleClick={handleDoubleClick}
        onMouseLeave={() => {
          setCrosshair((prev) => (prev?.pinned ? prev : null));
          if (panRef.current.mode !== "idle") {
            panRef.current = { mode: "idle" };
            setIsPanning(false);
          }
        }}
      >
        {/* Grid */}
        {yTicks.map((t: number) => (
          <line
            key={t}
            x1={PAD_L} x2={W - PAD_R}
            y1={toY(t)} y2={toY(t)}
            stroke="hsl(var(--border))"
            strokeWidth={0.5}
          />
        ))}

        {/* Y-axis labels */}
        {yTicks.map((t: number) => (
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

        {/* Future area — tinted region to the right of the last data bar */}
        {n < viewportBars && n > 0 && (() => {
          const futureX = xOf(n - 1) + barStep / 2;
          return (
            <rect
              x={futureX} y={PAD_T}
              width={W - PAD_R - futureX} height={H_PRICE - PAD_T - PAD_B}
              fill="hsl(var(--muted))" opacity={0.18}
              pointerEvents="none"
            />
          );
        })()}

        {/* SMAs — prefix sums + memoized paths (see smaPathDefs) */}
        {smaPathDefs.map(({ key, color, d }) =>
          d ? (
            <path
              key={`sma-${key}`}
              d={d}
              fill="none"
              stroke={color}
              strokeWidth={1.5}
              strokeLinejoin="round"
              opacity={0.85}
            />
          ) : null,
        )}

        {/* Candles */}
        {displaySlice.map((bar, i) => {
          const cx = xOf(i);
          const up = bar.close >= bar.open;
          const color = up ? "#10b981" : "#ef4444";
          const bodyTop = toY(Math.max(bar.open, bar.close));
          const bodyBot = toY(Math.min(bar.open, bar.close));
          const bodyH = Math.max(bodyBot - bodyTop, 1);

          return (
            <g key={sliceStart + i}>
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

        {/* Annotations (AI + user) */}
        {annotations.map((ann) => {
          const color = ANNOTATION_COLORS[ann.role];
          const LABEL_FONT = 10;
          const canDelete = !!onAnnotationDelete;

          if (ann.type === "horizontal") {
            const y = toY(ann.price);
            if (y < PAD_T || y > H_PRICE - PAD_B) return null;
            return (
              <g key={ann.id} style={{ cursor: canDelete ? "pointer" : "default" }} onClick={canDelete ? (ev) => { ev.stopPropagation(); onAnnotationDelete(ann.id); } : undefined}>
                {/* Wide invisible hit area */}
                <line x1={PAD_L} x2={W - PAD_R} y1={y} y2={y} stroke="transparent" strokeWidth={10} />
                <line
                  x1={PAD_L} x2={W - PAD_R}
                  y1={y} y2={y}
                  stroke={color} strokeWidth={1.5} strokeDasharray={ann.origin === "user" ? "none" : "6 3"} opacity={0.85}
                />
                {ann.label && (
                  <text x={PAD_L + 4} y={y - 3} fontSize={LABEL_FONT} fill={color} opacity={0.9}>
                    {ann.label}
                  </text>
                )}
              </g>
            );
          }

          if (ann.type === "zone") {
            const yTop = toY(Math.max(ann.priceTop, ann.priceBottom));
            const yBot = toY(Math.min(ann.priceTop, ann.priceBottom));
            return (
              <g key={ann.id} style={{ cursor: canDelete ? "pointer" : "default" }} onClick={canDelete ? (ev) => { ev.stopPropagation(); onAnnotationDelete(ann.id); } : undefined}>
                <rect
                  x={PAD_L} y={yTop}
                  width={W - PAD_L - PAD_R} height={Math.max(8, yBot - yTop)}
                  fill={color} opacity={0.12}
                />
                <line x1={PAD_L} x2={W - PAD_R} y1={yTop} y2={yTop} stroke={color} strokeWidth={1} opacity={0.5} />
                <line x1={PAD_L} x2={W - PAD_R} y1={yBot} y2={yBot} stroke={color} strokeWidth={1} opacity={0.5} />
                {ann.label && (
                  <text x={PAD_L + 4} y={yTop - 3} fontSize={LABEL_FONT} fill={color} opacity={0.9}>
                    {ann.label}
                  </text>
                )}
              </g>
            );
          }

          if (ann.type === "trend_line") {
            const fromGlobal = data.findIndex(d => d.date.slice(0, 10) === ann.fromDate.slice(0, 10));
            const toGlobal   = data.findIndex(d => d.date.slice(0, 10) === ann.toDate.slice(0, 10));
            if (fromGlobal < 0 || toGlobal < 0) return null;
            const fromLocal = fromGlobal - sliceStart;
            const toLocal   = toGlobal   - sliceStart;
            const clamp = (v: number) => Math.max(-1, Math.min(n, v));
            const x1 = xOf(clamp(fromLocal));
            const x2 = xOf(clamp(toLocal));
            const y1 = toY(ann.fromPrice);
            const y2 = toY(ann.toPrice);
            return (
              <g key={ann.id} style={{ cursor: canDelete ? "pointer" : "default" }} onClick={canDelete ? (ev) => { ev.stopPropagation(); onAnnotationDelete(ann.id); } : undefined}>
                {/* Wide invisible hit area */}
                <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="transparent" strokeWidth={10} />
                <line x1={x1} y1={y1} x2={x2} y2={y2} stroke={color} strokeWidth={1.5} opacity={0.85} />
                {ann.label && (
                  <text x={(x1 + x2) / 2} y={Math.min(y1, y2) - 3} fontSize={LABEL_FONT} fill={color} opacity={0.9} textAnchor="middle">
                    {ann.label}
                  </text>
                )}
              </g>
            );
          }

          return null;
        })}

        {/* Pivot marker: dot at bar + horizontal line to the right edge of the price pane */}
        {pivotMarker && (() => {
          const pbi = resolvePivotBarIndex(data, pivotMarker);
          if (pbi < sliceStart || pbi > sliceStart + n - 1) return null;
          const px = xOf(pbi - sliceStart);
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
        {xTickIndices.map((i: number) => (
          <text
            key={`xl-${sliceStart + i}`}
            x={xOf(i)}
            y={H_PRICE - PAD_B + 14}
            textAnchor="middle"
            fontSize={10}
            fill="hsl(var(--muted-foreground))"
          >
            {displaySlice[i]?.date?.slice(5)} {/* MM-DD */}
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
        {displaySlice.map((bar, i) => {
          const cx = xOf(i);
          const up = bar.close >= bar.open;
          const color = up ? "#10b981" : "#ef4444";
          const volY = toVolY(bar.volume);
          const volH = H_PRICE + 16 + (H_VOL - 8) - volY;
          return (
            <rect
              key={`v-${sliceStart + i}`}
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

          // Derive global bar indices from x positions for stats only
          const toIdx = (x: number) => {
            const rawLocal = (x - PAD_L - barStep / 2) / barStep;
            const local = Math.max(0, Math.min(n - 1, Math.round(rawLocal)));
            return Math.min(
              data.length - 1,
              Math.max(0, sliceStart + local),
            );
          };
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
          const localX = barIdx - sliceStart;
          if (localX < 0 || localX > n - 1) return null;

          const cx = xOf(localX);
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
        const toIdx = (x: number) => {
          const rawLocal = (x - PAD_L - barStep / 2) / barStep;
          const local = Math.max(0, Math.min(n - 1, Math.round(rawLocal)));
          return Math.min(
            data.length - 1,
            Math.max(0, sliceStart + local),
          );
        };
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
