"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { Briefcase, Loader2, Plus, Trash2 } from "lucide-react";
import { buildPortfolioFromTrades, type PortfolioPosition } from "./portfolio-from-trades";

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
      const res = await fetch(`/api/fmp/search-symbol?query=${encodeURIComponent(trimmed)}`);
      const body: unknown = await res.json();
      if (id !== reqId.current) return;
      if (!res.ok) {
        const err =
          typeof body === "object" && body !== null && "error" in body && typeof (body as { error: unknown }).error === "string"
            ? (body as { error: string }).error
            : "Search failed";
        setHits([]);
        setHint(err);
        return;
      }
      if (!Array.isArray(body)) {
        setHits([]);
        setHint("Unexpected response");
        return;
      }
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
        className="w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-sm"
        autoComplete="off"
        role="combobox"
        aria-expanded={open}
        aria-autocomplete="list"
      />
      {loading ? (
        <div className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
        </div>
      ) : null}
      {open && (hits.length > 0 || hint) ? (
        <ul
          className="absolute z-50 mt-1 max-h-60 w-full overflow-auto rounded-md border border-border bg-popover text-popover-foreground shadow-md"
          role="listbox"
          onMouseDown={cancelBlurClose}
        >
          {hits.map((h, i) => (
            <li key={`${h.symbol}-${i}`} role="option">
              <button
                type="button"
                className="flex w-full flex-col gap-0.5 px-3 py-2 text-left text-sm hover:bg-muted/80"
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => pick(h)}
              >
                <span className="font-mono font-semibold">{h.symbol}</span>
                {h.name ? <span className="text-xs text-muted-foreground line-clamp-2">{h.name}</span> : null}
                {(h.exchangeShortName || h.stockExchange) && (
                  <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
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
  metadata_json: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

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

function signedMarkValue(p: PortfolioPosition, mark: number | null): number | null {
  if (mark == null || !Number.isFinite(mark)) return null;
  return mark * p.netQty;
}

function unrealizedAtMark(p: PortfolioPosition, mark: number | null): number | null {
  if (mark == null || !Number.isFinite(mark)) return null;
  if (p.sideLabel === "long") return (mark - p.avgEntry) * p.netQty;
  return (p.avgEntry - mark) * Math.abs(p.netQty);
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

  useEffect(() => {
    if (positions.length === 0) {
      setMarks({});
      setMarksLoading(false);
      return;
    }
    let cancelled = false;
    setMarksLoading(true);
    const syms = [...new Set(positions.map((p) => p.ticker))];

    async function load() {
      const next: Record<string, number | null> = {};
      for (const sym of syms) {
        try {
          const res = await fetch(`/api/fmp/quote?symbol=${encodeURIComponent(sym)}`);
          if (!res.ok) {
            next[sym] = null;
            continue;
          }
          const data: unknown = await res.json();
          const row = Array.isArray(data) ? data[0] : null;
          const price =
            row && typeof row === "object" && row !== null && typeof (row as { price?: unknown }).price === "number"
              ? (row as { price: number }).price
              : null;
          next[sym] = price != null && Number.isFinite(price) ? price : null;
        } catch {
          next[sym] = null;
        }
      }
      if (!cancelled) setMarks(next);
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
      <div className="rounded-xl border border-border bg-card p-5">
        <h2 className="text-lg font-semibold flex items-center gap-2">
          <Briefcase className="h-5 w-5 opacity-80" aria-hidden />
          Portfolio
        </h2>
        <p className="text-sm text-muted-foreground mt-2">
          No open positions. Open and close trades with the correct side (buy/sell) and book (long/short) to build a
          position; we replay your ledger with average-cost to compute size and average entry.
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-border bg-card p-5 space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-semibold flex items-center gap-2">
          <Briefcase className="h-5 w-5 opacity-80" aria-hidden />
          Portfolio
        </h2>
        {marksLoading ? (
          <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            Loading marks…
          </span>
        ) : null}
      </div>
      <p className="text-xs text-muted-foreground">
        From your trade history (average cost). Live price from FMP quote; P&amp;L is unrealized vs average entry.
      </p>
      <div className="overflow-x-auto rounded-lg border border-border">
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
                  <td
                    className={`px-3 py-2 text-right tabular-nums ${
                      sur == null ? "" : sur > 0 ? "text-emerald-600 dark:text-emerald-400" : sur < 0 ? "text-rose-600 dark:text-rose-400" : ""
                    }`}
                  >
                    {sur != null ? fmtCcy(p.currency, sur) : "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
          {singlePortfolioCcy && (totals.nMv > 0 || totals.nUr > 0) ? (
            <tfoot className="border-t border-border bg-muted/20 font-medium">
              <tr>
                <td colSpan={6} className="px-3 py-2 text-right text-xs text-muted-foreground">
                  Total (same currency only)
                </td>
                <td className="px-3 py-2 text-right tabular-nums text-xs">
                  {totals.nMv > 0 ? fmtCcy(singlePortfolioCcy, totals.mv) : "—"}
                </td>
                <td
                  className={`px-3 py-2 text-right tabular-nums text-xs ${
                    totals.ur > 0
                      ? "text-emerald-600 dark:text-emerald-400"
                      : totals.ur < 0
                        ? "text-rose-600 dark:text-rose-400"
                        : ""
                  }`}
                >
                  {totals.nUr > 0 ? fmtCcy(singlePortfolioCcy, totals.ur) : "—"}
                </td>
              </tr>
            </tfoot>
          ) : null}
        </table>
      </div>
      {portfolioCurrencies.size > 1 ? (
        <p className="text-[11px] text-amber-600 dark:text-amber-500">
          Multiple currencies: portfolio-wide totals are hidden; use per-row value and P&amp;L for each CCY.
        </p>
      ) : null}
    </div>
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

  const [ticker, setTicker] = useState("");
  const [side, setSide] = useState<"buy" | "sell">("buy");
  const [positionSide, setPositionSide] = useState<"long" | "short">("long");
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
          const res = await fetch(
            `/api/fmp/price-at-date?symbol=${encodeURIComponent(sym)}&date=${encodeURIComponent(calendarDate)}`,
          );
          const body: unknown = await res.json();
          if (id !== priceFetchGen.current) return;
          if (!res.ok) {
            setPriceAutoStatus("error");
            const msg =
              typeof body === "object" &&
              body !== null &&
              "error" in body &&
              typeof (body as { error: unknown }).error === "string"
                ? (body as { error: string }).error
                : "Could not load price";
            setPriceAutoNote(msg);
            return;
          }
          if (
            typeof body !== "object" ||
            body === null ||
            typeof (body as { price: unknown }).price !== "number" ||
            !Number.isFinite((body as { price: number }).price)
          ) {
            setPriceAutoStatus("error");
            setPriceAutoNote("Bad response");
            return;
          }
          const parsed = body as { price: number; source: "historical" | "quote"; asOfDate: string };
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

  const sorted = useMemo(
    () => [...trades].sort((a, b) => new Date(b.executed_at).getTime() - new Date(a.executed_at).getTime()),
    [trades],
  );

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
    const { data: userData, error: userErr } = await supabase.auth.getUser();
    if (userErr || !userData.user) {
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
        user_id: userData.user.id,
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
      })
      .select()
      .single();

    setSaving(false);
    if (error) {
      setFormError(error.message || "Failed to save trade. Is the user_trades migration applied?");
      return;
    }
    if (data) {
      setTicker("");
      setQuantity("");
      setPricePerUnit("");
      setNotes("");
      router.refresh();
    }
  }

  async function handleDelete(id: number) {
    if (!confirm("Remove this trade from your log?")) return;
    setDeletingId(id);
    const supabase = createClient();
    const { error } = await supabase.schema("swingtrader").from("user_trades").delete().eq("id", id);
    setDeletingId(null);
    if (error) {
      alert(error.message);
      return;
    }
    router.refresh();
  }

  return (
    <div className="flex flex-col gap-8">
      <form
        onSubmit={(e) => void handleSubmit(e)}
        className="rounded-xl border border-border bg-card p-5 space-y-4"
      >
        <h2 className="text-lg font-semibold">Log a trade</h2>
        <p className="text-xs text-muted-foreground">
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
              className="rounded-md border border-input bg-background px-3 py-2 text-sm"
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
              className="rounded-md border border-input bg-background px-3 py-2 text-sm"
            >
              <option value="long">Long</option>
              <option value="short">Short</option>
            </select>
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-muted-foreground">Executed (local)</span>
            <input
              type="datetime-local"
              value={executedAtLocal}
              onChange={(e) => setExecutedAtLocal(e.target.value)}
              className="rounded-md border border-input bg-background px-3 py-2 text-sm"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-muted-foreground">Quantity</span>
            <input
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
              inputMode="decimal"
              placeholder="100"
              className="rounded-md border border-input bg-background px-3 py-2 text-sm tabular-nums"
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
                className="w-full rounded-md border border-input bg-background px-3 py-2 pr-9 text-sm tabular-nums"
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
                    ? "text-[11px] text-amber-600 dark:text-amber-500"
                    : "text-[11px] text-muted-foreground"
                }
              >
                {priceAutoNote}
              </span>
            ) : (
              <span className="text-[11px] text-muted-foreground">
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
              className="rounded-md border border-input bg-background px-3 py-2 text-sm uppercase"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-muted-foreground">Broker (optional)</span>
            <input
              value={broker}
              onChange={(e) => setBroker(e.target.value)}
              className="rounded-md border border-input bg-background px-3 py-2 text-sm"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm sm:col-span-2">
            <span className="text-muted-foreground">Account label (optional)</span>
            <input
              value={accountLabel}
              onChange={(e) => setAccountLabel(e.target.value)}
              className="rounded-md border border-input bg-background px-3 py-2 text-sm"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm sm:col-span-2 lg:col-span-4">
            <span className="text-muted-foreground">Notes (optional)</span>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={2}
              className="rounded-md border border-input bg-background px-3 py-2 text-sm resize-y"
            />
          </label>
        </div>
        {formError ? <p className="text-sm text-rose-500">{formError}</p> : null}
        <button
          type="submit"
          disabled={saving}
          className="inline-flex items-center gap-2 rounded-md bg-foreground px-4 py-2 text-sm font-medium text-background hover:opacity-90 disabled:opacity-50"
        >
          {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
          Add trade
        </button>
      </form>

      <PortfolioSection trades={trades} />

      <div>
        <h2 className="text-lg font-semibold mb-3">Your trades</h2>
        {sorted.length === 0 ? (
          <p className="text-sm text-muted-foreground rounded-lg border border-border p-6 text-center">
            No trades logged yet.
          </p>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-border">
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
                  <th className="px-3 py-2 w-10" />
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {sorted.map((row) => (
                  <tr key={row.id} className="hover:bg-muted/20">
                    <td className="px-3 py-2 whitespace-nowrap text-muted-foreground text-xs">
                      {formatExecuted(row.executed_at)}
                    </td>
                    <td className="px-3 py-2 font-mono font-semibold">{row.ticker}</td>
                    <td className="px-3 py-2 capitalize">{row.side}</td>
                    <td className="px-3 py-2 capitalize">{row.position_side}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{num(row.quantity)}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{num(row.price_per_unit)}</td>
                    <td className="px-3 py-2">{row.currency}</td>
                    <td className="px-3 py-2 max-w-[200px] truncate text-muted-foreground" title={row.notes ?? ""}>
                      {row.notes || "—"}
                    </td>
                    <td className="px-3 py-2">
                      <button
                        type="button"
                        onClick={() => void handleDelete(row.id)}
                        disabled={deletingId === row.id}
                        className="p-1.5 rounded-md text-muted-foreground hover:text-rose-500 hover:bg-muted disabled:opacity-40"
                        title="Delete"
                      >
                        {deletingId === row.id ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <Trash2 className="h-4 w-4" />
                        )}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
