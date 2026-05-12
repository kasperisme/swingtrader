"use client";

import { useEffect, useMemo, useState } from "react";
import { Loader2, X } from "lucide-react";
import {
  articlesForCell,
  articlesForDimensionCell,
  CLUSTER_LABELS,
  colorForScore,
  formatBucketTooltip,
  GRANULARITY_MS,
  type HeatmapCluster,
  type HeatmapGranularity,
  type HeatmapInputRow,
} from "@/lib/news-impact-heatmap/aggregate";
import {
  getArticlesByIds,
  type HeatmapArticle,
} from "@/app/actions/news-impact-heatmap";

const MAX_ARTICLES = 12;

type SortKey = "impactDesc" | "impactAsc" | "magnitude" | "newest" | "oldest";

const SORT_OPTIONS: Array<{ key: SortKey; label: string; title: string }> = [
  { key: "impactDesc", label: "Most positive", title: "Highest signed impact first" },
  { key: "impactAsc", label: "Most negative", title: "Lowest signed impact first" },
  { key: "magnitude", label: "Strongest", title: "Largest |impact| first — strongest signal regardless of sign" },
  { key: "newest", label: "Newest", title: "Most recently published first" },
  { key: "oldest", label: "Oldest", title: "Earliest published first" },
];

function publishedMs(article: { published_at: string | null; created_at: string }): number {
  const p = article.published_at ? Date.parse(article.published_at) : NaN;
  if (Number.isFinite(p)) return p;
  const c = Date.parse(article.created_at);
  return Number.isFinite(c) ? c : 0;
}

function sortArticles(articles: RankedArticle[], key: SortKey): RankedArticle[] {
  const out = articles.slice();
  switch (key) {
    case "impactDesc":
      out.sort((a, b) => b.impact - a.impact);
      break;
    case "impactAsc":
      out.sort((a, b) => a.impact - b.impact);
      break;
    case "magnitude":
      out.sort((a, b) => Math.abs(b.impact) - Math.abs(a.impact));
      break;
    case "newest":
      out.sort((a, b) => publishedMs(b) - publishedMs(a));
      break;
    case "oldest":
      out.sort((a, b) => publishedMs(a) - publishedMs(b));
      break;
  }
  return out;
}

export type HeatmapCellDrilldownProps = {
  rows: HeatmapInputRow[];
  cluster: HeatmapCluster;
  bucketIso: string;
  granularity: HeatmapGranularity;
  /** When the heatmap is smoothed with a trailing window of N buckets, the
   *  drill-down widens its article fetch to the same window so the listed
   *  stories correspond to the smoothed value, not just the clicked bucket. */
  smoothingWindow?: number;
  onClose?: () => void;
  /** When set, the drill-down narrows to articles where this specific sub-factor fired. */
  dimensionKey?: string;
  /** Pretty label for the dimension — used in the header. */
  dimensionLabel?: string;
};

type RankedArticle = HeatmapArticle & { impact: number };

export function HeatmapCellDrilldown({
  rows,
  cluster,
  bucketIso,
  granularity,
  smoothingWindow = 1,
  onClose,
  dimensionKey,
  dimensionLabel,
}: HeatmapCellDrilldownProps) {
  const [articles, setArticles] = useState<RankedArticle[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>("impactDesc");

  const windowBuckets = Math.max(1, Math.floor(smoothingWindow));

  const sortedArticles = useMemo(
    () => (articles ? sortArticles(articles, sortKey) : null),
    [articles, sortKey],
  );

  const windowStartIso = useMemo(() => {
    if (windowBuckets <= 1) return null;
    const startMs = Date.parse(bucketIso);
    if (!Number.isFinite(startMs)) return null;
    return new Date(
      startMs - (windowBuckets - 1) * GRANULARITY_MS[granularity],
    ).toISOString();
  }, [bucketIso, granularity, windowBuckets]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setArticles(null);

    const ranked = (dimensionKey
      ? articlesForDimensionCell(
          rows,
          cluster,
          dimensionKey,
          bucketIso,
          granularity,
          windowBuckets,
        )
      : articlesForCell(rows, cluster, bucketIso, granularity, windowBuckets)
    ).slice(0, MAX_ARTICLES);
    if (ranked.length === 0) {
      setArticles([]);
      setLoading(false);
      return () => {
        cancelled = true;
      };
    }

    const ids = ranked.map((r) => r.article_id);
    const impactById = new Map(ranked.map((r) => [r.article_id, r.impact]));

    getArticlesByIds(ids)
      .then((res) => {
        if (cancelled) return;
        if (!res.ok) {
          setError(res.error);
          return;
        }
        setArticles(
          res.data.map((a) => ({ ...a, impact: impactById.get(a.id) ?? 0 })),
        );
      })
      .catch(() => {
        if (!cancelled) setError("Failed to load stories.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [rows, cluster, bucketIso, granularity, dimensionKey, windowBuckets]);

  return (
    <div className="mt-3 rounded-lg border bg-card/60 px-3 py-2.5 sm:px-4 sm:py-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground/80">
            Top stories
          </p>
          <h4 className="mt-0.5 text-sm font-semibold tracking-tight">
            {CLUSTER_LABELS[cluster]}
            {dimensionLabel && (
              <span className="ml-1.5 text-foreground/70">
                / {dimensionLabel}
              </span>
            )}
            <span className="ml-1.5 font-normal text-muted-foreground">
              ·{" "}
              {windowStartIso
                ? `${formatBucketTooltip(windowStartIso, granularity)} → ${formatBucketTooltip(bucketIso, granularity)}`
                : formatBucketTooltip(bucketIso, granularity)}
            </span>
          </h4>
          {windowBuckets > 1 && (
            <p className="mt-0.5 text-[10px] text-muted-foreground/70">
              Trailing {windowBuckets}-bucket window — articles match the smoothed score.
            </p>
          )}
        </div>
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            aria-label="Close"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        )}
      </div>

      {articles && articles.length > 1 && !loading && !error && (
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          <span className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground/70">
            Sort
          </span>
          <div className="inline-flex flex-wrap gap-0.5 rounded-full border border-border bg-background/60 p-0.5">
            {SORT_OPTIONS.map((opt) => {
              const selected = opt.key === sortKey;
              return (
                <button
                  key={opt.key}
                  type="button"
                  onClick={() => setSortKey(opt.key)}
                  title={opt.title}
                  className={`rounded-full px-2.5 py-1 text-[10px] font-semibold transition-colors ${
                    selected
                      ? "bg-foreground text-background"
                      : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {opt.label}
                </button>
              );
            })}
          </div>
        </div>
      )}

      <div className="mt-2">
        {loading ? (
          <div className="flex items-center gap-2 py-3 text-xs text-muted-foreground">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            Loading stories…
          </div>
        ) : error ? (
          <p className="py-3 text-xs text-rose-500">{error}</p>
        ) : !sortedArticles || sortedArticles.length === 0 ? (
          <p className="py-3 text-xs text-muted-foreground">
            {windowBuckets > 1
              ? "No stories fired this cluster in the trailing window."
              : "No stories fired this cluster in this bucket."}
          </p>
        ) : (
          <ul className="flex flex-col divide-y divide-border/60">
            {sortedArticles.map((a) => (
              <ArticleRow key={a.id} article={a} />
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function ArticleRow({ article }: { article: RankedArticle }) {
  const fill = colorForScore(article.impact);
  const title =
    (article.title ?? "").trim() || (article.url ?? "").trim() || "Untitled story";
  return (
    <li className="flex items-start gap-2.5 py-2">
      <span
        className="mt-1 inline-block h-2 w-2 shrink-0 rounded-[2px]"
        style={{ backgroundColor: fill ?? "transparent" }}
        title={`Impact ${article.impact >= 0 ? "+" : ""}${article.impact.toFixed(2)}`}
        aria-hidden
      />
      <p className="line-clamp-2 min-w-0 flex-1 text-sm font-medium leading-snug text-foreground">
        {title}
      </p>
      {article.published_at && (
        <span className="shrink-0 self-center text-[10px] text-muted-foreground/80">
          {formatAge(article.published_at)}
        </span>
      )}
      <span className="ml-1 shrink-0 self-center font-mono text-[11px] tabular-nums text-foreground/80">
        {article.impact >= 0 ? "+" : ""}
        {article.impact.toFixed(2)}
      </span>
    </li>
  );
}

function formatAge(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const diffMs = Date.now() - d.getTime();
  if (diffMs < 0) return "just now";
  const minute = 60_000;
  const hour = 60 * minute;
  const day = 24 * hour;
  if (diffMs < hour) return `${Math.max(1, Math.floor(diffMs / minute))}m ago`;
  if (diffMs < day) return `${Math.floor(diffMs / hour)}h ago`;
  return `${Math.floor(diffMs / day)}d ago`;
}
