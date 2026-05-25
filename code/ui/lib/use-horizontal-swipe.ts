"use client";

import { useRef } from "react";
import type { TouchEvent as ReactTouchEvent } from "react";

type Options = {
  /** Finger moves left (next). */
  onSwipeLeft: () => void;
  /** Finger moves right (previous). */
  onSwipeRight: () => void;
  /** When false, no handlers are returned. */
  enabled?: boolean;
  /** Minimum horizontal travel (px) before a swipe counts. */
  minDistance?: number;
  /** Gestures starting inside an element matching this selector are ignored
   * (e.g. the chart, which consumes its own horizontal drag to pan time). */
  ignoreSelector?: string;
};

/**
 * Lightweight horizontal-swipe detector built on raw touch events — no
 * library, no preventDefault, so vertical scrolling and child pointer
 * handlers keep working. A swipe only fires on touchend when the horizontal
 * travel clears `minDistance` and clearly dominates the vertical travel.
 */
export function useHorizontalSwipe({
  onSwipeLeft,
  onSwipeRight,
  enabled = true,
  minDistance = 56,
  ignoreSelector = "[data-swipe-ignore]",
}: Options) {
  const start = useRef<{ x: number; y: number; ignore: boolean } | null>(null);

  function onTouchStart(e: ReactTouchEvent) {
    if (!enabled || e.touches.length !== 1) {
      start.current = null;
      return;
    }
    const t = e.touches[0]!;
    const target = e.target as Element | null;
    const ignore = !!(ignoreSelector && target?.closest?.(ignoreSelector));
    start.current = { x: t.clientX, y: t.clientY, ignore };
  }

  function onTouchEnd(e: ReactTouchEvent) {
    const s = start.current;
    start.current = null;
    if (!s || s.ignore || !enabled) return;
    const t = e.changedTouches[0];
    if (!t) return;
    const dx = t.clientX - s.x;
    const dy = t.clientY - s.y;
    if (Math.abs(dx) < minDistance) return;
    // Must be clearly horizontal so vertical scrolls don't change ticker.
    if (Math.abs(dx) <= Math.abs(dy) * 1.2) return;
    if (dx < 0) onSwipeLeft();
    else onSwipeRight();
  }

  return enabled ? { onTouchStart, onTouchEnd } : {};
}
