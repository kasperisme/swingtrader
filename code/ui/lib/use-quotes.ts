"use client";

import { useState, useEffect } from "react";
import { getCachedQuotes, setCachedQuotes } from "./quote-cache";
import { fmpGetQuote } from "@/app/actions/fmp";

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
      const chunks: string[][] = [];
      for (let i = 0; i < missing.length; i += 10) chunks.push(missing.slice(i, i + 10));

      const fresh: Record<string, FmpQuote | null> = {};
      for (const chunk of chunks) {
        await Promise.all(
          chunk.map(async sym => {
            try {
              const res = await fmpGetQuote(sym);
              if (!res.ok) { fresh[sym] = null; return; }
              const data = res.data;
              fresh[sym] = Array.isArray(data) ? (data[0] ?? null) : null;
            } catch {
              fresh[sym] = null;
            }
          })
        );
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
