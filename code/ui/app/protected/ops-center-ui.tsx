"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  Briefcase,
  Loader2,
  ArrowRight,
  Newspaper,
  BarChart3,
  BookOpen,
} from "lucide-react";
import { buildPortfolioFromTrades, type PortfolioPosition } from "@/app/protected/trades/portfolio-from-trades";
import { fmpGetQuote } from "@/app/actions/fmp";

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
      <div className="rounded-xl border border-border bg-card p-5">
        <h2 className="text-lg font-semibold flex items-center gap-2">
          <Briefcase className="h-5 w-5 opacity-80" aria-hidden />
          Portfolio
        </h2>
        <p className="text-sm text-muted-foreground mt-2">
          No open positions yet.{" "}
          <Link href="/protected/trades" className="text-foreground underline underline-offset-4 hover:text-amber-500 transition-colors">
            Log your first trade
          </Link>{" "}
          to build a position.
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
                  <td className="px-3 py-2 text-right tabular-nums">
                    {typeof p.netQty === "number"
                      ? p.netQty.toLocaleString("en-US", { maximumFractionDigits: 6 })
                      : String(p.netQty)}
                  </td>
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

const quickLinks = [
  {
    href: "/protected/articles",
    label: "Articles",
    description: "Semantic search across the news pipeline",
    icon: Newspaper,
  },
  {
    href: "/protected/screenings",
    label: "Screenings",
    description: "Trend template and fundamental scans",
    icon: BarChart3,
  },
  {
    href: "/protected/daily-narrative",
    label: "Daily Narrative",
    description: "AI briefing for your positions",
    icon: BookOpen,
  },
];

export function OpsCenterUI({ initialTrades }: { initialTrades: UserTradeRow[] }) {
  return (
    <div className="space-y-8">
      <PortfolioTable trades={initialTrades} />

      <section>
        <h2 className="text-sm font-semibold uppercase tracking-widest text-muted-foreground mb-3">Quick links</h2>
        <div className="grid gap-3 sm:grid-cols-3">
          {quickLinks.map(({ href, label, description, icon: Icon }) => (
            <Link
              key={href}
              href={href}
              className="group rounded-xl border border-border/80 bg-card/40 p-4 transition-colors duration-200 hover:border-amber-500/30 hover:bg-card/70"
            >
              <div className="flex items-start justify-between gap-2">
                <div>
                  <div className="flex items-center gap-2">
                    <Icon className="h-4 w-4 text-amber-500" aria-hidden />
                    <span className="text-sm font-semibold">{label}</span>
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">{description}</p>
                </div>
                <ArrowRight className="h-4 w-4 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
              </div>
            </Link>
          ))}
        </div>
      </section>
    </div>
  );
}