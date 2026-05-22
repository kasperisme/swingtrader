"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import {
  ArrowUpRight,
  Loader2,
  Newspaper,
  Search,
  Sparkles,
  Hash,
} from "lucide-react";
import { normalizeSearchTag } from "@/lib/news/search-tags";

type ArticleItem = {
  article_id: number;
  title: string | null;
  url: string | null;
  source: string | null;
  slug: string | null;
  image_url: string | null;
  published_at: string | null;
  snippet: string | null;
};

type SearchMode = "tags" | "semantic";

function formatAge(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const diff = Date.now() - d.getTime();
  if (diff < 0) return "now";
  const m = 60_000;
  const h = 60 * m;
  const day = 24 * h;
  const wk = 7 * day;
  if (diff < h) return `${Math.max(1, Math.floor(diff / m))}m`;
  if (diff < day) return `${Math.floor(diff / h)}h`;
  if (diff < wk) return `${Math.floor(diff / day)}d`;
  return `${Math.floor(diff / wk)}w`;
}

function articleHref(a: { slug: string | null; article_id: number }): string {
  return a.slug ? `/articles/${a.slug}` : `/articles/${a.article_id}`;
}

/**
 * Per-ticker articles list. Hits the same `/api/news/semantic-search`
 * endpoint the public articles page uses, with the ticker symbol passed as
 * a tag. Users can refine the search within the ticker via the input
 * (defaults to "tags" mode, can switch to "semantic" for natural-language
 * queries scoped to the same ticker).
 */
export function ScreeningsArticlesView({
  selectedTicker,
}: {
  selectedTicker: string | null;
}) {
  const symbol = selectedTicker?.trim().toUpperCase() ?? "";
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<SearchMode>("tags");
  const [items, setItems] = useState<ArticleItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const lastSymbolRef = useRef<string>("");

  const fetchArticles = useMemo(() => {
    return async (sym: string, q: string, m: SearchMode) => {
      if (!sym) return;
      const normalizedSym = normalizeSearchTag(sym);
      const trimmed = q.trim();
      const isRefining = trimmed.length > 0;
      // Tag mode: always include the ticker as a tag, plus any user-typed tag.
      // Semantic mode: pass the ticker as a constraint tag with the natural
      // language query body.
      const tags: string[] = [normalizedSym];
      if (m === "tags" && isRefining) {
        tags.push(normalizeSearchTag(trimmed));
      }
      const queryBody =
        m === "semantic" && isRefining
          ? trimmed
          : `${normalizedSym}${isRefining ? ` ${trimmed}` : ""}`;

      setLoading(true);
      setError(null);
      setNote(null);
      try {
        const r = await fetch("/api/news/semantic-search", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            query: queryBody,
            tags,
            limit: 25,
            lookback_days: 90,
            mode: m,
          }),
        });
        const data = await r.json();
        if (!r.ok) throw new Error(data?.error ?? "Search failed");
        setItems((data?.results ?? []) as ArticleItem[]);
        setNote((data?.note ?? null) as string | null);
      } catch (err) {
        setItems([]);
        setError(err instanceof Error ? err.message : "Search failed");
      } finally {
        setLoading(false);
      }
    };
  }, []);

  // Auto-fetch on ticker change. Reset the refinement input so we always
  // start from "all articles for this ticker".
  useEffect(() => {
    if (!symbol) {
      setItems([]);
      return;
    }
    if (lastSymbolRef.current !== symbol) {
      setQuery("");
      lastSymbolRef.current = symbol;
    }
    void fetchArticles(symbol, "", mode);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol]);

  if (!symbol) {
    return (
      <div className="p-6 text-center text-sm text-muted-foreground">
        Select a ticker from the sidebar to see related news.
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* Refinement command bar — same shape as the public articles page. */}
      <div className="shrink-0 border-b border-border bg-background px-3 py-2">
        <div className="flex items-center gap-2 rounded-lg border border-border bg-card/40 px-3 focus-within:border-amber-500/60 focus-within:bg-card/70">
          <span className="font-mono text-[11px] text-amber-500/80 select-none">
            ~/{symbol.toLowerCase()}/
          </span>
          {loading ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin text-amber-500" />
          ) : (
            <Search className="h-3.5 w-3.5 text-muted-foreground" />
          )}
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                void fetchArticles(symbol, query, mode);
              }
            }}
            placeholder={
              mode === "tags"
                ? `Refine ${symbol} by tag — earnings, lawsuit, AI…`
                : `Ask the feed — e.g. supply-chain risk for ${symbol}`
            }
            className="h-9 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground/70"
            aria-label={`Refine articles for ${symbol}`}
          />
        </div>
        <div className="mt-1.5 flex items-center gap-1.5 pl-1">
          <ModeButton
            active={mode === "tags"}
            label="Tags"
            icon={<Hash className="h-3 w-3" />}
            onClick={() => {
              setMode("tags");
              void fetchArticles(symbol, query, "tags");
            }}
          />
          <ModeButton
            active={mode === "semantic"}
            label="Semantic"
            icon={<Sparkles className="h-3 w-3" />}
            onClick={() => {
              setMode("semantic");
              void fetchArticles(symbol, query, "semantic");
            }}
          />
          {note && (
            <span className="ml-auto text-[10px] text-muted-foreground">
              {note}
            </span>
          )}
        </div>
      </div>

      {/* Results list. Empty / error / loading states render in-place. */}
      <div className="flex-1 min-h-0 overflow-y-auto">
        {error ? (
          <p className="px-3 py-8 text-center text-sm text-rose-500">
            {error}
          </p>
        ) : loading && items.length === 0 ? (
          <div className="flex items-center justify-center gap-2 px-3 py-8 text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            <span className="text-sm">Loading articles for {symbol}…</span>
          </div>
        ) : items.length === 0 ? (
          <p className="px-3 py-8 text-center text-sm text-muted-foreground">
            No recent articles tagged{" "}
            <span className="font-mono text-foreground">{symbol}</span>.
          </p>
        ) : (
          <ul className="divide-y divide-border">
            {items.map((item) => (
              <li key={item.article_id}>
                <Link
                  href={articleHref(item)}
                  className="group flex flex-col gap-1.5 px-3 py-3 transition-colors hover:bg-muted/30"
                >
                  <div className="flex items-start justify-between gap-2">
                    <h4 className="text-sm font-medium leading-snug text-foreground/95">
                      {item.title || "Untitled"}
                    </h4>
                    <ArrowUpRight className="h-3 w-3 shrink-0 text-muted-foreground/40 transition-colors group-hover:text-foreground" />
                  </div>
                  {item.snippet ? (
                    <p className="line-clamp-2 text-xs text-muted-foreground">
                      {item.snippet}
                    </p>
                  ) : null}
                  <div className="flex items-center gap-2 text-[10px] font-mono uppercase tracking-[0.1em] text-muted-foreground">
                    <Newspaper className="h-2.5 w-2.5" />
                    <span className="truncate">
                      {item.source || "feed"}
                    </span>
                    <span className="text-muted-foreground/40">·</span>
                    <span>{formatAge(item.published_at)}</span>
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function ModeButton({
  active,
  label,
  icon,
  onClick,
}: {
  active: boolean;
  label: string;
  icon: React.ReactNode;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-mono uppercase tracking-[0.1em] transition-colors ${
        active
          ? "border-amber-500/40 bg-amber-500/10 text-amber-600 dark:text-amber-400"
          : "border-border text-muted-foreground hover:text-foreground"
      }`}
    >
      {icon}
      {label}
    </button>
  );
}
