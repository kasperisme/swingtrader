/**
 * In-memory client cache for OHLC series fetched via the `fmpGetOhlc` server
 * action. Keyed by symbol + interval + date range so a given chart window is
 * fetched at most once per TTL. Enables prefetching adjacent tickers and the
 * other date-filter ranges so navigation in the screenings deep-dive renders
 * instantly (no loading spinner, no refetch).
 */

import { fmpGetOhlc, type FmpOhlcBar } from "@/app/actions/fmp";
import type { OhlcBar } from "@/components/ticker-charts/types";

export type OhlcDateRange = { from: string; to: string };

/** OHLC is intraday-stable enough that a few minutes of caching is safe. */
const TTL_MS = 5 * 60 * 1000;

type Entry = { data: OhlcBar[]; storedAt: number };

const cache = new Map<string, Entry>();
const inflight = new Map<string, Promise<OhlcBar[] | null>>();

export function ohlcCacheKey(
  symbol: string,
  interval: string | undefined,
  dateRange: OhlcDateRange | undefined,
): string {
  const sym = symbol.trim().toUpperCase();
  const iv = interval ?? "1day";
  const range = dateRange
    ? `${dateRange.from.slice(0, 10)}:${dateRange.to.slice(0, 10)}`
    : "default";
  return `${sym}|${iv}|${range}`;
}

/** Synchronous read — returns cached rows if present and fresh, else null. */
export function getCachedOhlc(
  symbol: string,
  interval: string | undefined,
  dateRange: OhlcDateRange | undefined,
): OhlcBar[] | null {
  if (!symbol?.trim()) return null;
  const key = ohlcCacheKey(symbol, interval, dateRange);
  const entry = cache.get(key);
  if (!entry) return null;
  if (Date.now() - entry.storedAt > TTL_MS) {
    cache.delete(key);
    return null;
  }
  return entry.data;
}

export function putCachedOhlc(
  symbol: string,
  interval: string | undefined,
  dateRange: OhlcDateRange | undefined,
  data: OhlcBar[],
): void {
  if (!symbol?.trim()) return;
  cache.set(ohlcCacheKey(symbol, interval, dateRange), {
    data,
    storedAt: Date.now(),
  });
}

/**
 * Fetch + cache an OHLC window unless it is already fresh or in flight.
 * Fire-and-forget: callers `void prefetchOhlc(...)`. In-flight requests are
 * deduped so prefetch + the chart's own fetch never race to the same window.
 */
export async function prefetchOhlc(
  symbol: string,
  interval: string | undefined,
  dateRange: OhlcDateRange | undefined,
): Promise<OhlcBar[] | null> {
  if (!symbol?.trim()) return null;
  const key = ohlcCacheKey(symbol, interval, dateRange);
  const entry = cache.get(key);
  if (entry && Date.now() - entry.storedAt <= TTL_MS) return entry.data;
  const pending = inflight.get(key);
  if (pending) return pending;

  const p = (async () => {
    const res = await fmpGetOhlc(symbol, interval, dateRange);
    if (res.ok) {
      const rows: OhlcBar[] = res.data as FmpOhlcBar[];
      cache.set(key, { data: rows, storedAt: Date.now() });
      return rows;
    }
    return null;
  })().finally(() => {
    inflight.delete(key);
  });

  inflight.set(key, p);
  return p;
}
