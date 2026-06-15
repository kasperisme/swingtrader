"use client";

import type { ScreeningTickerSentimentHeadRow } from "@/app/actions/screenings";

export type FetchTickerSentimentResult =
  | { ok: true; data: ScreeningTickerSentimentHeadRow[] }
  | { ok: false; error: string };

/**
 * Drop-in client replacement for the screeningsGetTickerSentimentHeadRows server
 * action: same `{ ok, data } | { ok: false, error }` shape, but routed through
 * the /api/screenings/ticker-sentiment route handler so it runs concurrently
 * instead of queueing on Next.js's sequential Server Action queue (where it was
 * blocking the chart's OHLC fetch).
 */
export async function fetchTickerSentimentHeadRows(
  symbols: string[],
): Promise<FetchTickerSentimentResult> {
  try {
    const res = await fetch("/api/screenings/ticker-sentiment", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ symbols }),
    });
    if (!res.ok) {
      return { ok: false, error: `Request failed (${res.status})` };
    }
    return (await res.json()) as FetchTickerSentimentResult;
  } catch (err) {
    return {
      ok: false,
      error: err instanceof Error ? err.message : "Failed to load ticker sentiment",
    };
  }
}
