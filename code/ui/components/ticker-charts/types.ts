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
  const byDate = data.findIndex((d) => d.date === entry.date);
  if (byDate >= 0) return byDate;
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
