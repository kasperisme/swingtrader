export interface OhlcBar {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface ChartPoint {
  barIdx: number;
  date: string;
  price: number;
  open: number;
  high: number;
  low: number;
  close: number;
}

/** Single saved entry: dot at bar + horizontal ray to the right (price pane only). */
export type EntryMarker = {
  barIdx: number;
  date: string;
  price: number;
  direction?: "long" | "short";
  take_profit?: number;
  stop_loss?: number;
};

export function resolveEntryBarIndex(
  data: OhlcBar[],
  entry: { barIdx: number; date: string },
): number {
  if (data.length === 0) return 0;
  // Exact match first (fast path).
  const exact = data.findIndex((d) => d.date === entry.date);
  if (exact >= 0) return exact;
  // Normalise to calendar day: metadata_json dates may carry a time
  // component ("2026-05-22 00:00") while OHLC bars are "2026-05-22"
  // (or vice versa). Compare on the YYYY-MM-DD prefix so the marker
  // anchors to the right bar regardless of formatting.
  const key = entry.date.slice(0, 10);
  if (key) {
    const sameDay = data.findIndex((d) => d.date.slice(0, 10) === key);
    if (sameDay >= 0) return sameDay;
    // No bar on that exact day (e.g. a weekly/4h chart, or a non-trading
    // day): anchor to the last bar on or before the entry date so the
    // marker lands in the right region instead of snapping to a stale
    // absolute barIdx. `data` is sorted ascending by date.
    let candidate = -1;
    for (let i = 0; i < data.length; i++) {
      if (data[i]!.date.slice(0, 10) <= key) candidate = i;
      else break;
    }
    if (candidate >= 0) return candidate;
    // Entry predates all loaded bars — clamp to the oldest bar.
    return 0;
  }
  // No usable date — fall back to the stored absolute index.
  return Math.max(0, Math.min(data.length - 1, entry.barIdx));
}

export type AnnotationRole = "support" | "resistance" | "entry" | "stop" | "target" | "info";

export type ChartAnnotation =
  | {
      id: string;
      type: "horizontal";
      price: number;
      role: AnnotationRole;
      label?: string;
      origin?: "ai" | "user";
    }
  | {
      id: string;
      type: "trend_line";
      fromDate: string;
      fromPrice: number;
      toDate: string;
      toPrice: number;
      role: AnnotationRole;
      label?: string;
      origin?: "ai" | "user";
    }
  | {
      id: string;
      type: "zone";
      priceTop: number;
      priceBottom: number;
      role: AnnotationRole;
      label?: string;
      origin?: "ai" | "user";
    };

export const ANNOTATION_COLORS: Record<AnnotationRole, string> = {
  support:    "#22c55e",
  resistance: "#ef4444",
  entry:      "#3b82f6",
  stop:       "#f59e0b",
  target:     "#a855f7",
  info:       "#94a3b8",
};

function parseMarkerObject(obj: unknown): EntryMarker | null {
  if (
    obj &&
    typeof obj === "object" &&
    typeof (obj as { barIdx?: unknown }).barIdx === "number" &&
    typeof (obj as { date?: unknown }).date === "string" &&
    typeof (obj as { price?: unknown }).price === "number"
  ) {
    const d = (obj as { direction?: unknown }).direction;
    const tp = (obj as { take_profit?: unknown }).take_profit;
    const sl = (obj as { stop_loss?: unknown }).stop_loss;
    return {
      barIdx: (obj as { barIdx: number }).barIdx,
      date: (obj as { date: string }).date,
      price: (obj as { price: number }).price,
      ...(d === "long" || d === "short" ? { direction: d } : {}),
      ...(typeof tp === "number" ? { take_profit: tp } : {}),
      ...(typeof sl === "number" ? { stop_loss: sl } : {}),
    };
  }
  return null;
}

export function entryFromMetadata(
  meta: Record<string, unknown> | undefined,
): EntryMarker | null {
  if (!meta) return null;
  // Read new `entry` key first, fall back to legacy `pivot` and `pivot_points`
  const fromEntry = parseMarkerObject(meta.entry);
  if (fromEntry) return fromEntry;
  const fromPivot = parseMarkerObject(meta.pivot);
  if (fromPivot) return fromPivot;
  const raw = meta.pivot_points;
  if (Array.isArray(raw) && raw.length > 0) {
    const first = raw[0];
    const barIdx =
      typeof (first as { barIdx?: unknown }).barIdx === "number"
        ? (first as { barIdx: number }).barIdx
        : 0;
    return parseMarkerObject({ ...(first as object), barIdx });
  }
  return null;
}
