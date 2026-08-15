"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { AlertCircle, Briefcase, Loader2, Plus, Sparkles, Trash2 } from "lucide-react";
import { buildPortfolioFromTrades, type PortfolioPosition } from "./portfolio-from-trades";
import { closingTradeIdSet } from "@/lib/trades/closed-positions";
import { fmpGetPriceAtDate, fmpGetQuote, fmpSearchSymbol } from "@/app/actions/fmp";
import { track } from "@/lib/analytics/events";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

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

/** Wait for typing / picker to settle before hitting FMP search. */
const SEARCH_DEBOUNCE_MS = 600;
const MIN_SEARCH_CHARS = 1;
const MAX_SUGGESTIONS = 25;
/** Wait after ticker + execution time change before loading a price. */
const AUTO_PRICE_DEBOUNCE_MS = 800;

function localCalendarDateFromDatetimeLocal(value: string): string | null {
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return null;
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function formatPriceForInput(n: number): string {
  if (!Number.isFinite(n)) return "";
  const rounded = Math.round(n * 1_000_000) / 1_000_000;
  return String(rounded);
}

function TickerSearchInput(props: {
  value: string;
  onChangeTicker: (t: string) => void;
  onPickCurrency?: (ccy: string) => void;
}) {
  const { value, onChangeTicker, onPickCurrency } = props;
  const listId = useId();
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [hits, setHits] = useState<FmpSymbolHit[]>([]);
  const [hint, setHint] = useState<string | null>(null);
  const blurClose = useRef<ReturnType<typeof setTimeout> | null>(null);
  const debounce = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reqId = useRef(0);

  const runSearch = useCallback(async (q: string) => {
    const trimmed = q.trim();
    if (trimmed.length < MIN_SEARCH_CHARS) {
      setHits([]);
      setHint(null);
      setLoading(false);
      return;
    }
    const id = ++reqId.current;
    setLoading(true);
    setHint(null);
    try {
      const res = await fmpSearchSymbol(trimmed);
      if (id !== reqId.current) return;
      if (!res.ok) {
        setHits([]);
        setHint(res.error);
        return;
      }
      const body = res.data;
      const parsed = body.filter(isFmpSymbolHit).slice(0, MAX_SUGGESTIONS);
      setHits(parsed);
      setHint(parsed.length === 0 ? "No matches" : null);
    } catch {
      if (id !== reqId.current) return;
      setHits([]);
      setHint("Network error");
    } finally {
      if (id === reqId.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (debounce.current) clearTimeout(debounce.current);
    debounce.current = setTimeout(() => {
      void runSearch(value);
    }, SEARCH_DEBOUNCE_MS);
    return () => {
      if (debounce.current) clearTimeout(debounce.current);
    };
  }, [value, runSearch]);

  function scheduleBlurClose() {
    if (blurClose.current) clearTimeout(blurClose.current);
    blurClose.current = setTimeout(() => setOpen(false), 180);
  }

  function cancelBlurClose() {
    if (blurClose.current) {
      clearTimeout(blurClose.current);
      blurClose.current = null;
    }
  }

  function pick(hit: FmpSymbolHit) {
    onChangeTicker(hit.symbol);
    if (hit.currency?.trim() && onPickCurrency) {
      onPickCurrency(hit.currency.trim().toUpperCase());
    }
    setOpen(false);
    setHits([]);
  }

  return (
    <div className="relative">
      <input
        value={value}
        onChange={(e) => {
          onChangeTicker(e.target.value);
          setOpen(true);
        }}
        onFocus={() => {
          cancelBlurClose();
          setOpen(true);
        }}
        onBlur={() => scheduleBlurClose()}
        placeholder="Search name or ticker (FMP)"
        className="min-h-11 w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-sm focus:outline-none focus:ring-1 focus:ring-ring"
        autoComplete="off"
        role="combobox"
        aria-expanded={open}
        aria-autocomplete="list"
        aria-controls={listId}
      />
      {loading ? (
        <div className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
        </div>
      ) : null}
      {open && (hits.length > 0 || hint) ? (
        <ul
          id={listId}
          className="absolute z-50 mt-1 max-h-60 w-full overflow-auto rounded-md border border-border bg-popover text-popover-foreground shadow-md"
          role="listbox"
          onMouseDown={cancelBlurClose}
        >
          {hits.map((h, i) => (
            <li key={`${h.symbol}-${i}`} role="option" aria-selected={false}>
              <button
                type="button"
                className="flex min-h-11 w-full cursor-pointer flex-col justify-center gap-0.5 px-3 py-2 text-left text-sm transition-colors hover:bg-muted/80 focus-visible:bg-muted/80 focus-visible:outline-none"
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => pick(h)}
              >
                <span className="font-mono font-semibold">{h.symbol}</span>
                {h.name ? <span className="text-xs text-muted-foreground line-clamp-2">{h.name}</span> : null}
                {(h.exchangeShortName || h.stockExchange) && (
                  <span className="text-[11px] uppercase tracking-wide text-muted-foreground">
                    {h.exchangeShortName ?? h.stockExchange}
                    {h.currency ? ` · ${h.currency}` : ""}
                  </span>
                )}
              </button>
            </li>
          ))}
          {hint && hits.length === 0 ? (
            <li className="px-3 py-2 text-xs text-muted-foreground">{hint}</li>
          ) : null}
        </ul>
      ) : null}
    </div>
  );
}

export type UserTradeRow = {
  id: number;
  user_id: string;
  side: "buy" | "sell";
  position_side: "long" | "short";
  ticker: string;
  quantity: number | string;
  price_per_unit: number | string;
  currency: string;
  executed_at: string;
  broker: string | null;
  account_label: string | null;
  notes: string | null;
  /** False (default) = real money. True = paper trading book. */
  is_paper: boolean;
  metadata_json: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

type BookFilter = "all" | "real" | "paper";

function num(v: number | string): string {
  const n = typeof v === "number" ? v : parseFloat(String(v));
  return Number.isFinite(n) ? n.toLocaleString("en-US", { maximumFractionDigits: 6 }) : String(v);
}

function formatExecuted(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return new Intl.DateTimeFormat("en-GB", {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "UTC",
  }).format(d) + " UTC";
}

function fmtCcy(currency: string, n: number): string {
  const c = currency.trim().toUpperCase();
  if (!/^[A-Z]{3}$/.test(c)) {
    return n.toLocaleString("en-US", { maximumFractionDigits: 2 });
  }
  try {
    return new Intl.NumberFormat("en-US", { style: "currency", currency: c, maximumFractionDigits: 2 }).format(n);
  } catch {
    return n.toLocaleString("en-US", { maximumFractionDigits: 2 });
  }
}

/**
 * Currency, always signed. P&L must not be legible by colour alone — a
 * red/green-blind reader gets nothing from the class name, and the sign is the
 * fastest read for everyone else too.
 */
function fmtCcySigned(currency: string, n: number): string {
  const body = fmtCcy(currency, Math.abs(n));
  if (n > 0) return `+${body}`;
  if (n < 0) return `-${body}`;
  return body;
}

/** Tailwind classes for a P&L figure. Colour is the secondary cue, not the only one. */
function pnlClass(n: number | null): string {
  if (n == null || n === 0) return "";
  return n > 0
    ? "text-emerald-600 dark:text-emerald-400"
    : "text-rose-600 dark:text-rose-400";
}

function signedMarkValue(p: PortfolioPosition, mark: number | null): number | null {
  if (mark == null || !Number.isFinite(mark)) return null;
  return mark * p.netQty;
}

function unrealizedAtMark(p: PortfolioPosition, mark: number | null): number | null {
  if (mark == null || !Number.isFinite(mark)) return null;
  if (p.sideLabel === "long") return (mark - p.avgEntry) * p.netQty;
  return (p.avgEntry - mark) * Math.abs(p.netQty);
}

/**
 * Which book a derived position belongs to.
 *
 * Positions are keyed by ticker+currency only, so a position can be built from
 * BOTH real and paper trades at once. A closing trade has to land in one book,
 * and guessing would silently corrupt the other — so when a position mixes the
 * two we report null and the one-click close is withheld rather than writing to
 * a book the user didn't choose. Filtering to Real or Paper resolves it.
 */
function bookForPosition(
  trades: UserTradeRow[],
  ticker: string,
  currency: string,
): boolean | null {
  let sawReal = false;
  let sawPaper = false;
  for (const t of trades) {
    if (String(t.ticker).trim().toUpperCase() !== ticker) continue;
    if ((String(t.currency || "USD").trim().toUpperCase() || "USD") !== currency) continue;
    if (t.is_paper) sawPaper = true;
    else sawReal = true;
  }
  if (sawReal && sawPaper) return null;
  if (sawPaper) return true;
  if (sawReal) return false;
  return null;
}

/**
 * The close control. Disabled — with the reason stated — rather than hidden,
 * so a position that cannot be closed one-click explains itself instead of
 * silently lacking a button.
 */
function ClosePositionButton({
  position,
  mark,
  isPaper,
  onRequest,
  className = "",
}: {
  position: PortfolioPosition;
  mark: number | null;
  isPaper: boolean | null;
  onRequest: (v: { position: PortfolioPosition; mark: number; isPaper: boolean }) => void;
  className?: string;
}) {
  const reason =
    mark == null
      ? "No live price yet — can't close at market."
      : isPaper == null
        ? "This position mixes real and paper trades. Filter to Real or Paper to close it."
        : null;

  return (
    <button
      type="button"
      disabled={reason !== null}
      title={reason ?? `Close ${position.ticker} at ${fmtCcy(position.currency, mark ?? 0)}`}
      aria-label={`Close ${position.ticker} position${reason ? ` — unavailable: ${reason}` : ""}`}
      onClick={() => {
        if (mark != null && isPaper != null) onRequest({ position, mark, isPaper });
      }}
      className={
        "inline-flex min-h-11 cursor-pointer items-center justify-center rounded-md border border-border px-3 text-xs font-medium transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50 " +
        className
      }
    >
      Close
    </button>
  );
}

/** The offsetting trade that flattens a position. Long closes with a sell,
 *  short covers with a buy — the same rule the log-a-trade form states. */
function closingTradeFor(p: PortfolioPosition, mark: number) {
  return {
    side: (p.netQty > 0 ? "sell" : "buy") as "buy" | "sell",
    position_side: p.sideLabel,
    quantity: Math.abs(p.netQty),
    price_per_unit: mark,
    currency: p.currency,
    ticker: p.ticker,
  };
}

function PortfolioSection({ trades }: { trades: UserTradeRow[] }) {
  const positions = useMemo(() => buildPortfolioFromTrades(trades), [trades]);
  const symbolsKey = useMemo(
    () =>
      positions
        .map((p) => p.ticker)
        .sort()
        .join(","),
    [positions],
  );
  const [marks, setMarks] = useState<Record<string, number | null>>({});
  const [marksLoading, setMarksLoading] = useState(false);
  const router = useRouter();
  const [pendingClose, setPendingClose] = useState<
    { position: PortfolioPosition; mark: number; isPaper: boolean } | null
  >(null);
  const [closing, setClosing] = useState(false);
  const [closeError, setCloseError] = useState<string | null>(null);

  // Closing APPENDS an offsetting trade rather than editing history — the
  // portfolio is a replay of the ledger, so the position flattens because the
  // maths works out, not because rows were removed.
  async function handleClose() {
    if (!pendingClose) return;
    setClosing(true);
    setCloseError(null);
    const supabase = createClient();
    const { data: claims } = await supabase.auth.getClaims();
    const userId = claims?.claims?.sub;
    if (!userId) {
      setClosing(false);
      setCloseError("Your session expired. Sign in again to close this position.");
      return;
    }
    const t = closingTradeFor(pendingClose.position, pendingClose.mark);
    const { data, error } = await supabase
      .schema("swingtrader")
      .from("user_trades")
      .insert({
        user_id: userId,
        side: t.side,
        position_side: t.position_side,
        ticker: t.ticker,
        quantity: t.quantity,
        price_per_unit: t.price_per_unit,
        currency: t.currency,
        executed_at: new Date().toISOString(),
        broker: null,
        account_label: null,
        notes: "Closed at market",
        is_paper: pendingClose.isPaper,
      })
      .select()
      .single();
    setClosing(false);
    if (error) {
      setCloseError(error.message || "Failed to close the position.");
      return;
    }
    if (data) {
      track("trade_logged", {
        trade_id: String(data.id),
        ticker: data.ticker,
        side: data.side,
      });
      setPendingClose(null);
      router.refresh();
    }
  }

  useEffect(() => {
    if (positions.length === 0) {
      setMarks({});
      setMarksLoading(false);
      return;
    }
    let cancelled = false;
    setMarksLoading(true);
    const syms = [...new Set(positions.map((p) => p.ticker))];

    // One request per symbol, but concurrently — this used to await each quote
    // in turn, so a 20-position portfolio paid 20 sequential round trips before
    // a single mark appeared.
    async function load() {
      const entries = await Promise.all(
        syms.map(async (sym): Promise<[string, number | null]> => {
          try {
            const res = await fmpGetQuote(sym);
            if (!res.ok) return [sym, null];
            const data: unknown = res.data;
            const row = Array.isArray(data) ? data[0] : null;
            const price =
              row && typeof row === "object" && row !== null && typeof (row as { price?: unknown }).price === "number"
                ? (row as { price: number }).price
                : null;
            return [sym, price != null && Number.isFinite(price) ? price : null];
          } catch {
            return [sym, null];
          }
        }),
      );
      if (!cancelled) setMarks(Object.fromEntries(entries));
    }

    void load().finally(() => {
      if (!cancelled) setMarksLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [symbolsKey, positions.length]);

  const portfolioCurrencies = useMemo(() => new Set(positions.map((p) => p.currency)), [positions]);
  const singlePortfolioCcy = portfolioCurrencies.size === 1 ? positions[0]?.currency ?? null : null;

  const totals = useMemo(() => {
    let mv = 0;
    let ur = 0;
    let nMv = 0;
    let nUr = 0;
    for (const p of positions) {
      const m = marks[p.ticker] ?? null;
      const smv = signedMarkValue(p, m);
      const sur = unrealizedAtMark(p, m);
      if (smv != null) {
        mv += smv;
        nMv += 1;
      }
      if (sur != null) {
        ur += sur;
        nUr += 1;
      }
    }
    return { mv, ur, nMv, nUr };
  }, [positions, marks]);

  if (positions.length === 0) {
    return (
      <section aria-labelledby="portfolio-heading">
        <h2
          id="portfolio-heading"
          className="flex items-center gap-2 border-b border-border pb-3 text-lg font-semibold tracking-tight"
        >
          <Briefcase className="h-5 w-5 opacity-80" aria-hidden />
          Portfolio
        </h2>
        <p className="mt-3 max-w-[65ch] text-sm text-muted-foreground">
          No open positions. Open and close trades with the correct side (buy/sell) and book (long/short) to build a
          position; we replay your ledger with average-cost to compute size and average entry.
        </p>
      </section>
    );
  }

  return (
    <section aria-labelledby="portfolio-heading" className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border pb-3">
        <h2
          id="portfolio-heading"
          className="flex items-center gap-2 text-lg font-semibold tracking-tight"
        >
          <Briefcase className="h-5 w-5 opacity-80" aria-hidden />
          Portfolio
        </h2>
        {marksLoading ? (
          <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
            <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
            Loading marks…
          </span>
        ) : null}
      </div>

      {/* The two numbers the page exists to answer. These used to live in a
          text-xs table footer, below the fold of a horizontally-scrolling
          table — i.e. the most important figures were the least visible. */}
      {singlePortfolioCcy && (totals.nMv > 0 || totals.nUr > 0) ? (
        <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-border bg-border">
          <div className="bg-background px-4 py-3">
            <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Market value
            </dt>
            <dd className="mt-1 text-xl font-semibold tabular-nums tracking-tight">
              {totals.nMv > 0 ? fmtCcy(singlePortfolioCcy, totals.mv) : "—"}
            </dd>
          </div>
          <div className="bg-background px-4 py-3">
            <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Unrealized P&amp;L
            </dt>
            <dd
              className={`mt-1 text-xl font-semibold tabular-nums tracking-tight ${pnlClass(
                totals.nUr > 0 ? totals.ur : null,
              )}`}
            >
              {totals.nUr > 0 ? fmtCcySigned(singlePortfolioCcy, totals.ur) : "—"}
            </dd>
          </div>
        </dl>
      ) : null}

      <p className="max-w-[65ch] text-xs text-muted-foreground">
        From your trade history (average cost). Live price from FMP quote; P&amp;L is unrealized vs average entry.
      </p>

      {/* Eight columns do not survive a phone. Below `md` the same rows render
          as cards; the table takes over where there is width for it. */}
      <ul className="flex flex-col gap-2 md:hidden">
        {positions.map((p) => {
          const mark = marks[p.ticker] ?? null;
          const smv = signedMarkValue(p, mark);
          const sur = unrealizedAtMark(p, mark);
          return (
            <li
              key={`${p.ticker}-${p.currency}-card`}
              className="rounded-lg border border-border p-3"
            >
              <div className="flex items-baseline justify-between gap-2">
                <span className="font-mono text-sm font-semibold">{p.ticker}</span>
                <span className={`text-sm font-semibold tabular-nums ${pnlClass(sur)}`}>
                  {sur != null ? fmtCcySigned(p.currency, sur) : "—"}
                </span>
              </div>
              <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
                <div className="flex justify-between gap-2">
                  <dt className="text-muted-foreground">Qty</dt>
                  <dd className="tabular-nums">
                    {num(p.netQty)}{" "}
                    <span className="capitalize text-muted-foreground">{p.sideLabel}</span>
                  </dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt className="text-muted-foreground">Avg entry</dt>
                  <dd className="tabular-nums">{fmtCcy(p.currency, p.avgEntry)}</dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt className="text-muted-foreground">Last</dt>
                  <dd className="tabular-nums">
                    {mark != null ? fmtCcy(p.currency, mark) : "—"}
                  </dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt className="text-muted-foreground">Value</dt>
                  <dd className="tabular-nums">
                    {smv != null ? fmtCcy(p.currency, smv) : "—"}
                  </dd>
                </div>
              </dl>
              <ClosePositionButton
                position={p}
                mark={mark}
                isPaper={bookForPosition(trades, p.ticker, p.currency)}
                onRequest={setPendingClose}
                className="mt-3 w-full"
              />
            </li>
          );
        })}
      </ul>

      <div className="hidden overflow-x-auto rounded-lg border border-border md:block">
        <table className="w-full text-sm">
          <thead className="bg-muted/40 border-b border-border">
            <tr>
              <th className="px-3 py-2 text-left text-xs font-medium text-muted-foreground">Ticker</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-muted-foreground">Book</th>
              <th className="px-3 py-2 text-right text-xs font-medium text-muted-foreground">Qty</th>
              <th className="px-3 py-2 text-right text-xs font-medium text-muted-foreground">Avg entry</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-muted-foreground">CCY</th>
              <th className="px-3 py-2 text-right text-xs font-medium text-muted-foreground">Last</th>
              <th className="px-3 py-2 text-right text-xs font-medium text-muted-foreground">Value @ last</th>
              <th className="px-3 py-2 text-right text-xs font-medium text-muted-foreground">Unrealized</th>
              <th className="px-3 py-2 text-right text-xs font-medium text-muted-foreground">
                <span className="sr-only">Close position</span>
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {positions.map((p) => {
              const mark = marks[p.ticker] ?? null;
              const smv = signedMarkValue(p, mark);
              const sur = unrealizedAtMark(p, mark);
              return (
                <tr key={`${p.ticker}-${p.currency}`} className="hover:bg-muted/20">
                  <td className="px-3 py-2 font-mono font-semibold">{p.ticker}</td>
                  <td className="px-3 py-2 capitalize">{p.sideLabel}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{num(p.netQty)}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{fmtCcy(p.currency, p.avgEntry)}</td>
                  <td className="px-3 py-2">{p.currency}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-muted-foreground">
                    {mark != null ? fmtCcy(p.currency, mark) : "—"}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {smv != null ? fmtCcy(p.currency, smv) : "—"}
                  </td>
                  <td className={`px-3 py-2 text-right tabular-nums ${pnlClass(sur)}`}>
                    {sur != null ? fmtCcySigned(p.currency, sur) : "—"}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <ClosePositionButton
                      position={p}
                      mark={mark}
                      isPaper={bookForPosition(trades, p.ticker, p.currency)}
                      onRequest={setPendingClose}
                    />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {portfolioCurrencies.size > 1 ? (
        <p className="flex items-start gap-1.5 text-xs text-amber-700 dark:text-amber-500">
          <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          Multiple currencies: portfolio-wide totals are hidden; use per-row value and P&amp;L for each CCY.
        </p>
      ) : null}

      <Dialog
        open={pendingClose !== null}
        onOpenChange={(o) => {
          if (!o && !closing) {
            setPendingClose(null);
            setCloseError(null);
          }
        }}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Close this position?</DialogTitle>
            <DialogDescription className="pt-1">
              {pendingClose ? (
                <>
                  This logs{" "}
                  <span className="font-mono font-semibold text-foreground">
                    {closingTradeFor(pendingClose.position, pendingClose.mark).side}{" "}
                    {num(Math.abs(pendingClose.position.netQty))}{" "}
                    {pendingClose.position.ticker}
                  </span>{" "}
                  at{" "}
                  <span className="font-mono font-semibold text-foreground">
                    {fmtCcy(pendingClose.position.currency, pendingClose.mark)}
                  </span>{" "}
                  ({pendingClose.isPaper ? "paper" : "real"} book), flattening the{" "}
                  {pendingClose.position.sideLabel} position.
                  <br />
                  It adds a trade rather than deleting history, so your realised
                  P&amp;L stays intact. The price is the last quote, which may differ
                  from your actual fill.
                </>
              ) : null}
            </DialogDescription>
          </DialogHeader>
          {closeError ? (
            <p role="alert" className="flex items-start gap-1.5 text-sm text-destructive">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
              {closeError}
            </p>
          ) : null}
          <DialogFooter className="gap-2 sm:gap-2">
            <Button
              variant="ghost"
              className="min-h-11"
              disabled={closing}
              onClick={() => {
                setPendingClose(null);
                setCloseError(null);
              }}
            >
              Cancel
            </Button>
            <Button className="min-h-11" disabled={closing} onClick={() => void handleClose()}>
              {closing ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              ) : null}
              {closing ? "Closing…" : "Close position"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}

export function TradesUI({ initialTrades }: { initialTrades: UserTradeRow[] }) {
  const router = useRouter();
  const [trades, setTrades] = useState<UserTradeRow[]>(initialTrades);

  useEffect(() => {
    setTrades(initialTrades);
  }, [initialTrades]);
  const [saving, setSaving] = useState(false);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  // Deleting a trade rewrites the portfolio, so it gets a real confirmation
  // rather than a native confirm() — which can't be styled, can't be read by
  // the page, and blocks the whole tab while it's up.
  const [pendingDelete, setPendingDelete] = useState<UserTradeRow | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const [ticker, setTicker] = useState("");
  const [side, setSide] = useState<"buy" | "sell">("buy");
  const [positionSide, setPositionSide] = useState<"long" | "short">("long");
  const [isPaper, setIsPaper] = useState(false);
  const [bookFilter, setBookFilter] = useState<BookFilter>("all");
  const [quantity, setQuantity] = useState("");
  const [pricePerUnit, setPricePerUnit] = useState("");
  const [currency, setCurrency] = useState("USD");
  const [executedAtLocal, setExecutedAtLocal] = useState(() => {
    const d = new Date();
    const pad = (n: number) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  });
  const [broker, setBroker] = useState("");
  const [accountLabel, setAccountLabel] = useState("");
  const [notes, setNotes] = useState("");

  const priceDirtyRef = useRef(false);
  const priceFetchGen = useRef(0);
  const [priceAutoStatus, setPriceAutoStatus] = useState<"idle" | "loading" | "ok" | "error">("idle");
  const [priceAutoNote, setPriceAutoNote] = useState<string | null>(null);

  useEffect(() => {
    priceDirtyRef.current = false;
  }, [ticker, executedAtLocal]);

  useEffect(() => {
    const sym = ticker.trim().toUpperCase();
    const cal = localCalendarDateFromDatetimeLocal(executedAtLocal);
    if (!sym || !cal) {
      setPriceAutoStatus("idle");
      setPriceAutoNote(null);
      return;
    }

    const calendarDate = cal;

    setPriceAutoStatus("idle");
    setPriceAutoNote(null);

    const handle = setTimeout(() => {
      const id = ++priceFetchGen.current;

      async function run() {
        if (priceDirtyRef.current) return;
        setPriceAutoStatus("loading");
        setPriceAutoNote(null);
        try {
          const res = await fmpGetPriceAtDate(sym, calendarDate);
          if (id !== priceFetchGen.current) return;
          if (!res.ok) {
            setPriceAutoStatus("error");
            setPriceAutoNote(res.error);
            return;
          }
          const parsed = res.data;
          if (priceDirtyRef.current) {
            setPriceAutoStatus("idle");
            return;
          }
          setPricePerUnit(formatPriceForInput(parsed.price));
          setPriceAutoStatus("ok");
          setPriceAutoNote(
            parsed.source === "historical"
              ? `Filled: daily close (${parsed.asOfDate})`
              : "Filled: latest quote (no daily bar for that day)",
          );
        } catch {
          if (id !== priceFetchGen.current) return;
          setPriceAutoStatus("error");
          setPriceAutoNote("Network error");
        }
      }

      void run();
    }, AUTO_PRICE_DEBOUNCE_MS);

    return () => {
      clearTimeout(handle);
      priceFetchGen.current += 1;
    };
  }, [ticker, executedAtLocal]);

  const filteredTrades = useMemo(() => {
    if (bookFilter === "all") return trades;
    const wantPaper = bookFilter === "paper";
    return trades.filter((t) => Boolean(t.is_paper) === wantPaper);
  }, [trades, bookFilter]);

  const sorted = useMemo(
    () =>
      [...filteredTrades].sort(
        (a, b) => new Date(b.executed_at).getTime() - new Date(a.executed_at).getTime(),
      ),
    [filteredTrades],
  );

  const closingIds = useMemo(
    () =>
      closingTradeIdSet(
        trades.map((t) => ({
          id: t.id,
          ticker: t.ticker,
          currency: t.currency,
          quantity: t.quantity,
          price_per_unit: t.price_per_unit,
          side: t.side,
          executed_at: t.executed_at,
          is_paper: !!t.is_paper,
        })),
      ),
    [trades],
  );

  const paperCount = useMemo(
    () => trades.reduce((n, t) => (t.is_paper ? n + 1 : n), 0),
    [trades],
  );
  const realCount = trades.length - paperCount;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setFormError(null);
    const q = parseFloat(quantity);
    const p = parseFloat(pricePerUnit);
    if (!ticker.trim()) {
      setFormError("Ticker is required.");
      return;
    }
    if (!Number.isFinite(q) || q <= 0) {
      setFormError("Quantity must be a positive number.");
      return;
    }
    if (!Number.isFinite(p) || p < 0) {
      setFormError("Price must be zero or positive.");
      return;
    }

    const supabase = createClient();
    const { data: claims } = await supabase.auth.getClaims();
    const userId = claims?.claims?.sub;
    if (!userId) {
      setFormError("You must be signed in to log a trade.");
      return;
    }

    const executed = new Date(executedAtLocal);
    if (Number.isNaN(executed.getTime())) {
      setFormError("Invalid execution date/time.");
      return;
    }

    setSaving(true);
    const { data, error } = await supabase
      .schema("swingtrader")
      .from("user_trades")
      .insert({
        user_id: userId,
        side,
        position_side: positionSide,
        ticker: ticker.trim().toUpperCase(),
        quantity: q,
        price_per_unit: p,
        currency: currency.trim() || "USD",
        executed_at: executed.toISOString(),
        broker: broker.trim() || null,
        account_label: accountLabel.trim() || null,
        notes: notes.trim() || null,
        is_paper: isPaper,
      })
      .select()
      .single();

    setSaving(false);
    if (error) {
      setFormError(error.message || "Failed to save trade. Is the user_trades migration applied?");
      return;
    }
    if (data) {
      track("trade_logged", {
        trade_id: String(data.id),
        ticker: data.ticker,
        side: data.side,
      });
      setTicker("");
      setQuantity("");
      setPricePerUnit("");
      setNotes("");
      router.refresh();
    }
  }

  async function handleDelete(trade: UserTradeRow) {
    setDeletingId(trade.id);
    setDeleteError(null);
    const supabase = createClient();
    const { error } = await supabase
      .schema("swingtrader")
      .from("user_trades")
      .delete()
      .eq("id", trade.id);
    setDeletingId(null);
    if (error) {
      // Keep the dialog open and show why — an alert() here left the user with
      // a dismissed modal and no idea whether the row had gone.
      setDeleteError(error.message);
      return;
    }
    setPendingDelete(null);
    router.refresh();
  }

  return (
    <div className="flex flex-col gap-8">
      <form
        onSubmit={(e) => void handleSubmit(e)}
        data-tour="trade-add"
        className="rounded-xl border border-border bg-card p-5 space-y-4"
      >
        <h2 className="text-lg font-semibold tracking-tight">Log a trade</h2>
        <p className="max-w-[65ch] text-xs text-muted-foreground">
          Long: open with buy, close with sell. Short: open with sell, cover with buy.
        </p>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <label className="flex flex-col gap-1 text-sm sm:col-span-2 lg:col-span-1">
            <span className="text-muted-foreground">Ticker</span>
            <TickerSearchInput
              value={ticker}
              onChangeTicker={setTicker}
              onPickCurrency={setCurrency}
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-muted-foreground">Side</span>
            <select
              value={side}
              onChange={(e) => setSide(e.target.value as "buy" | "sell")}
              className="min-h-11 cursor-pointer rounded-md border border-input bg-background px-3 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
            >
              <option value="buy">Buy</option>
              <option value="sell">Sell</option>
            </select>
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-muted-foreground">Position</span>
            <select
              value={positionSide}
              onChange={(e) => setPositionSide(e.target.value as "long" | "short")}
              className="min-h-11 cursor-pointer rounded-md border border-input bg-background px-3 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
            >
              <option value="long">Long</option>
              <option value="short">Short</option>
            </select>
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-muted-foreground">Book</span>
            <select
              value={isPaper ? "paper" : "real"}
              onChange={(e) => setIsPaper(e.target.value === "paper")}
              className="min-h-11 cursor-pointer rounded-md border border-input bg-background px-3 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
            >
              <option value="real">Real</option>
              <option value="paper">Paper</option>
            </select>
            <span className="text-xs text-muted-foreground">
              Paper trades stay separate in the portfolio view.
            </span>
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-muted-foreground">Executed (local)</span>
            <input
              type="datetime-local"
              value={executedAtLocal}
              onChange={(e) => setExecutedAtLocal(e.target.value)}
              className="min-h-11 rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-muted-foreground">Quantity</span>
            <input
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
              inputMode="decimal"
              placeholder="100"
              className="min-h-11 rounded-md border border-input bg-background px-3 py-2 text-sm tabular-nums focus:outline-none focus:ring-1 focus:ring-ring"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-muted-foreground">Price / unit</span>
            <div className="relative">
              <input
                value={pricePerUnit}
                onChange={(e) => {
                  priceDirtyRef.current = true;
                  setPriceAutoStatus("idle");
                  setPriceAutoNote(null);
                  setPricePerUnit(e.target.value);
                }}
                inputMode="decimal"
                placeholder="185.50"
                className="min-h-11 w-full rounded-md border border-input bg-background px-3 py-2 pr-9 text-sm tabular-nums focus:outline-none focus:ring-1 focus:ring-ring"
              />
              {priceAutoStatus === "loading" ? (
                <div className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin" />
                </div>
              ) : null}
            </div>
            {priceAutoNote ? (
              <span
                className={
                  priceAutoStatus === "error"
                    ? "text-xs text-amber-700 dark:text-amber-500"
                    : "text-xs text-muted-foreground"
                }
              >
                {priceAutoNote}
              </span>
            ) : (
              <span className="text-xs text-muted-foreground">
                Set ticker and execution time to load a price from FMP (daily close, or live quote fallback).
              </span>
            )}
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-muted-foreground">Currency</span>
            <input
              value={currency}
              onChange={(e) => setCurrency(e.target.value)}
              placeholder="USD"
              className="min-h-11 rounded-md border border-input bg-background px-3 py-2 text-sm uppercase focus:outline-none focus:ring-1 focus:ring-ring"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-muted-foreground">Broker (optional)</span>
            <input
              value={broker}
              onChange={(e) => setBroker(e.target.value)}
              className="min-h-11 rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm sm:col-span-2">
            <span className="text-muted-foreground">Account label (optional)</span>
            <input
              value={accountLabel}
              onChange={(e) => setAccountLabel(e.target.value)}
              className="min-h-11 rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm sm:col-span-2 lg:col-span-4">
            <span className="text-muted-foreground">Notes (optional)</span>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={2}
              className="min-h-11 resize-y rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
            />
          </label>
        </div>
        {formError ? (
          <p
            role="alert"
            className="flex items-start gap-1.5 text-sm text-destructive"
          >
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
            {formError}
          </p>
        ) : null}
        <button
          type="submit"
          disabled={saving}
          className="inline-flex min-h-11 cursor-pointer items-center gap-2 rounded-md bg-foreground px-4 text-sm font-medium text-background transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-default disabled:opacity-50"
        >
          {saving ? (
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
          ) : (
            <Plus className="h-4 w-4" aria-hidden />
          )}
          {saving ? "Adding…" : "Add trade"}
        </button>
      </form>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div
          role="radiogroup"
          aria-label="Filter by book"
          className="inline-flex items-center gap-1 rounded-lg border border-border bg-card p-1 text-xs"
        >
          {(
            [
              { key: "all", label: `All (${trades.length})` },
              { key: "real", label: `Real (${realCount})` },
              { key: "paper", label: `Paper (${paperCount})` },
            ] as { key: BookFilter; label: string }[]
          ).map((opt) => {
            const active = bookFilter === opt.key;
            return (
              <button
                key={opt.key}
                type="button"
                role="radio"
                onClick={() => setBookFilter(opt.key)}
                className={
                  "inline-flex min-h-11 cursor-pointer items-center rounded-md px-3 font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring " +
                  (active
                    ? "bg-foreground text-background"
                    : "text-muted-foreground hover:text-foreground")
                }
                aria-checked={active}
              >
                {opt.label}
              </button>
            );
          })}
        </div>
        {bookFilter !== "all" ? (
          <p className="max-w-[65ch] text-xs text-muted-foreground">
            Showing {bookFilter === "paper" ? "paper" : "real"} trades only.
            Portfolio is recomputed from the visible subset.
          </p>
        ) : null}
      </div>

      <PortfolioSection trades={filteredTrades} />

      <section data-tour="trade-list" aria-labelledby="trades-heading">
        <h2
          id="trades-heading"
          className="mb-4 border-b border-border pb-3 text-lg font-semibold tracking-tight"
        >
          Your trades
          {sorted.length > 0 ? (
            <span className="ml-2 font-normal tabular-nums text-muted-foreground">
              {sorted.length}
            </span>
          ) : null}
        </h2>
        {sorted.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border px-6 py-10 text-center">
            <p className="text-sm font-medium text-foreground">
              {bookFilter === "all"
                ? "No trades logged yet."
                : `No ${bookFilter} trades yet.`}
            </p>
            <p className="mx-auto mt-1 max-w-[45ch] text-sm text-muted-foreground">
              {bookFilter === "all"
                ? "Log your first execution above and your portfolio builds itself from the ledger."
                : "Switch the filter, or log one to this book above."}
            </p>
          </div>
        ) : (
          <>
          {/* Ten columns on a phone is a horizontal-scroll maze. Cards below
              `md`, table where the width exists. */}
          <ul className="flex flex-col gap-2 md:hidden">
            {sorted.map((row) => (
              <li key={`${row.id}-card`} className="rounded-lg border border-border p-3">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <span className="inline-flex items-center gap-2">
                      <span className="font-mono text-sm font-semibold">{row.ticker}</span>
                      {row.is_paper ? (
                        <span className="rounded-sm bg-amber-500/15 px-1.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-amber-700 dark:text-amber-400">
                          Paper
                        </span>
                      ) : null}
                    </span>
                    <p className="mt-0.5 text-xs capitalize text-muted-foreground">
                      {row.side} · {row.position_side}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => {
                      setDeleteError(null);
                      setPendingDelete(row);
                    }}
                    className="inline-flex h-11 w-11 shrink-0 cursor-pointer items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-destructive focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                    aria-label={`Delete ${row.ticker} trade from ${formatExecuted(row.executed_at)}`}
                  >
                    <Trash2 className="h-4 w-4" aria-hidden />
                  </button>
                </div>
                <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
                  <div className="flex justify-between gap-2">
                    <dt className="text-muted-foreground">Qty</dt>
                    <dd className="tabular-nums">{num(row.quantity)}</dd>
                  </div>
                  <div className="flex justify-between gap-2">
                    <dt className="text-muted-foreground">Price</dt>
                    <dd className="tabular-nums">
                      {num(row.price_per_unit)} {row.currency}
                    </dd>
                  </div>
                </dl>
                <p className="mt-2 text-xs text-muted-foreground">
                  {formatExecuted(row.executed_at)}
                </p>
                {row.notes ? (
                  <p className="mt-1 text-xs text-muted-foreground">{row.notes}</p>
                ) : null}
                {closingIds.has(row.id) ? (
                  <Link
                    href={`/protected/trades/positions/${row.id}/review`}
                    className="mt-2 inline-flex min-h-11 items-center gap-1 rounded-md border border-amber-500/30 bg-amber-500/10 px-3 text-xs font-medium text-amber-700 transition-colors hover:bg-amber-500/20 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring dark:text-amber-400"
                  >
                    <Sparkles className="h-3 w-3" aria-hidden />
                    AI post-trade review
                  </Link>
                ) : null}
              </li>
            ))}
          </ul>
          <div className="hidden overflow-x-auto rounded-lg border border-border md:block">
            <table className="w-full text-sm">
              <thead className="bg-muted/40 border-b border-border">
                <tr>
                  <th className="px-3 py-2 text-left text-xs font-medium text-muted-foreground">Executed</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-muted-foreground">Ticker</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-muted-foreground">Side</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-muted-foreground">Position</th>
                  <th className="px-3 py-2 text-right text-xs font-medium text-muted-foreground">Qty</th>
                  <th className="px-3 py-2 text-right text-xs font-medium text-muted-foreground">Price</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-muted-foreground">CCY</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-muted-foreground">Notes</th>
                  {/* Action columns still need names — an empty <th> is
                      announced as a blank column header. */}
                  <th className="w-20 px-3 py-2">
                    <span className="sr-only">Post-trade review</span>
                  </th>
                  <th className="w-14 px-3 py-2">
                    <span className="sr-only">Delete</span>
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {sorted.map((row) => (
                  <tr key={row.id} className="hover:bg-muted/20">
                    <td className="px-3 py-2 whitespace-nowrap text-muted-foreground text-xs">
                      {formatExecuted(row.executed_at)}
                    </td>
                    <td className="px-3 py-2 font-mono font-semibold">
                      <span className="inline-flex items-center gap-2">
                        {row.ticker}
                        {row.is_paper ? (
                          <span className="rounded-sm bg-amber-500/15 px-1.5 py-0.5 font-sans text-[11px] font-semibold uppercase tracking-wide text-amber-700 dark:text-amber-400">
                            Paper
                            <span className="sr-only"> trade — not real money</span>
                          </span>
                        ) : null}
                      </span>
                    </td>
                    <td className="px-3 py-2 capitalize">{row.side}</td>
                    <td className="px-3 py-2 capitalize">{row.position_side}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{num(row.quantity)}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{num(row.price_per_unit)}</td>
                    <td className="px-3 py-2">{row.currency}</td>
                    <td className="px-3 py-2 max-w-[200px] truncate text-muted-foreground" title={row.notes ?? ""}>
                      {row.notes || "—"}
                    </td>
                    <td className="px-3 py-2">
                      {closingIds.has(row.id) ? (
                        <Link
                          href={`/protected/trades/positions/${row.id}/review`}
                          className="inline-flex min-h-9 items-center gap-1 rounded-md border border-amber-500/30 bg-amber-500/10 px-2 text-xs font-medium text-amber-700 transition-colors hover:bg-amber-500/20 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring dark:text-amber-400"
                          aria-label={`AI post-trade review for ${row.ticker}`}
                        >
                          <Sparkles className="h-3 w-3" aria-hidden />
                          Review
                        </Link>
                      ) : null}
                    </td>
                    <td className="px-3 py-2">
                      <button
                        type="button"
                        onClick={() => {
                          setDeleteError(null);
                          setPendingDelete(row);
                        }}
                        disabled={deletingId === row.id}
                        className="inline-flex h-9 w-9 cursor-pointer items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-destructive focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-default disabled:opacity-40"
                        aria-label={`Delete ${row.ticker} trade from ${formatExecuted(row.executed_at)}`}
                      >
                        {deletingId === row.id ? (
                          <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                        ) : (
                          <Trash2 className="h-4 w-4" aria-hidden />
                        )}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          </>
        )}
      </section>

      {/* Delete confirmation. Replaces confirm()/alert(), which blocked the tab
          and gave no way to report a failed delete. */}
      <Dialog
        open={pendingDelete !== null}
        onOpenChange={(next) => {
          if (!next && deletingId === null) {
            setPendingDelete(null);
            setDeleteError(null);
          }
        }}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Remove this trade?</DialogTitle>
            <DialogDescription className="pt-2">
              {pendingDelete ? (
                <>
                  <span className="font-mono font-semibold text-foreground">
                    {pendingDelete.ticker}
                  </span>{" "}
                  · {pendingDelete.side} {num(pendingDelete.quantity)} @{" "}
                  {num(pendingDelete.price_per_unit)} {pendingDelete.currency} ·{" "}
                  {formatExecuted(pendingDelete.executed_at)}.
                  <br />
                  Your portfolio is replayed from this ledger, so removing it
                  changes your position size and average entry. This can&apos;t be
                  undone.
                </>
              ) : null}
            </DialogDescription>
          </DialogHeader>
          {deleteError ? (
            <p role="alert" className="flex items-start gap-1.5 text-sm text-destructive">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
              {deleteError}
            </p>
          ) : null}
          <DialogFooter className="gap-2 sm:gap-2">
            <Button
              variant="ghost"
              className="min-h-11"
              disabled={deletingId !== null}
              onClick={() => {
                setPendingDelete(null);
                setDeleteError(null);
              }}
            >
              Keep it
            </Button>
            <Button
              variant="destructive"
              className="min-h-11"
              disabled={deletingId !== null}
              onClick={() => {
                if (pendingDelete) void handleDelete(pendingDelete);
              }}
            >
              {deletingId !== null ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              ) : (
                <Trash2 className="h-4 w-4" aria-hidden />
              )}
              {deletingId !== null ? "Removing…" : "Remove trade"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
