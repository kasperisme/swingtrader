"use client";

import { useState, useEffect } from "react";
import { getCachedQuotes, setCachedQuotes } from "./quote-cache";

export interface FmpQuote {
  symbol: string;
  name: string;
  price: number;
  changePercentage: number;
  change: number;
  volume: number;
  marketCap: number;
  dayLow: number;
  dayHigh: number;
  yearLow: number;
  yearHigh: number;
  priceAvg50: number;
  priceAvg200: number;
  exchange: string;
  open: number;
  previousClose: number;
  timestamp: number;
}

export function useQuotes(symbols: string[]): {
  quotes: Record<string, FmpQuote | null>;
  loading: boolean;
} {
  const [quotes, setQuotes] = useState<Record<string, FmpQuote | null>>({});
  const [loading, setLoading] = useState(false);
  const symbolsKey = symbols.join(",");

  useEffect(() => {
    if (symbols.length === 0) return;
    let cancelled = false;

    async function fetchAll() {
      const cached = await getCachedQuotes<FmpQuote>(symbols);
      if (cancelled) return;
      if (Object.keys(cached).length > 0) setQuotes(cached);

      const missing = symbols.filter(s => !(s in cached));
      if (missing.length === 0) return;

      setLoading(true);

      // One round-trip to the bulk route handler instead of one server action
      // per symbol. Next.js serializes client-invoked Server Actions, so the old
      // per-symbol fan-out ran sequentially (~60 × ~120ms) and starved the
      // chart's OHLC fetch on the same queue. The route handler runs off that
      // queue and fans the FMP requests out concurrently server-side.
      let fresh: Record<string, FmpQuote | null> = {};
      try {
        const res = await fetch("/api/fmp/quotes", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ symbols: missing }),
        });
        if (res.ok) {
          const json = (await res.json()) as {
            quotes?: Record<string, FmpQuote | null>;
          };
          fresh = json.quotes ?? {};
        }
      } catch {
        fresh = {};
      }

      if (cancelled) return;
      setQuotes(prev => ({ ...prev, ...fresh }));

      const toCache: Record<string, FmpQuote> = {};
      for (const [sym, q] of Object.entries(fresh)) {
        if (q != null) toCache[sym] = q;
      }
      if (Object.keys(toCache).length > 0) await setCachedQuotes(toCache);
      setLoading(false);
    }

    fetchAll().catch(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbolsKey]);

  return { quotes, loading };
}
