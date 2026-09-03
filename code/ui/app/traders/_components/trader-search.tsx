"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { ArrowUpRight, Search } from "lucide-react";
import type { TraderPreview } from "@/lib/sanity/types";

/**
 * The lookup half of the directory.
 *
 * Client-side rather than a round trip: the whole roster is a few dozen rows at
 * most, so filtering in the browser is instant and works with no network. If
 * this ever grows past a few hundred people it should move server-side — the
 * cutover point is when the payload stops being smaller than the page's JS.
 */

const TAG_LABEL: Record<string, string> = {
  value: "Value",
  growth: "Growth",
  momentum: "Momentum",
  quant: "Quant",
  macro: "Macro",
  contrarian: "Contrarian",
  index: "Index",
  technical: "Technical",
  news: "News-driven",
  social: "Social arbitrage",
  academic: "Academic",
};

export function TraderSearch({ traders }: { traders: TraderPreview[] }) {
  const [query, setQuery] = useState("");
  const [tag, setTag] = useState<string | null>(null);

  const tags = useMemo(() => {
    const counts = new Map<string, number>();
    for (const t of traders)
      for (const g of t.tags ?? []) counts.set(g, (counts.get(g) ?? 0) + 1);
    return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  }, [traders]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return traders.filter((t) => {
      if (tag && !(t.tags ?? []).includes(tag)) return false;
      if (!q) return true;
      return [t.name, t.knownFor, t.style, t.summary, ...(t.tags ?? [])]
        .filter(Boolean)
        .some((v) => String(v).toLowerCase().includes(q));
    });
  }, [traders, query, tag]);

  return (
    <>
      <div className="flex flex-wrap items-center gap-3">
        <label className="relative flex-1 basis-64">
          <span className="sr-only">Search traders</span>
          <Search
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden
          />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search by name, style or idea…"
            className="w-full rounded-lg border bg-background py-2 pl-9 pr-3 text-sm outline-none transition-colors placeholder:text-muted-foreground focus-visible:border-amber-500/60 focus-visible:ring-2 focus-visible:ring-amber-500/30"
          />
        </label>
        <p className="font-mono text-xs tabular-nums text-muted-foreground">
          {filtered.length} of {traders.length}
        </p>
      </div>

      {tags.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {tags.map(([g, n]) => {
            const active = tag === g;
            return (
              <button
                key={g}
                type="button"
                onClick={() => setTag(active ? null : g)}
                aria-pressed={active}
                className={`rounded-full border px-2.5 py-0.5 font-mono text-[11px] transition-colors ${
                  active
                    ? "border-amber-600/60 bg-amber-600/10 text-amber-700 dark:text-amber-500"
                    : "text-muted-foreground hover:border-foreground/30 hover:text-foreground"
                }`}
              >
                {TAG_LABEL[g] ?? g}
                <span className="ml-1.5 opacity-60">{n}</span>
              </button>
            );
          })}
        </div>
      )}

      {filtered.length === 0 ? (
        <p className="mt-8 text-sm text-muted-foreground">
          Nothing matches “{query}”.
        </p>
      ) : (
        <ul className="mt-6 grid gap-2">
          {filtered.map((t, i) => (
            <li
              key={t.slug}
              className="animate-screening-row-in"
              style={{ animationDelay: `${Math.min(i, 12) * 30}ms` }}
            >
              <Link
                href={`/traders/${t.slug}`}
                className="group block border-l-2 border-l-border py-4 pl-5 transition-colors hover:border-l-amber-500 hover:bg-muted/50 focus-visible:border-l-amber-500 focus-visible:bg-muted/50 focus-visible:outline-none"
              >
                <div className="flex flex-wrap items-baseline gap-x-3 font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
                  {t.style && <span>{t.style}</span>}
                  {t.lifespan && (
                    <span className="tabular-nums opacity-70">{t.lifespan}</span>
                  )}
                  {t.arenaAgentSlug && (
                    <span className="text-amber-600 dark:text-amber-500">
                      in the arena
                    </span>
                  )}
                </div>
                <h2 className="mt-1.5 flex items-start gap-1.5 text-lg font-semibold leading-snug tracking-tight transition-colors group-hover:text-amber-600 dark:group-hover:text-amber-500">
                  {t.name}
                  <ArrowUpRight
                    className="mt-1 h-4 w-4 shrink-0 opacity-0 transition-opacity group-hover:opacity-100"
                    aria-hidden
                  />
                </h2>
                {(t.summary || t.knownFor) && (
                  <p className="mt-1 line-clamp-2 max-w-[68ch] text-sm leading-relaxed text-muted-foreground">
                    {t.summary || t.knownFor}
                  </p>
                )}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
