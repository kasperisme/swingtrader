"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import {
  ArrowUpRight,
  CornerDownLeft,
  Loader2,
  Newspaper,
  Search,
  Sparkles,
  X,
} from "lucide-react";
import type { ArticleGridItem } from "@/components/articles-grid";

type SemanticSearchItem = {
  article_id: number;
  title: string | null;
  url: string | null;
  source: string | null;
  slug: string | null;
  image_url: string | null;
  article_stream: string | null;
  published_at: string | null;
  snippet: string | null;
  similarity: number;
};

function formatAgeSince(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const diff = Date.now() - d.getTime();
  if (diff < 0) return "just now";
  const m = 60_000;
  const h = 60 * m;
  const day = 24 * h;
  const wk = 7 * day;
  if (diff < h) return `${Math.max(1, Math.floor(diff / m))}m`;
  if (diff < day) return `${Math.floor(diff / h)}h`;
  if (diff < wk) return `${Math.floor(diff / day)}d`;
  return `${Math.floor(diff / wk)}w`;
}

function articleHref(a: { slug: string | null; id: number }): string {
  return a.slug ? `/articles/${a.slug}` : `/articles/${a.id}`;
}

function sourceLabel(s: string | null | undefined): string {
  if (!s) return "feed";
  return s.length > 28 ? `${s.slice(0, 26)}…` : s;
}

export function ArticlesSearchPanel({
  initialArticles,
}: {
  initialArticles: ArticleGridItem[];
}) {
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [results, setResults] = useState<SemanticSearchItem[]>([]);
  const [hasSearched, setHasSearched] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "/" && document.activeElement?.tagName !== "INPUT") {
        e.preventDefault();
        inputRef.current?.focus();
      }
      if (e.key === "Escape" && document.activeElement === inputRef.current) {
        inputRef.current?.blur();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Warm the HF embedding pod as soon as the user lands on the page so the
  // first real query doesn't pay the cold-start tail.
  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/news/semantic-search/warmup", {
      method: "POST",
      signal: controller.signal,
    }).catch(() => {
      /* fire-and-forget; warmup failure is silent */
    });
    return () => controller.abort();
  }, []);

  async function runSearch() {
    const q = query.trim();
    if (q.length < 3) {
      setHasSearched(true);
      setResults([]);
      setNote("Type at least 3 characters.");
      return;
    }
    setHasSearched(true);
    setLoading(true);
    setNote(null);
    try {
      const r = await fetch("/api/news/semantic-search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: q, limit: 20, lookback_days: 90 }),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data?.error ?? "Search failed");
      setResults((data?.results ?? []) as SemanticSearchItem[]);
      setNote(data?.note ?? null);
    } catch (err) {
      setResults([]);
      setNote(err instanceof Error ? err.message : "Search failed");
    } finally {
      setLoading(false);
    }
  }

  function clearSearch() {
    setQuery("");
    setResults([]);
    setNote(null);
    setHasSearched(false);
    inputRef.current?.focus();
  }

  const dedupedResults = useMemo(() => {
    const seen = new Set<number>();
    return results.filter((r) => {
      if (seen.has(r.article_id)) return false;
      seen.add(r.article_id);
      return true;
    });
  }, [results]);

  const resultCount = hasSearched ? dedupedResults.length : initialArticles.length;

  return (
    <div className="flex flex-col gap-6">
      {/* Command-bar search */}
      <div data-tour="article-filters">
        <div
          className={`relative flex items-center gap-3 rounded-lg border bg-card/40 px-4 transition-colors focus-within:border-amber-500/60 focus-within:bg-card/70 ${
            hasSearched ? "border-amber-500/30" : "border-border"
          }`}
        >
          <span className="font-mono text-xs text-amber-500/80 select-none">~/</span>
          {loading ? (
            <Loader2 className="h-4 w-4 animate-spin text-amber-500" />
          ) : (
            <Search className="h-4 w-4 text-muted-foreground" />
          )}
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                void runSearch();
              }
            }}
            placeholder="Ask the feed — e.g. tariff risk for semiconductor exporters"
            aria-label="Semantic article search"
            className="h-12 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground/70"
          />
          {query && !loading && (
            <button
              type="button"
              onClick={clearSearch}
              aria-label="Clear search"
              className="rounded p-1 text-muted-foreground transition-colors hover:text-foreground"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
          <kbd className="hidden items-center gap-1 rounded border border-border/60 bg-background/60 px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground sm:inline-flex">
            <CornerDownLeft className="h-2.5 w-2.5" />
            Enter
          </kbd>
        </div>
        {note && (
          <p className="mt-2 pl-4 text-xs text-muted-foreground">{note}</p>
        )}
      </div>

      {/* Mode strip */}
      <div className="flex items-center justify-between border-b border-border/60 pb-3">
        <div className="flex items-center gap-2 text-xs">
          {hasSearched ? (
            <Sparkles className="h-3 w-3 text-amber-500" />
          ) : (
            <Newspaper className="h-3 w-3 text-muted-foreground" />
          )}
          <span className="font-mono uppercase tracking-[0.2em] text-muted-foreground">
            {hasSearched ? "Semantic Query" : "Latest Feed"}
          </span>
          <span className="text-muted-foreground/40">/</span>
          <span className="text-muted-foreground">
            <span className="font-mono tabular-nums text-foreground">
              {String(resultCount).padStart(2, "0")}
            </span>{" "}
            {hasSearched ? "matches" : "stories"}
          </span>
        </div>
        {hasSearched && (
          <button
            type="button"
            onClick={clearSearch}
            className="text-xs text-muted-foreground transition-colors hover:text-amber-400"
          >
            Back to feed
          </button>
        )}
      </div>

      {/* Body */}
      {loading ? (
        <EditorialSkeleton mode={hasSearched ? "query" : "feed"} />
      ) : hasSearched ? (
        <QueryResults results={dedupedResults} query={query} />
      ) : (
        <EditorialFeed articles={initialArticles} />
      )}
    </div>
  );
}

/* ------------------------------- Feed mode ------------------------------- */

function EditorialFeed({ articles }: { articles: ArticleGridItem[] }) {
  if (articles.length === 0) {
    return (
      <EmptyState
        title="The feed is quiet."
        body="No articles have been ingested yet. Check back after the next pipeline run."
      />
    );
  }

  const [hero, ...rest] = articles;
  const featured = rest.slice(0, 2);
  const compact = rest.slice(2);

  return (
    <div data-tour="article-list" className="flex flex-col gap-10">
      <HeroArticle article={hero} />
      {featured.length > 0 && (
        <div className="grid gap-6 md:grid-cols-2">
          {featured.map((a) => (
            <FeaturedArticle key={a.id} article={a} />
          ))}
        </div>
      )}
      {compact.length > 0 && <CompactList articles={compact} />}
    </div>
  );
}

function HeroArticle({ article }: { article: ArticleGridItem }) {
  const age = formatAgeSince(article.published_at ?? article.created_at);
  return (
    <article className="group grid gap-6 md:grid-cols-12 md:gap-8">
      <Link
        href={articleHref(article)}
        className="relative col-span-12 block aspect-[16/9] overflow-hidden rounded-md bg-muted md:col-span-7 md:aspect-[4/3]"
      >
        {article.image_url ? (
          <img
            src={article.image_url}
            alt=""
            loading="eager"
            className="h-full w-full object-cover transition-transform duration-500 ease-out group-hover:scale-[1.02]"
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center">
            <Newspaper className="h-8 w-8 text-muted-foreground/40" />
          </div>
        )}
        <div className="pointer-events-none absolute inset-0 bg-gradient-to-tr from-black/30 via-transparent to-transparent" />
        <div className="absolute left-4 top-4 inline-flex items-center gap-2 rounded-sm bg-background/70 px-2 py-1 font-mono text-[10px] uppercase tracking-[0.2em] text-amber-500 backdrop-blur">
          <span className="h-1 w-1 rounded-full bg-amber-500" />
          Lead
        </div>
      </Link>

      <div className="col-span-12 flex flex-col justify-between md:col-span-5">
        <div>
          <p className="mb-3 inline-flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.2em] text-amber-500/80">
            <span className="h-px w-6 bg-amber-500/60" />
            {sourceLabel(article.source)}
          </p>
          <Link
            href={articleHref(article)}
            className="block text-2xl font-bold leading-[1.1] tracking-tight transition-colors hover:text-amber-400 md:text-4xl"
          >
            {article.title || article.url || "Untitled article"}
          </Link>
        </div>
        <div className="mt-6 flex items-center justify-between border-t border-border/60 pt-4 text-xs text-muted-foreground">
          <span className="font-mono tabular-nums">{age} ago</span>
          <Link
            href={articleHref(article)}
            className="inline-flex items-center gap-1 transition-colors hover:text-amber-400"
          >
            Read story <ArrowUpRight className="h-3.5 w-3.5" />
          </Link>
        </div>
      </div>
    </article>
  );
}

function FeaturedArticle({ article }: { article: ArticleGridItem }) {
  const age = formatAgeSince(article.published_at ?? article.created_at);
  return (
    <article className="group flex flex-col gap-3">
      <Link
        href={articleHref(article)}
        className="relative block aspect-[16/10] overflow-hidden rounded-md bg-muted"
      >
        {article.image_url ? (
          <img
            src={article.image_url}
            alt=""
            loading="lazy"
            className="h-full w-full object-cover transition-transform duration-500 ease-out group-hover:scale-[1.02]"
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center">
            <Newspaper className="h-6 w-6 text-muted-foreground/40" />
          </div>
        )}
      </Link>
      <div>
        <p className="mb-1.5 font-mono text-[10px] uppercase tracking-[0.2em] text-amber-500/80">
          {sourceLabel(article.source)}
        </p>
        <Link
          href={articleHref(article)}
          className="line-clamp-3 text-base font-semibold leading-snug tracking-tight transition-colors hover:text-amber-400"
        >
          {article.title || article.url || "Untitled article"}
        </Link>
        <p className="mt-2 font-mono text-[11px] tabular-nums text-muted-foreground">
          {age} ago
        </p>
      </div>
    </article>
  );
}

function CompactList({ articles }: { articles: ArticleGridItem[] }) {
  return (
    <div>
      <div className="mb-4 flex items-center gap-3">
        <span className="font-mono text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
          The rest
        </span>
        <span className="h-px flex-1 bg-border/60" />
        <span className="font-mono text-[10px] tabular-nums text-muted-foreground">
          {String(articles.length).padStart(2, "0")}
        </span>
      </div>
      <ul className="divide-y divide-border/60">
        {articles.map((a) => {
          const age = formatAgeSince(a.published_at ?? a.created_at);
          return (
            <li key={a.id} className="group">
              <Link
                href={articleHref(a)}
                className="grid grid-cols-[64px_1fr_auto] items-center gap-4 py-3 sm:grid-cols-[88px_1fr_auto] sm:gap-5"
              >
                <div className="relative aspect-[4/3] overflow-hidden rounded-sm bg-muted">
                  {a.image_url ? (
                    <img
                      src={a.image_url}
                      alt=""
                      loading="lazy"
                      className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-[1.04]"
                    />
                  ) : (
                    <div className="flex h-full w-full items-center justify-center">
                      <Newspaper className="h-3 w-3 text-muted-foreground/40" />
                    </div>
                  )}
                </div>
                <div className="min-w-0">
                  <p className="mb-1 truncate font-mono text-[10px] uppercase tracking-[0.15em] text-amber-500/70">
                    {sourceLabel(a.source)}
                  </p>
                  <p className="line-clamp-2 text-sm font-medium leading-snug transition-colors group-hover:text-amber-400">
                    {a.title || a.url || "Untitled article"}
                  </p>
                </div>
                <span className="self-start whitespace-nowrap font-mono text-[11px] tabular-nums text-muted-foreground">
                  {age}
                </span>
              </Link>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/* ------------------------------- Query mode ------------------------------ */

function QueryResults({
  results,
  query,
}: {
  results: SemanticSearchItem[];
  query: string;
}) {
  if (results.length === 0) {
    return (
      <EmptyState
        title={`No semantic matches for "${query.trim()}"`}
        body="Try a broader phrase, fewer constraints, or a different timeframe. Lookback is 90 days."
      />
    );
  }

  return (
    <ol data-tour="article-list" className="divide-y divide-border/60">
      {results.map((r, i) => (
        <QueryResultRow key={r.article_id} item={r} rank={i + 1} />
      ))}
    </ol>
  );
}

function QueryResultRow({
  item,
  rank,
}: {
  item: SemanticSearchItem;
  rank: number;
}) {
  const href = item.slug
    ? `/articles/${item.slug}`
    : `/articles/${item.article_id}`;
  const age = formatAgeSince(item.published_at);
  const pct = Math.max(0, Math.min(1, item.similarity ?? 0));
  const pctLabel = `${Math.round(pct * 100)}%`;
  const src = sourceLabel(item.source ?? item.article_stream);

  return (
    <li className="group py-5">
      <Link
        href={href}
        className="grid grid-cols-[auto_1fr] gap-4 sm:grid-cols-[auto_1fr_120px] sm:gap-6"
      >
        <span className="pt-1 font-mono text-xs tabular-nums text-muted-foreground">
          {String(rank).padStart(2, "0")}
        </span>
        <div className="min-w-0">
          <div className="mb-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[10px] uppercase tracking-[0.15em]">
            <span className="text-amber-500/80">{src}</span>
            <span className="text-muted-foreground/40">·</span>
            <span className="text-muted-foreground tabular-nums normal-case tracking-normal">
              {age} ago
            </span>
            <span className="text-muted-foreground/40">·</span>
            <span className="inline-flex items-center gap-1.5 normal-case tracking-normal text-muted-foreground">
              <span
                className="inline-block h-1.5 w-1.5 rounded-full"
                style={{
                  background: `hsl(${Math.round(38 + pct * 0)}, 92%, ${Math.round(
                    50 - (1 - pct) * 15,
                  )}%)`,
                }}
                aria-hidden
              />
              <span className="font-mono tabular-nums text-foreground">{pctLabel}</span>
              <span>match</span>
            </span>
          </div>
          <p className="text-base font-semibold leading-snug tracking-tight transition-colors group-hover:text-amber-400 sm:text-lg">
            {item.title || item.url || "Untitled article"}
          </p>
          {item.snippet && (
            <p className="mt-2 line-clamp-2 max-w-[68ch] text-sm leading-relaxed text-muted-foreground">
              {item.snippet}
            </p>
          )}
          <SimilarityBar value={pct} className="mt-3 sm:hidden" />
        </div>
        <div className="hidden flex-col items-end gap-3 sm:flex">
          {item.image_url ? (
            <div className="relative h-16 w-[120px] overflow-hidden rounded-sm bg-muted">
              <img
                src={item.image_url}
                alt=""
                loading="lazy"
                className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-[1.04]"
              />
            </div>
          ) : (
            <div className="flex h-16 w-[120px] items-center justify-center rounded-sm bg-muted/40">
              <Newspaper className="h-4 w-4 text-muted-foreground/40" />
            </div>
          )}
          <SimilarityBar value={pct} className="w-[120px]" />
        </div>
      </Link>
    </li>
  );
}

function SimilarityBar({
  value,
  className = "",
}: {
  value: number;
  className?: string;
}) {
  return (
    <div
      className={`relative h-[2px] w-full overflow-hidden rounded-full bg-border/60 ${className}`}
      aria-hidden
    >
      <div
        className="absolute inset-y-0 left-0 bg-amber-500/80"
        style={{ width: `${Math.max(2, Math.round(value * 100))}%` }}
      />
    </div>
  );
}

/* ------------------------------ Empty + skel ----------------------------- */

function EmptyState({ title, body }: { title: string; body: string }) {
  return (
    <div className="flex flex-col items-start gap-3 border-l-2 border-amber-500/40 py-8 pl-6">
      <Newspaper className="h-5 w-5 text-amber-500/70" />
      <h3 className="text-lg font-semibold tracking-tight">{title}</h3>
      <p className="max-w-[55ch] text-sm leading-relaxed text-muted-foreground">
        {body}
      </p>
    </div>
  );
}

export function EditorialSkeleton({
  mode = "feed",
}: {
  mode?: "feed" | "query";
}) {
  if (mode === "query") {
    return (
      <div className="divide-y divide-border/60">
        {[0, 1, 2, 3, 4].map((i) => (
          <div
            key={i}
            className="grid animate-pulse grid-cols-[auto_1fr_120px] gap-6 py-5"
          >
            <div className="h-3 w-6 rounded bg-muted" />
            <div className="space-y-2">
              <div className="h-3 w-28 rounded bg-muted" />
              <div className="h-4 w-4/5 rounded bg-muted" />
              <div className="h-3 w-3/5 rounded bg-muted" />
            </div>
            <div className="h-16 w-[120px] rounded-sm bg-muted" />
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-10">
      <div className="grid animate-pulse gap-6 md:grid-cols-12 md:gap-8">
        <div className="col-span-12 aspect-[16/9] rounded-md bg-muted md:col-span-7 md:aspect-[4/3]" />
        <div className="col-span-12 space-y-4 md:col-span-5">
          <div className="h-3 w-20 rounded bg-muted" />
          <div className="h-8 w-full rounded bg-muted" />
          <div className="h-8 w-3/4 rounded bg-muted" />
          <div className="h-3 w-24 rounded bg-muted" />
        </div>
      </div>
      <div className="grid animate-pulse gap-6 md:grid-cols-2">
        {[0, 1].map((i) => (
          <div key={i} className="space-y-3">
            <div className="aspect-[16/10] rounded-md bg-muted" />
            <div className="h-4 w-4/5 rounded bg-muted" />
            <div className="h-3 w-1/3 rounded bg-muted" />
          </div>
        ))}
      </div>
      <ul className="divide-y divide-border/60">
        {[0, 1, 2, 3].map((i) => (
          <li
            key={i}
            className="grid animate-pulse grid-cols-[88px_1fr_auto] items-center gap-5 py-3"
          >
            <div className="aspect-[4/3] rounded-sm bg-muted" />
            <div className="space-y-2">
              <div className="h-3 w-24 rounded bg-muted" />
              <div className="h-4 w-3/4 rounded bg-muted" />
            </div>
            <div className="h-3 w-8 rounded bg-muted" />
          </li>
        ))}
      </ul>
    </div>
  );
}
