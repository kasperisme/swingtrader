"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { ArticleImpact } from "./news-trends-types";
import {
  putNewsTrendsCache,
  readNewsTrendsHydrationBundle,
} from "@/lib/news-trends/news-trends-idb-cache";
import { NewsTrendsUI } from "./news-trends-ui";
import type {
  ClusterTrendRow,
  DimensionTrendRow,
  ViewMode,
} from "./news-trends-series";

type DailySupplementResponse = {
  articles: ArticleImpact[];
};

type HourlySupplementResponse = {
  clusterHourly: ClusterTrendRow[];
};

type DimensionDailyResponse = {
  dimensionDaily: DimensionTrendRow[];
};

type DimensionHourlyResponse = {
  dimensionHourly: DimensionTrendRow[];
};

export function NewsTrendsClient({
  clusterDaily,
}: {
  clusterDaily: ClusterTrendRow[];
}) {
  const [articles, setArticles] = useState<ArticleImpact[]>([]);
  const [clusterHourly, setClusterHourly] = useState<ClusterTrendRow[]>([]);
  const [dimensionDaily, setDimensionDaily] = useState<DimensionTrendRow[]>(
    [],
  );
  const [dimensionHourly, setDimensionHourly] = useState<DimensionTrendRow[]>(
    [],
  );
  const [dailySupplementError, setDailySupplementError] = useState<
    string | null
  >(null);
  const [dailySupplementDone, setDailySupplementDone] = useState(false);
  const [hourlySupplementError, setHourlySupplementError] = useState<
    string | null
  >(null);
  const [hourlyLoading, setHourlyLoading] = useState(false);
  /** True while hourly cluster fetch runs (prefetch or user); drives hourly chart loading state. */
  const [hourlyFetchPending, setHourlyFetchPending] = useState(false);
  const hourlyFetchRef = useRef({ loaded: false });
  const hourlyInflightRef = useRef<Promise<boolean> | null>(null);
  const dimDailyRef = useRef({ loaded: false, inFlight: false });
  const dimHourlyRef = useRef({ loaded: false, inFlight: false });
  const [dimensionFetchLoading, setDimensionFetchLoading] = useState<
    false | ViewMode
  >(false);
  const [dimensionFetchError, setDimensionFetchError] = useState<string | null>(
    null,
  );
  /** Avoid hydration mismatch: async status differs from SSR snapshot until mount. */
  const [hasMounted, setHasMounted] = useState(false);

  useEffect(() => {
    setHasMounted(true);
  }, []);

  useEffect(() => {
    putNewsTrendsCache("clusterDaily", clusterDaily);
  }, [clusterDaily]);

  const fetchHourlyClusterCore = useCallback((): Promise<boolean> => {
    if (hourlyFetchRef.current.loaded) return Promise.resolve(true);
    if (hourlyInflightRef.current) return hourlyInflightRef.current;
    setHourlyFetchPending(true);
    const p = (async (): Promise<boolean> => {
      try {
        const res = await fetch("/api/news/trends/supplement?part=hourly", {
          credentials: "same-origin",
        });
        if (!res.ok) return false;
        const data = (await res.json()) as HourlySupplementResponse;
        const rows = data.clusterHourly ?? [];
        setClusterHourly(rows);
        hourlyFetchRef.current.loaded = true;
        putNewsTrendsCache("clusterHourly", rows);
        return true;
      } catch {
        return false;
      } finally {
        hourlyInflightRef.current = null;
        setHourlyFetchPending(false);
      }
    })();
    hourlyInflightRef.current = p;
    return p;
  }, []);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const bundle = await readNewsTrendsHydrationBundle();
      if (cancelled) return;

      if (bundle.articles && bundle.articles.length > 0) {
        setArticles(bundle.articles);
        setDailySupplementDone(true);
      }
      if (bundle.clusterHourly && bundle.clusterHourly.length > 0) {
        setClusterHourly(bundle.clusterHourly);
        hourlyFetchRef.current.loaded = true;
      }
      if (bundle.dimensionDaily && bundle.dimensionDaily.length > 0) {
        setDimensionDaily(bundle.dimensionDaily);
        dimDailyRef.current.loaded = true;
      }
      if (bundle.dimensionHourly && bundle.dimensionHourly.length > 0) {
        setDimensionHourly(bundle.dimensionHourly);
        dimHourlyRef.current.loaded = true;
      }

      try {
        const res = await fetch("/api/news/trends/supplement?part=daily", {
          credentials: "same-origin",
        });
        if (cancelled) return;
        if (!res.ok) {
          const msg =
            res.status === 401
              ? "Sign in required to load headlines."
              : `Could not load extra trends data (${res.status}).`;
          setDailySupplementError(msg);
          return;
        }
        const data = (await res.json()) as DailySupplementResponse;
        if (cancelled) return;
        const nextArticles = data.articles ?? [];
        setArticles(nextArticles);
        setDailySupplementError(null);
        putNewsTrendsCache("articles", nextArticles);
      } catch {
        if (!cancelled) {
          setDailySupplementError("Network error loading headlines.");
        }
      } finally {
        if (!cancelled) setDailySupplementDone(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  /** Fire-and-forget hourly cluster prefetch after headlines path settles. */
  useEffect(() => {
    if (!dailySupplementDone) return;
    if (hourlyFetchRef.current.loaded) return;
    void fetchHourlyClusterCore();
  }, [dailySupplementDone, fetchHourlyClusterCore]);

  const requestHourlyTrends = useCallback(() => {
    if (hourlyFetchRef.current.loaded) return;
    setHourlyLoading(true);
    setHourlySupplementError(null);
    void fetchHourlyClusterCore().then((ok) => {
      if (!ok) {
        setHourlySupplementError(
          "Could not load hourly cluster series (try again).",
        );
      }
      setHourlyLoading(false);
    });
  }, [fetchHourlyClusterCore]);

  const ensureDimensionAggregates = useCallback((granularity: ViewMode) => {
    if (granularity === "daily") {
      const r = dimDailyRef.current;
      if (r.loaded || r.inFlight) return;
      r.inFlight = true;
      setDimensionFetchError(null);
      setDimensionFetchLoading("daily");
      void (async () => {
        try {
          const res = await fetch(
            "/api/news/trends/supplement?part=dimension-daily",
            { credentials: "same-origin" },
          );
          if (!res.ok) {
            setDimensionFetchError(
              res.status === 401
                ? "Sign in required to load dimension series."
                : `Could not load daily dimensions (${res.status}).`,
            );
            return;
          }
          const data = (await res.json()) as DimensionDailyResponse;
          const rows = data.dimensionDaily ?? [];
          setDimensionDaily(rows);
          dimDailyRef.current.loaded = true;
          putNewsTrendsCache("dimensionDaily", rows);
        } catch {
          setDimensionFetchError("Network error loading daily dimensions.");
        } finally {
          dimDailyRef.current.inFlight = false;
          setDimensionFetchLoading(false);
        }
      })();
      return;
    }

    const rh = dimHourlyRef.current;
    if (rh.loaded || rh.inFlight) return;
    rh.inFlight = true;
    setDimensionFetchError(null);
    setDimensionFetchLoading("hourly");
    void (async () => {
      try {
        const res = await fetch(
          "/api/news/trends/supplement?part=dimension-hourly",
          { credentials: "same-origin" },
        );
        if (!res.ok) {
          setDimensionFetchError(
            res.status === 401
              ? "Sign in required to load dimension series."
              : `Could not load hourly dimensions (${res.status}).`,
          );
          return;
        }
        const data = (await res.json()) as DimensionHourlyResponse;
        const rows = data.dimensionHourly ?? [];
        setDimensionHourly(rows);
        dimHourlyRef.current.loaded = true;
        putNewsTrendsCache("dimensionHourly", rows);
      } catch {
        setDimensionFetchError("Network error loading hourly dimensions.");
      } finally {
        dimHourlyRef.current.inFlight = false;
        setDimensionFetchLoading(false);
      }
    })();
  }, []);

  return (
    <div className="flex flex-col gap-2">
      {hasMounted && dailySupplementError != null && (
        <p className="text-sm text-destructive">{dailySupplementError}</p>
      )}
      {hasMounted &&
        !dailySupplementDone &&
        dailySupplementError == null && (
          <p className="text-xs text-muted-foreground">Loading headlines…</p>
        )}
      {hasMounted && hourlySupplementError != null && (
        <p className="text-sm text-destructive">{hourlySupplementError}</p>
      )}
      {hasMounted && dimensionFetchError != null && (
        <p className="text-sm text-destructive">{dimensionFetchError}</p>
      )}
      <NewsTrendsUI
        articles={articles}
        clusterDaily={clusterDaily}
        clusterHourly={clusterHourly}
        dimensionDaily={dimensionDaily}
        dimensionHourly={dimensionHourly}
        hourlyClusterLoading={hourlyLoading || hourlyFetchPending}
        onSwitchToHourly={requestHourlyTrends}
        onEnsureDimensionAggregates={ensureDimensionAggregates}
        dimensionAggregatesLoading={dimensionFetchLoading}
      />
    </div>
  );
}
