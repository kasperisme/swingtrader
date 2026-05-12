"use client";

import { useEffect, useState } from "react";
import { NewsImpactHeatmap } from "@/components/news-impact-heatmap";
import { getNewsImpactHeatmapData } from "@/app/actions/news-impact-heatmap";
import {
  defaultGranularityForRange,
  isCombinationViable,
  rangeToSinceIso,
  type HeatmapGranularity,
  type HeatmapInputRow,
  type HeatmapRange,
} from "@/lib/news-impact-heatmap/aggregate";

export function NewsTrendsHeatmapClient() {
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
  );
}
