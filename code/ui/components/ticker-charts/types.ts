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

/** Single saved pivot: dot at bar + horizontal ray to the right (price pane only). */
export type PivotMarker = { barIdx: number; date: string; price: number };

export function resolvePivotBarIndex(
  data: OhlcBar[],
  pivot: { barIdx: number; date: string },
): number {
  const byDate = data.findIndex((d) => d.date === pivot.date);
  if (byDate >= 0) return byDate;
  return Math.max(0, Math.min(data.length - 1, pivot.barIdx));
}

export type AnnotationRole = "support" | "resistance" | "entry" | "stop" | "target" | "info";

export type ChartAnnotation =
  | {
      id: string;
      type: "horizontal";
      price: number;
      role: AnnotationRole;
      label?: string;
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
    }
  | {
      id: string;
      type: "zone";
      priceTop: number;
      priceBottom: number;
      role: AnnotationRole;
      label?: string;
    };

export const ANNOTATION_COLORS: Record<AnnotationRole, string> = {
  support:    "#22c55e",
  resistance: "#ef4444",
  entry:      "#3b82f6",
  stop:       "#f59e0b",
  target:     "#a855f7",
  info:       "#94a3b8",
};

export function pivotFromMetadata(
  meta: Record<string, unknown> | undefined,
): PivotMarker | null {
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
