"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  Loader2,
  ArrowRight,
  TrendingUp,
  BarChart3,
  Network,
} from "lucide-react";
import { buildPortfolioFromTrades, type PortfolioPosition } from "@/app/protected/trades/portfolio-from-trades";
import { fmpGetQuote } from "@/app/actions/fmp";
import { PortfolioValueChart } from "./portfolio-value-chart";

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

function PortfolioTable({ trades }: { trades: UserTradeRow[] }) {
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
          const res = await fmpGetQuote(sym);
          if (!res.ok) {
            next[sym] = null;
            continue;
          }
          const data: unknown = res.data;
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
      <div className="border-b border-border pb-4">
        <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground/50 mb-1">Portfolio</p>
        <p className="text-sm text-muted-foreground">
          No open positions.{" "}
          <Link href="/protected/trades" className="text-foreground underline underline-offset-4 hover:text-amber-500 transition-colors">
            Log your first trade
          </Link>
          .
        </p>
      </div>
    );
  }

  const plClass = (n: number | null) =>
    n == null ? "" : n > 0 ? "text-emerald-500" : n < 0 ? "text-rose-500" : "";

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground/50">Portfolio</p>
        {marksLoading && (
          <span className="inline-flex items-center gap-1 text-xs text-muted-foreground/50">
            <Loader2 className="h-3 w-3 animate-spin" />
            updating
          </span>
        )}
      </div>

      {/* Mobile: position cards */}
      <div className="flex flex-col divide-y divide-border md:hidden">
        {positions.map((p) => {
          const mark = marks[p.ticker] ?? null;
          const smv = signedMarkValue(p, mark);
          const sur = unrealizedAtMark(p, mark);
          const isLong = p.sideLabel === "long";
          const stripColor = isLong ? "bg-emerald-500" : "bg-rose-500";
          return (
            <div key={`${p.ticker}-${p.currency}`} className="flex gap-3 py-2.5">
              <div className={`w-0.5 shrink-0 rounded-full ${stripColor}`} />
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="font-mono text-sm font-semibold">{p.ticker}</span>
                  <span className={`tabular-nums text-sm font-semibold ${plClass(sur)}`}>
                    {sur != null ? fmtCcy(p.currency, sur) : "—"}
                  </span>
                </div>
                <div className="mt-0.5 flex items-center justify-between gap-2 text-xs text-muted-foreground">
                  <span className="capitalize">
                    {p.sideLabel} · {typeof p.netQty === "number" ? p.netQty.toLocaleString("en-US", { maximumFractionDigits: 4 }) : p.netQty} @ {fmtCcy(p.currency, p.avgEntry)}
                  </span>
                  <span className="tabular-nums">
                    {mark != null ? `last ${fmtCcy(p.currency, mark)}` : "—"}
                  </span>
                </div>
                {smv != null && (
                  <div className="mt-0.5 text-right text-xs text-muted-foreground/60 tabular-nums">
                    value {fmtCcy(p.currency, smv)}
                  </div>
                )}
              </div>
            </div>
          );
        })}
        {singlePortfolioCcy && totals.nUr > 0 && (
          <div className="flex items-center justify-between py-2 text-xs">
            <span className="text-muted-foreground/50 uppercase tracking-wide font-medium">Total unrealized</span>
            <span className={`tabular-nums font-semibold ${plClass(totals.ur)}`}>
              {fmtCcy(singlePortfolioCcy, totals.ur)}
            </span>
          </div>
        )}
      </div>

      {/* Desktop: compact table */}
      <div className="hidden overflow-x-auto md:block">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-border">
              <th className="pb-1.5 text-left font-medium text-muted-foreground/50 uppercase tracking-wide">Ticker</th>
              <th className="pb-1.5 text-left font-medium text-muted-foreground/50 uppercase tracking-wide">Book</th>
              <th className="pb-1.5 pr-3 text-right font-medium text-muted-foreground/50 uppercase tracking-wide">Qty</th>
              <th className="pb-1.5 pr-3 text-right font-medium text-muted-foreground/50 uppercase tracking-wide">Avg entry</th>
              <th className="pb-1.5 pr-3 text-right font-medium text-muted-foreground/50 uppercase tracking-wide">Last</th>
              <th className="pb-1.5 pr-3 text-right font-medium text-muted-foreground/50 uppercase tracking-wide">Value</th>
              <th className="pb-1.5 text-right font-medium text-muted-foreground/50 uppercase tracking-wide">Unrealized</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border/50">
            {positions.map((p) => {
              const mark = marks[p.ticker] ?? null;
              const smv = signedMarkValue(p, mark);
              const sur = unrealizedAtMark(p, mark);
              return (
                <tr key={`${p.ticker}-${p.currency}`} className="hover:bg-muted/10">
                  <td className="py-1.5 pr-3 font-mono font-semibold">{p.ticker}</td>
                  <td className="py-1.5 pr-3 capitalize text-muted-foreground">{p.sideLabel}</td>
                  <td className="py-1.5 pr-3 text-right tabular-nums text-muted-foreground">
                    {typeof p.netQty === "number" ? p.netQty.toLocaleString("en-US", { maximumFractionDigits: 6 }) : String(p.netQty)}
                    <span className="ml-1 text-muted-foreground/40">{p.currency}</span>
                  </td>
                  <td className="py-1.5 pr-3 text-right tabular-nums">{fmtCcy(p.currency, p.avgEntry)}</td>
                  <td className="py-1.5 pr-3 text-right tabular-nums text-muted-foreground">
                    {mark != null ? fmtCcy(p.currency, mark) : "—"}
                  </td>
                  <td className="py-1.5 pr-3 text-right tabular-nums">
                    {smv != null ? fmtCcy(p.currency, smv) : "—"}
                  </td>
                  <td className={`py-1.5 text-right tabular-nums font-medium ${plClass(sur)}`}>
                    {sur != null ? fmtCcy(p.currency, sur) : "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
          {singlePortfolioCcy && (totals.nMv > 0 || totals.nUr > 0) && (
            <tfoot>
              <tr className="border-t border-border">
                <td colSpan={5} className="py-1.5 text-right text-muted-foreground/40 uppercase tracking-wide">Total</td>
                <td className="py-1.5 pr-3 text-right tabular-nums">
                  {totals.nMv > 0 ? fmtCcy(singlePortfolioCcy, totals.mv) : "—"}
                </td>
                <td className={`py-1.5 text-right tabular-nums font-medium ${plClass(totals.ur)}`}>
                  {totals.nUr > 0 ? fmtCcy(singlePortfolioCcy, totals.ur) : "—"}
                </td>
              </tr>
            </tfoot>
          )}
        </table>
      </div>

      {portfolioCurrencies.size > 1 && (
        <p className="text-xs text-amber-500/70">
          Multi-currency — portfolio totals hidden.
        </p>
      )}
    </div>
  );
}

const quickLinks = [
  {
    href: "/protected/news-trends",
    label: "News Trends",
    description: "Track trending topics and sentiment shifts",
    icon: TrendingUp,
  },
  {
    href: "/protected/screenings",
    label: "Screenings",
    description: "Trend template and fundamental scans",
    icon: BarChart3,
  },
  {
    href: "/protected/relations",
    label: "Network Graph",
    description: "Explore entity relationships and connections",
    icon: Network,
  },
];

export function OpsCenterUI({ initialTrades }: { initialTrades: UserTradeRow[] }) {
  return (
    <div className="space-y-6">
      <PortfolioTable trades={initialTrades} />
      <PortfolioValueChart trades={initialTrades} />

      <div className="flex flex-col divide-y divide-border/60 sm:flex-row sm:divide-x sm:divide-y-0">
        {quickLinks.map(({ href, label, description, icon: Icon }) => (
          <Link
            key={href}
            href={href}
            className="group flex items-center gap-3 py-3 pr-6 text-sm transition-colors hover:text-amber-500 sm:pl-6 first:pl-0"
          >
            <Icon className="h-4 w-4 shrink-0 text-muted-foreground/50 transition-colors group-hover:text-amber-500" aria-hidden />
            <div className="min-w-0">
              <span className="font-medium">{label}</span>
              <p className="text-xs text-muted-foreground truncate">{description}</p>
            </div>
            <ArrowRight className="ml-auto h-3.5 w-3.5 shrink-0 text-muted-foreground/30 transition-colors group-hover:text-amber-500" />
          </Link>
        ))}
      </div>
    </div>
  );
}