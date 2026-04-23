"use client";

import { useMemo, useState } from "react";
import { Search } from "lucide-react";
import { ArticlesGrid, type ArticleGridItem } from "@/components/articles-grid";

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

export function ArticlesSearchPanel({ initialArticles }: { initialArticles: ArticleGridItem[] }) {
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [results, setResults] = useState<SemanticSearchItem[]>([]);
  const [hasSearched, setHasSearched] = useState(false);

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

  const gridArticles = useMemo<ArticleGridItem[]>(() => {
    if (!hasSearched) return initialArticles;
    if (!results.length) return [];
    const seen = new Set<number>();
    return results.filter((r) => {
      if (seen.has(r.article_id)) return false;
      seen.add(r.article_id);
      return true;
    }).map((r) => ({
      id: r.article_id,
      slug: r.slug ?? null,
      title: r.title ?? null,
      url: r.url ?? null,
      image_url: r.image_url ?? null,
      source: r.source ?? r.article_stream ?? null,
      published_at: r.published_at ?? null,
      created_at: r.published_at ?? new Date().toISOString(),
    }));
  }, [hasSearched, initialArticles, results]);

  const resultLabel = hasSearched
    ? `${gridArticles.length} semantic result${gridArticles.length === 1 ? "" : "s"}`
    : `${initialArticles.length} latest article${initialArticles.length === 1 ? "" : "s"}`;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end gap-2">
        <div className="flex min-w-[260px] flex-1 flex-col gap-1.5">
          <span className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Search</span>
          <div className="relative min-w-[260px] flex-1">
            <Search className="pointer-events-none absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  void runSearch();
                }
              }}
              placeholder="Search articles semantically (e.g. tariff risk for semis)"
              className="w-full rounded-md border border-border bg-background py-2 pl-8 pr-2 text-sm"
            />
          </div>
        </div>
        <button
          type="button"
          onClick={() => void runSearch()}
          disabled={loading}
          className="rounded-md border border-border px-3 py-2 text-xs font-medium text-muted-foreground hover:text-foreground disabled:opacity-60"
        >
          {loading ? "Searching..." : "Search"}
        </button>
        {results.length > 0 && (
          <>
            <button
              type="button"
              onClick={() => {
                setQuery("");
                setResults([]);
                setNote(null);
                setHasSearched(false);
              }}
              className="rounded-md border border-border px-3 py-2 text-xs font-medium text-muted-foreground hover:text-foreground"
            >
              Clear
            </button>
          </>
        )}
        {note && <p className="w-full pt-1 text-xs text-muted-foreground">{note}</p>}
      </div>

      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <p>{resultLabel}</p>
        <p className="uppercase tracking-wide">{hasSearched ? "Query mode" : "Feed mode"}</p>
      </div>

      <ArticlesGrid articles={gridArticles} />
    </div>
  );
}
