"use client";

import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { NewsImpactHeatmap } from "@/components/news-impact-heatmap";
import { CompanyFingerprint } from "@/components/company-fingerprint";
import { getNewsImpactHeatmapData } from "@/app/actions/news-impact-heatmap";
import {
  getCompanyFingerprint,
  type CompanySnapshot,
} from "@/app/actions/company-fingerprint";
import {
  defaultGranularityForRange,
  isCombinationViable,
  rangeToSinceIso,
  type HeatmapGranularity,
  type HeatmapInputRow,
  type HeatmapRange,
} from "@/lib/news-impact-heatmap/aggregate";
import type { NoteStatus } from "./screenings-types";

/**
 * News tab in the screenings deep-dive. Stacks a per-ticker factor-exposure
 * fingerprint (when a ticker is selected) above the market-wide news-impact
 * heatmap. Other props are kept for call-site compatibility.
 */
export function StockNewsTrendView(props: {
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
  const { selectedTicker } = props;

  const [rows, setRows] = useState<HeatmapInputRow[] | null>(null);
  const [nowIso, setNowIso] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [range, setRange] = useState<HeatmapRange>("24h");
  const [granularity, setGranularity] = useState<HeatmapGranularity>(() =>
    defaultGranularityForRange("24h"),
  );

  function handleRangeChange(next: HeatmapRange) {
    setRange(next);
    // Keep the user's granularity sticky across range changes. Only fall back
    // to the range default if the current combo would be invalid (e.g. 24h × 1d).
    if (!isCombinationViable(next, granularity)) {
      setGranularity(defaultGranularityForRange(next));
    }
  }

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    const since = rangeToSinceIso(range, granularity, new Date());
    getNewsImpactHeatmapData(since)
      .then((res) => {
        if (cancelled) return;
        if (!res.ok) {
          setError(res.error);
          return;
        }
        setRows(res.data.rows);
        setNowIso(res.data.nowIso);
      })
      .catch(() => {
        if (!cancelled) setError("Failed to load news impact data.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [range, granularity]);

  return (
    <div className="flex flex-col gap-4">
      {selectedTicker && (
        <CompanyFingerprintSection
          ticker={selectedTicker}
          newsRows={rows ?? undefined}
        />
      )}
      <NewsImpactHeatmap
        rows={rows}
        nowIso={nowIso}
        loading={loading}
        error={error}
        range={range}
        onRangeChange={handleRangeChange}
        granularity={granularity}
        onGranularityChange={setGranularity}
      />
    </div>
  );
}

function CompanyFingerprintSection({
  ticker,
  newsRows,
}: {
  ticker: string;
  newsRows: HeatmapInputRow[] | undefined;
}) {
  const [snapshot, setSnapshot] = useState<CompanySnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setSnapshot(null);
    getCompanyFingerprint(ticker)
      .then((res) => {
        if (cancelled) return;
        if (!res.ok) {
          setError(res.error);
          return;
        }
        setSnapshot(res.data);
      })
      .catch(() => {
        if (!cancelled) setError("Failed to load company fingerprint.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [ticker]);

  if (loading) {
    return (
      <div className="flex items-center gap-2 rounded-lg border bg-card px-4 py-6 text-xs text-muted-foreground">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        Loading {ticker} fingerprint…
      </div>
    );
  }
  if (error) {
    return (
      <div className="rounded-lg border bg-card px-4 py-3 text-xs text-rose-500">
        {error}
      </div>
    );
  }
  if (!snapshot) return null;

  return (
    <CompanyFingerprint
      ticker={snapshot.ticker}
      vectorDate={snapshot.vectorDate}
      dimensions={snapshot.dimensions}
      raw={snapshot.raw}
      metadata={snapshot.metadata}
      newsRows={newsRows}
    />
  );
}
