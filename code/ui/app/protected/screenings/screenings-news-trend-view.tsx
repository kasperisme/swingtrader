"use client";

import React, { useState, useMemo, useEffect, useRef } from "react";
import { Loader2 } from "lucide-react";
import {
  NewsTrendsUI,
  type ArticleImpact,
} from "../news-trends/news-trends-ui";
import { screeningsGetNewsImpacts } from "@/app/actions/screenings";
import type { NoteStatus } from "./screenings-types";

function applyCompanyVector(
  articles: ArticleImpact[],
  companyDims: Record<string, number>,
): ArticleImpact[] {
  return articles.map((a) => ({
    ...a,
    impact_json: Object.fromEntries(
      Object.entries(a.impact_json).map(([k, v]) => [
        k,
        v * (companyDims[k] ?? 0),
      ]),
    ),
  }));
}

export function StockNewsTrendView({
  symbols,
  companyVectorDimensions,
  selectedTicker,
  dismissed,
  onDismiss,
  onRestore,
  getStatus,
  onSetStatus,
  hasComment,
  onEditComment,
  getTickerMeta,
}: {
  symbols: string[];
  companyVectorDimensions: Record<string, Record<string, number>>;
  selectedTicker: string | null;
  onSelect: (ticker: string) => void;
  dismissed: Set<string>;
  onDismiss: (ticker: string) => void;
  onRestore: (ticker: string) => void;
  getStatus: (ticker: string) => NoteStatus;
  onSetStatus: (ticker: string, status: NoteStatus) => void;
  hasComment: (ticker: string) => boolean;
  onEditComment: (ticker: string) => void;
  getTickerMeta: (ticker: string) => {
    sector: string;
    industry: string;
    subSector: string;
  };
}) {
  const [articles, setArticles] = useState<ArticleImpact[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const containerRef = useRef<HTMLDivElement>(null);
  const [chartHeight, setChartHeight] = useState(436);
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => {
      const w = entry.contentRect.width;
      setChartHeight(Math.max(260, Math.round(w * (436 / 900))));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const eligible = useMemo(
    () =>
      symbols.filter((s) => {
        const d = companyVectorDimensions[s];
        return d && Object.keys(d).length > 0;
      }),
    [symbols, companyVectorDimensions],
  );

  const symbol = useMemo(() => {
    if (eligible.length === 0) return null;
    if (selectedTicker == null) return eligible[0] ?? null;
    if (eligible.includes(selectedTicker)) return selectedTicker;
    if (symbols.includes(selectedTicker)) return null;
    return eligible[0] ?? null;
  }, [eligible, symbols, selectedTicker]);

  useEffect(() => {
    setLoading(true);
    setError(null);
    screeningsGetNewsImpacts()
      .then((res) => {
        if (!res.ok) {
          setError("Failed to load news data");
          return;
        }
        setArticles(res.data);
      })
      .catch(() => setError("Failed to load news data"))
      .finally(() => setLoading(false));
  }, []);

  const weightedArticles = useMemo(() => {
    if (!symbol || articles.length === 0) return [];
    const dims = companyVectorDimensions[symbol] ?? {};
    return applyCompanyVector(articles, dims);
  }, [symbol, articles, companyVectorDimensions]);

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground py-8">
        <Loader2 className="w-4 h-4 animate-spin" />
        Loading news data…
      </div>
    );
  }
  if (error) return <p className="text-sm text-rose-500 py-4">{error}</p>;
  if (eligible.length === 0) {
    return (
      <p className="text-sm text-muted-foreground py-8 text-center">
        None of the filtered stocks have a company vector. Run the vector
        builder first.
      </p>
    );
  }

  if (
    symbol == null &&
    selectedTicker != null &&
    symbols.includes(selectedTicker)
  ) {
    return (
      <p className="text-sm text-muted-foreground py-8 text-center">
        No company vector for {selectedTicker}. News trend weighting is
        unavailable for this symbol.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div ref={containerRef} className="w-full">
        {symbol && weightedArticles.length > 0 && (
          <NewsTrendsUI
            key={symbol}
            articles={weightedArticles}
            chartHeight={chartHeight}
            showMainChartFrame={false}
          />
        )}
      </div>
      {symbol && weightedArticles.length === 0 && articles.length > 0 && (
        <p className="text-sm text-muted-foreground py-8 text-center">
          No news data available.
        </p>
      )}

      {symbols.length > eligible.length && (
        <p className="text-xs text-muted-foreground">
          {symbols.length - eligible.length} stock
          {symbols.length - eligible.length !== 1 ? "s" : ""} skipped — no
          company vector.
        </p>
      )}
    </div>
  );
}