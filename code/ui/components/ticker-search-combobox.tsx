"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Loader2 } from "lucide-react";
import { fmpSearchSymbol } from "@/app/actions/fmp";

type Props = {
  value: string;
  onChange: (value: string) => void;
  onSubmit?: () => void;
  options: string[];
  placeholder?: string;
  className?: string;
};

type FmpSymbolHit = {
  symbol: string;
  name?: string;
  currency?: string;
  stockExchange?: string;
  exchangeShortName?: string;
};

function isFmpSymbolHit(v: unknown): v is FmpSymbolHit {
  if (typeof v !== "object" || v === null) return false;
  const s = (v as { symbol?: unknown }).symbol;
  return typeof s === "string" && s.length > 0;
}

const SEARCH_DEBOUNCE_MS = 400;
const MAX_FMP_HITS = 20;
const MAX_LOCAL_EXTRA = 12;
const MAX_TOTAL_ROWS = 28;
/** FMP `search-symbol` max query length (see `fmp.ts`). */
const MAX_QUERY_LEN = 80;

type DisplayRow =
  | { kind: "fmp"; hit: FmpSymbolHit }
  | { kind: "local"; symbol: string };

export function TickerSearchCombobox({
  value,
  onChange,
  onSubmit,
  options,
  placeholder = "Search ticker or company…",
  className = "",
}: Props) {
  const [open, setOpen] = useState(false);
  const [fmpHits, setFmpHits] = useState<FmpSymbolHit[]>([]);
  const [fmpLoading, setFmpLoading] = useState(false);
  const [fmpHint, setFmpHint] = useState<string | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reqIdRef = useRef(0);

  const trimmed = value.trim();

  const localSuggestions = useMemo(() => {
    const q = value.trim().toUpperCase();
    const unique = Array.from(
      new Set(
        options.map((o) => o.trim().toUpperCase()).filter(Boolean),
      ),
    ).sort((a, b) => a.localeCompare(b));
    if (!q) return unique.slice(0, 20);
    const starts = unique.filter((s) => s.startsWith(q));
    const contains = unique.filter((s) => !s.startsWith(q) && s.includes(q));
    return [...starts, ...contains].slice(0, 20);
  }, [options, value]);

  const displayRows = useMemo((): DisplayRow[] => {
    if (!trimmed) {
      return localSuggestions.map((symbol) => ({ kind: "local", symbol }));
    }
    const seen = new Set<string>();
    const out: DisplayRow[] = [];
    for (const h of fmpHits) {
      const sym = h.symbol.trim().toUpperCase();
      if (!sym || seen.has(sym)) continue;
      seen.add(sym);
      out.push({ kind: "fmp", hit: h });
      if (out.length >= MAX_FMP_HITS) break;
    }
    const localCap =
      fmpHits.length > 0 ? MAX_LOCAL_EXTRA : Math.min(25, MAX_TOTAL_ROWS);
    let localAdded = 0;
    for (const s of localSuggestions) {
      if (seen.has(s)) continue;
      seen.add(s);
      out.push({ kind: "local", symbol: s });
      localAdded++;
      if (localAdded >= localCap || out.length >= MAX_TOTAL_ROWS) break;
    }
    return out;
  }, [trimmed, fmpHits, localSuggestions]);

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (trimmed.length < 1) {
      setFmpHits([]);
      setFmpHint(null);
      setFmpLoading(false);
      return;
    }
    if (trimmed.length > MAX_QUERY_LEN) {
      setFmpHits([]);
      setFmpHint("Query too long");
      setFmpLoading(false);
      return;
    }

    setFmpHits([]);
    setFmpHint(null);

    debounceRef.current = setTimeout(() => {
      const id = ++reqIdRef.current;
      setFmpLoading(true);
      setFmpHint(null);
      void (async () => {
        try {
          const res = await fmpSearchSymbol(trimmed);
          if (id !== reqIdRef.current) return;
          if (!res.ok) {
            setFmpHits([]);
            setFmpHint(res.error);
            return;
          }
          const parsed = (res.data as unknown[])
            .filter(isFmpSymbolHit)
            .map((h) => ({
              ...h,
              symbol: h.symbol.trim(),
            }))
            .slice(0, MAX_FMP_HITS);
          setFmpHits(parsed);
          setFmpHint(null);
        } catch {
          if (id !== reqIdRef.current) return;
          setFmpHits([]);
          setFmpHint("Network error");
        } finally {
          if (id === reqIdRef.current) setFmpLoading(false);
        }
      })();
    }, SEARCH_DEBOUNCE_MS);

    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [trimmed]);

  function pick(ticker: string) {
    onChange(ticker.trim().toUpperCase());
    setOpen(false);
  }

  const showDropdown =
    open &&
    (displayRows.length > 0 ||
      fmpLoading ||
      (Boolean(fmpHint) && trimmed.length > 0));

  return (
    <div className={`relative ${className}`}>
      <input
        value={value}
        onChange={(e) => {
          onChange(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => {
          setTimeout(() => setOpen(false), 120);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            onSubmit?.();
            setOpen(false);
          }
        }}
        placeholder={placeholder}
        autoComplete="off"
        className="h-9 w-full rounded-md border border-input bg-background px-3 pr-9 text-sm"
      />
      {fmpLoading && trimmed.length > 0 ? (
        <div className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
        </div>
      ) : null}
      {showDropdown ? (
        <div
          className="absolute z-20 mt-1 max-h-56 w-full overflow-auto rounded-md border border-border bg-popover p-1 shadow-lg"
          onMouseDown={(e) => e.preventDefault()}
        >
          {fmpLoading && displayRows.length === 0 ? (
            <p className="px-2 py-2 text-xs text-muted-foreground">Searching…</p>
          ) : null}
          {displayRows.map((row, i) =>
            row.kind === "fmp" ? (
              <button
                key={`fmp-${row.hit.symbol}-${i}`}
                type="button"
                onMouseDown={(e) => {
                  e.preventDefault();
                  pick(row.hit.symbol);
                }}
                className="flex w-full flex-col gap-0.5 rounded px-2 py-1.5 text-left hover:bg-muted"
              >
                <span className="text-xs font-mono font-semibold">
                  {row.hit.symbol}
                </span>
                {row.hit.name ? (
                  <span className="line-clamp-2 text-[11px] text-muted-foreground">
                    {row.hit.name}
                  </span>
                ) : null}
                {(row.hit.exchangeShortName || row.hit.stockExchange) ? (
                  <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
                    {row.hit.exchangeShortName ?? row.hit.stockExchange}
                    {row.hit.currency ? ` · ${row.hit.currency}` : ""}
                  </span>
                ) : null}
              </button>
            ) : (
              <button
                key={`loc-${row.symbol}-${i}`}
                type="button"
                onMouseDown={(e) => {
                  e.preventDefault();
                  pick(row.symbol);
                }}
                className="block w-full rounded px-2 py-1.5 text-left text-xs font-mono hover:bg-muted"
              >
                {row.symbol}
              </button>
            ),
          )}
          {fmpHint && displayRows.length === 0 && !fmpLoading ? (
            <p className="px-2 py-2 text-xs text-muted-foreground">{fmpHint}</p>
          ) : null}
          {fmpHint && displayRows.length > 0 ? (
            <p className="border-t border-border px-2 py-1.5 text-[10px] text-muted-foreground">
              {fmpHint}
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
