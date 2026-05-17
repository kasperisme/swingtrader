"use client";

import React, { useState, useMemo, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { Loader2, Plus, CheckCircle } from "lucide-react";
import { fmpGetPriceAtDate } from "@/app/actions/fmp";
import { createClient } from "@/lib/supabase/client";
import type { FmpQuote } from "@/lib/use-quotes";
import type { ScreeningRow, NoteStatus } from "./screenings-types";
import type { EntryMarker } from "@/components/ticker-charts";

function LogTradeForm({
  ticker,
  defaultPrice,
  onDone,
  onCancel,
}: {
  ticker: string;
  defaultPrice: number | null;
  onDone: () => void;
  onCancel: () => void;
}) {
  const router = useRouter();
  const [side, setSide] = useState<"buy" | "sell">("buy");
  const [positionSide, setPositionSide] = useState<"long" | "short">("long");
  const [quantity, setQuantity] = useState("");
  const [pricePerUnit, setPricePerUnit] = useState(
    defaultPrice != null
      ? String(Math.round(defaultPrice * 1_000_000) / 1_000_000)
      : "",
  );
  const [currency, setCurrency] = useState("USD");
  const [executedAtLocal, setExecutedAtLocal] = useState(() => {
    const d = new Date();
    const pad = (n: number) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  });
  const [tradeNotes, setTradeNotes] = useState("");
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [priceStatus, setPriceStatus] = useState<"idle" | "loading" | "ok">(
    "idle",
  );
  const priceFetchGen = useRef(0);
  const priceDirtyRef = useRef(false);

  useEffect(() => {
    priceDirtyRef.current = false;
  }, [executedAtLocal]);

  useEffect(() => {
    if (!ticker || !executedAtLocal) return;
    const d = new Date(executedAtLocal);
    if (Number.isNaN(d.getTime())) return;
    const cal = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

    const handle = setTimeout(() => {
      const id = ++priceFetchGen.current;
      async function run() {
        if (priceDirtyRef.current) return;
        setPriceStatus("loading");
        try {
          const res = await fmpGetPriceAtDate(ticker, cal);
          if (id !== priceFetchGen.current) return;
          if (res.ok && !priceDirtyRef.current) {
            setPricePerUnit(
              String(Math.round(res.data.price * 1_000_000) / 1_000_000),
            );
            setPriceStatus("ok");
          } else {
            setPriceStatus("idle");
          }
        } catch {
          if (id === priceFetchGen.current) setPriceStatus("idle");
        }
      }
      void run();
    }, 600);

    return () => {
      clearTimeout(handle);
      priceFetchGen.current += 1;
    };
  }, [ticker, executedAtLocal]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setFormError(null);
    const q = parseFloat(quantity);
    const p = parseFloat(pricePerUnit);
    if (!Number.isFinite(q) || q <= 0) {
      setFormError("Quantity must be a positive number.");
      return;
    }
    if (!Number.isFinite(p) || p < 0) {
      setFormError("Price must be zero or positive.");
      return;
    }
    const executed = new Date(executedAtLocal);
    if (Number.isNaN(executed.getTime())) {
      setFormError("Invalid execution date.");
      return;
    }

    setSaving(true);
    const supabase = createClient();
    const { data: claims } = await supabase.auth.getClaims();
    const userId = claims?.claims?.sub;
    if (!userId) {
      setFormError("Not signed in.");
      setSaving(false);
      return;
    }

    const { error: dbErr } = await supabase
      .schema("swingtrader")
      .from("user_trades")
      .insert({
        user_id: userId,
        side,
        position_side: positionSide,
        ticker,
        quantity: q,
        price_per_unit: p,
        currency: currency.trim() || "USD",
        executed_at: executed.toISOString(),
        notes: tradeNotes.trim() || null,
      });

    setSaving(false);
    if (dbErr) {
      setFormError(dbErr.message);
      return;
    }
    router.refresh();
    onDone();
  }

  const inputCls =
    "rounded-md border border-border bg-background px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-ring";
  const selectCls = `${inputCls} pr-6`;

  return (
    <form
      onSubmit={(e) => void handleSubmit(e)}
      className="flex flex-col gap-3 p-4 bg-muted/30 rounded-lg border border-border"
    >
      <p className="text-xs font-semibold text-foreground">
        Log trade — <span className="font-mono">{ticker}</span>
      </p>
      <div className="flex flex-wrap gap-3 items-end">
        <label className="flex flex-col gap-1 text-xs text-muted-foreground">
          Side
          <select
            value={side}
            onChange={(e) => setSide(e.target.value as "buy" | "sell")}
            className={selectCls}
          >
            <option value="buy">Buy</option>
            <option value="sell">Sell</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted-foreground">
          Position
          <select
            value={positionSide}
            onChange={(e) =>
              setPositionSide(e.target.value as "long" | "short")
            }
            className={selectCls}
          >
            <option value="long">Long</option>
            <option value="short">Short</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted-foreground">
          Executed (local)
          <input
            type="datetime-local"
            value={executedAtLocal}
            onChange={(e) => setExecutedAtLocal(e.target.value)}
            className={inputCls}
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted-foreground">
          Quantity
          <input
            type="number"
            min="0"
            step="any"
            placeholder="0"
            value={quantity}
            onChange={(e) => setQuantity(e.target.value)}
            className={`${inputCls} w-24`}
            required
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted-foreground">
          Price / unit
          <div className="relative flex items-center">
            <input
              type="number"
              min="0"
              step="any"
              placeholder="0.00"
              value={pricePerUnit}
              onChange={(e) => {
                priceDirtyRef.current = true;
                setPricePerUnit(e.target.value);
                setPriceStatus("idle");
              }}
              className={`${inputCls} w-28 pr-6`}
              required
            />
            {priceStatus === "loading" && (
              <Loader2 className="absolute right-1.5 w-3 h-3 animate-spin text-muted-foreground" />
            )}
            {priceStatus === "ok" && (
              <CheckCircle className="absolute right-1.5 w-3 h-3 text-emerald-500" />
            )}
          </div>
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted-foreground">
          CCY
          <input
            type="text"
            value={currency}
            onChange={(e) => setCurrency(e.target.value.toUpperCase())}
            maxLength={4}
            className={`${inputCls} w-16 uppercase`}
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted-foreground flex-1 min-w-[140px]">
          Notes (optional)
          <input
            type="text"
            value={tradeNotes}
            onChange={(e) => setTradeNotes(e.target.value)}
            placeholder="e.g. breakout entry"
            className={inputCls}
          />
        </label>
      </div>
      {formError && <p className="text-xs text-rose-500">{formError}</p>}
      <div className="flex gap-2">
        <button
          type="submit"
          disabled={saving}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-foreground text-background text-xs font-medium disabled:opacity-50 hover:opacity-90 transition-opacity"
        >
          {saving ? (
            <Loader2 className="w-3 h-3 animate-spin" />
          ) : (
            <Plus className="w-3 h-3" />
          )}
          {saving ? "Saving…" : "Save trade"}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="px-3 py-1.5 rounded-md border border-border text-xs text-muted-foreground hover:bg-muted/40 transition-colors"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}

export function TradeMonitoringView({
  entries,
  quotes,
  loadingQuotes,
  selectedTicker,
  onSelect,
  onGoToCharts,
  onOpenWorkflowEditor,
  getStatus,
  activePositionSymbols,
  filteredSymbolSet,
}: {
  entries: { row: ScreeningRow; pivot: EntryMarker }[];
  quotes: Record<string, FmpQuote | null>;
  loadingQuotes: boolean;
  selectedTicker: string | null;
  onSelect: (ticker: string) => void;
  onGoToCharts: () => void;
  onOpenWorkflowEditor: (ticker: string) => void;
  getStatus: (ticker: string) => NoteStatus;
  activePositionSymbols: Set<string>;
  filteredSymbolSet: Set<string>;
}) {
  const [logTradeTicker, setLogTradeTicker] = useState<string | null>(null);
  type TradeSortKey =
    | "symbol"
    | "pivotDate"
    | "pivotPrice"
    | "latest"
    | "vsPivotPct"
    | "workflow"
    | "results";
  const TRADE_SORT_KEYS: TradeSortKey[] = [
    "symbol",
    "pivotDate",
    "pivotPrice",
    "latest",
    "vsPivotPct",
    "workflow",
    "results",
  ];
  const [sortKey, setSortKeyRaw] = useState<TradeSortKey>(() => {
    try {
      const v = localStorage.getItem("trade-monitor-sort-key") as TradeSortKey;
      if (TRADE_SORT_KEYS.includes(v)) return v;
    } catch {
      /* ignore */
    }
    return "vsPivotPct";
  });
  const [sortDir, setSortDirRaw] = useState<"asc" | "desc">(() => {
    try {
      const v = localStorage.getItem("trade-monitor-sort-dir");
      if (v === "asc" || v === "desc") return v;
    } catch {
      /* ignore */
    }
    return "desc";
  });

  function setSortKey(k: TradeSortKey) {
    setSortKeyRaw(k);
    try {
      localStorage.setItem("trade-monitor-sort-key", k);
    } catch {
      /* ignore */
    }
  }
  function setSortDir(d: "asc" | "desc") {
    setSortDirRaw(d);
    try {
      localStorage.setItem("trade-monitor-sort-dir", d);
    } catch {
      /* ignore */
    }
  }

  function toggleSort(k: TradeSortKey) {
    if (sortKey === k) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
      return;
    }
    setSortKey(k);
    setSortDir(
      k === "symbol" || k === "pivotDate" || k === "workflow"
        ? "asc"
        : "desc",
    );
  }

  const sorted = useMemo(() => {
    const out = [...entries];
    out.sort((a, b) => {
      const symA = a.row.symbol ?? "";
      const symB = b.row.symbol ?? "";
      const qA = quotes[symA];
      const qB = quotes[symB];
      const dA = qA?.price != null ? qA.price - a.pivot.price : null;
      const dB = qB?.price != null ? qB.price - b.pivot.price : null;
      const dpA =
        dA != null && Math.abs(a.pivot.price) > 1e-9
          ? (dA / a.pivot.price) * 100
          : null;
      const dpB =
        dB != null && Math.abs(b.pivot.price) > 1e-9
          ? (dB / b.pivot.price) * 100
          : null;
      const stA = getStatus(symA);
      const stB = getStatus(symB);
      const inA = filteredSymbolSet.has(symA);
      const inB = filteredSymbolSet.has(symB);

      let cmp = 0;
      if (sortKey === "symbol") cmp = symA.localeCompare(symB);
      else if (sortKey === "pivotDate")
        cmp = a.pivot.date.localeCompare(b.pivot.date);
      else if (sortKey === "pivotPrice") cmp = a.pivot.price - b.pivot.price;
      else if (sortKey === "latest")
        cmp = (qA?.price ?? -Infinity) - (qB?.price ?? -Infinity);
      else if (sortKey === "vsPivotPct")
        cmp = (dpA ?? -Infinity) - (dpB ?? -Infinity);
      else if (sortKey === "workflow") cmp = stA.localeCompare(stB);
      else if (sortKey === "results") cmp = Number(inA) - Number(inB);

      if (cmp === 0) cmp = symA.localeCompare(symB);
      return sortDir === "asc" ? cmp : -cmp;
    });
    return out;
  }, [entries, quotes, getStatus, filteredSymbolSet, sortKey, sortDir]);

  function ColHd({
    label,
    col,
    align = "left",
  }: {
    label: string;
    col: TradeSortKey;
    align?: "left" | "center" | "right";
  }) {
    const active = sortKey === col;
    const alignClass =
      align === "center"
        ? "text-center"
        : align === "right"
          ? "text-right"
          : "text-left";
    return (
      <th
        onClick={() => toggleSort(col)}
        className={`px-3 py-2 text-xs font-medium text-muted-foreground uppercase tracking-wide whitespace-nowrap cursor-pointer select-none hover:text-foreground ${alignClass} ${active ? "text-foreground" : ""}`}
      >
        {label}
        {active ? (sortDir === "asc" ? " ↑" : " ↓") : ""}
      </th>
    );
  }

  if (entries.length === 0) {
    return (
      <p className="text-sm text-muted-foreground py-8 text-center">
        No pivot markers yet. Set a pivot on the Charts tab (right-click the
        chart).
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="space-y-1">
        <h3 className="text-sm font-semibold text-foreground">
          Pivot overview
        </h3>
        <p className="text-sm text-muted-foreground">
          All tickers in this run with a saved chart pivot. Charts still draw
          the pivot dot and ray; open a row to review price vs pivot on the
          Charts tab.
        </p>
      </div>
      {loadingQuotes && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="w-4 h-4 animate-spin" />
          Loading latest prices…
        </div>
      )}
      <div className="overflow-x-auto border border-border">
        <table className="w-full text-sm">
          <thead className="bg-muted/40 border-b border-border">
            <tr>
              <ColHd label="Symbol" col="symbol" />
              <ColHd label="Pivot date" col="pivotDate" />
              <ColHd label="Pivot" col="pivotPrice" align="right" />
              <ColHd label="Latest" col="latest" align="right" />
              <ColHd label="Vs entry" col="vsPivotPct" align="right" />
              <ColHd label="Workflow" col="workflow" align="center" />
              <ColHd label="Results" col="results" align="center" />
              <th
                className="px-3 py-2 text-right text-xs font-medium text-muted-foreground uppercase tracking-wide"
                aria-hidden
              />
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {sorted.map(({ row, pivot }) => {
              const sym = row.symbol!;
              const sel = sym === selectedTicker;
              const st = getStatus(sym);
              const inFilter = filteredSymbolSet.has(sym);
              const q = quotes[sym];
              const latest = q?.price ?? null;
              const d = latest != null ? latest - pivot.price : null;
              const dp =
                d != null && Math.abs(pivot.price) > 1e-9
                  ? (d / pivot.price) * 100
                  : null;
              const distColor =
                d == null
                  ? "text-muted-foreground"
                  : d >= 0
                    ? "text-emerald-600 dark:text-emerald-400"
                    : "text-rose-500";
              const loggingThis = logTradeTicker === sym;
              return (
                <React.Fragment key={row.scan_row_id}>
                  <tr
                    onClick={() => onSelect(sym)}
                    onDoubleClick={() => onOpenWorkflowEditor(sym)}
                    className={`cursor-pointer transition-colors ${sel ? "bg-foreground/10 ring-1 ring-inset ring-foreground/20" : "hover:bg-muted/30"}`}
                  >
                    <td className="px-3 py-2 font-mono font-semibold whitespace-nowrap">
                      <span className="flex items-center gap-1.5">
                        {activePositionSymbols.has(sym) && (
                          <span className="shrink-0 w-1.5 h-1.5 rounded-full bg-emerald-400" title="Active position" />
                        )}
                        {sym}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-muted-foreground whitespace-nowrap">
                      {pivot.date}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      ${pivot.price.toFixed(2)}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums font-medium">
                      {latest != null ? `$${latest.toFixed(2)}` : "—"}
                    </td>
                    <td
                      className={`px-3 py-2 text-right tabular-nums whitespace-nowrap ${distColor}`}
                    >
                      {d == null || dp == null
                        ? "—"
                        : `${d >= 0 ? "+" : ""}${d.toFixed(2)} (${dp >= 0 ? "+" : ""}${dp.toFixed(2)}%)`}
                    </td>
                    <td className="px-3 py-2 text-center">
                      <span className="text-xs text-muted-foreground capitalize">
                        {st}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-center">
                      {inFilter ? (
                        <span className="text-[11px] text-emerald-600 dark:text-emerald-400">
                          Shown
                        </span>
                      ) : (
                        <span
                          className="text-[11px] text-muted-foreground"
                          title="Hidden by current Results filters — still on chart list"
                        >
                          Outside filter
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-right whitespace-nowrap">
                      <div className="flex items-center justify-end gap-3">
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            setLogTradeTicker(loggingThis ? null : sym);
                          }}
                          className={`flex items-center gap-1 text-xs font-medium transition-colors ${loggingThis ? "text-muted-foreground hover:text-foreground" : "text-emerald-600 hover:text-emerald-700 dark:text-emerald-400 dark:hover:text-emerald-300"}`}
                          title="Log a trade for this ticker"
                        >
                          <Plus className="w-3 h-3" />
                          {loggingThis ? "Cancel" : "Log trade"}
                        </button>
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            onSelect(sym);
                            onGoToCharts();
                          }}
                          className="text-xs font-medium text-sky-600 hover:underline dark:text-sky-400"
                        >
                          Open chart
                        </button>
                      </div>
                    </td>
                  </tr>
                  {loggingThis && (
                    <tr>
                      <td colSpan={8} className="px-3 py-3 bg-muted/20">
                        <LogTradeForm
                          ticker={sym}
                          defaultPrice={latest}
                          onDone={() => setLogTradeTicker(null)}
                          onCancel={() => setLogTradeTicker(null)}
                        />
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}