"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import type { ArenaHolding, ArenaNavPoint, ArenaPosition } from "@/app/actions/arena";
import { PortfolioValue } from "./portfolio-value";

/**
 * The portfolio chart and the holdings table, sharing one selected session.
 *
 * Click a point on the chart and the table below becomes the book as it stood
 * at THAT close — read from the snapshot `mark_to_market` writes on every NAV
 * row, so it is the real historical book rather than today's positions
 * back-projected onto an old price.
 *
 * Without this the two halves disagree in a way that is easy to misread: the
 * chart shows a $78k book in July while the table lists whatever is held now.
 * Selection defaults to the latest session, so the page opens on the live book.
 */

type Props = {
  points: ArenaNavPoint[];
  livePositions: ArenaPosition[];
  startingCash: number;
  colorIndex: number | null;
  nav: number | null;
  cash: number | null;
};

type Row = {
  ticker: string;
  quantity: number;
  avgCost: number;
  mark: number;
  marketValue: number;
  unrealizedPct: number | null;
  unrealizedPnl: number;
};

function fmtMoney(v: number | null | undefined, digits = 0) {
  if (v == null) return "—";
  return `$${v.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}`;
}

function fmtPct(v: number | null | undefined, digits = 2) {
  if (v == null) return "—";
  return `${v >= 0 ? "+" : ""}${(v * 100).toFixed(digits)}%`;
}

function toneFor(v: number | null | undefined) {
  if (v == null) return "text-muted-foreground";
  if (v > 0) return "text-emerald-600 dark:text-emerald-500";
  if (v < 0) return "text-rose-600 dark:text-rose-500";
  return "text-muted-foreground";
}

function fmtDay(iso: string) {
  return new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  });
}

/** A stored snapshot line -> a table row, deriving what the snapshot omits. */
function fromHolding(h: ArenaHolding): Row {
  const pnl = h.quantity * (h.mark - h.avg_cost);
  return {
    ticker: h.ticker,
    quantity: h.quantity,
    avgCost: h.avg_cost,
    mark: h.mark,
    marketValue: h.market_value,
    // Signed by direction: a short that falls in price is a GAIN.
    unrealizedPct: h.avg_cost ? Math.sign(h.quantity) * (h.mark - h.avg_cost) / h.avg_cost : null,
    unrealizedPnl: pnl,
  };
}

function fromLive(p: ArenaPosition): Row {
  return {
    ticker: p.ticker,
    quantity: p.quantity,
    avgCost: p.avg_cost,
    mark: p.last_price ?? p.avg_cost,
    marketValue: p.market_value,
    unrealizedPct: p.unrealized_pct,
    unrealizedPnl: p.unrealized_pnl,
  };
}

export function PortfolioPanel({
  points,
  livePositions,
  startingCash,
  colorIndex,
  nav,
  cash,
}: Props) {
  const sorted = useMemo(
    () => [...points].sort((a, b) => a.as_of.localeCompare(b.as_of)),
    [points],
  );
  const latest = sorted.at(-1) ?? null;
  const [selected, setSelected] = useState<string | null>(null);

  const point = selected
    ? sorted.find((p) => p.as_of === selected) ?? latest
    : latest;
  const isLive = !selected || point?.as_of === latest?.as_of;

  // The live table is authoritative for today (it carries fresher marks than
  // the snapshot written at the close). Past days come from the snapshot.
  const rows: Row[] = useMemo(() => {
    if (isLive && livePositions.length > 0) return livePositions.map(fromLive);
    return (point?.positions?.holdings ?? []).map(fromHolding);
  }, [isLive, livePositions, point]);

  const ordered = [...rows].sort(
    (a, b) => Math.abs(b.marketValue) - Math.abs(a.marketValue),
  );
  const invested = ordered.reduce((n, r) => n + Math.abs(r.marketValue), 0);
  const pnl = ordered.reduce((n, r) => n + r.unrealizedPnl, 0);
  const shownNav = isLive ? nav : point?.nav ?? null;
  const shownCash = isLive ? cash : point?.cash ?? null;
  const stale = point?.positions?.stale_marks ?? [];

  return (
    <>
      <PortfolioValue
        points={points}
        startingCash={startingCash}
        colorIndex={colorIndex}
        selected={point?.as_of ?? null}
        onSelect={(d) => setSelected(d)}
      />

      <div className="mt-10 flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2">
        <h3 className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
          {isLive ? "Open positions" : `Positions on ${fmtDay(point!.as_of)}`}
        </h3>
        {!isLive && (
          <button
            type="button"
            onClick={() => setSelected(null)}
            className="rounded-full border px-2.5 py-0.5 font-mono text-[11px] text-muted-foreground transition-colors hover:border-foreground/30 hover:text-foreground"
          >
            back to today
          </button>
        )}
      </div>

      {!isLive && (
        <p className="mt-1.5 font-mono text-[11px] text-muted-foreground/80">
          The book as it stood at that close. Click the chart to move; marks are
          that session&rsquo;s.
        </p>
      )}

      {ordered.length === 0 ? (
        <p className="mt-4 max-w-[62ch] text-sm text-muted-foreground">
          {isLive
            ? "Holding no positions — all cash."
            : "Held nothing that session — the whole account was in cash."}
          {shownCash != null && ` (${fmtMoney(shownCash)})`}
        </p>
      ) : (
        <div className="-mx-4 mt-4 overflow-x-auto px-4">
          <table className="w-full min-w-[620px] border-collapse text-sm">
            <caption className="sr-only">
              Positions with cost basis, mark, value and unrealised P&amp;L
              {isLive ? " (current)" : ` on ${point!.as_of}`}
            </caption>
            <thead>
              <tr className="border-b text-left font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
                <th scope="col" className="pb-2 pr-4 font-normal">Ticker</th>
                <th scope="col" className="pb-2 pr-4 text-right font-normal">Qty</th>
                <th scope="col" className="pb-2 pr-4 text-right font-normal">Cost</th>
                <th scope="col" className="pb-2 pr-4 text-right font-normal">Mark</th>
                <th scope="col" className="pb-2 pr-4 text-right font-normal">Value</th>
                <th scope="col" className="pb-2 text-right font-normal">Unrealised</th>
              </tr>
            </thead>
            <tbody className="font-mono tabular-nums">
              {ordered.map((r) => (
                <tr key={r.ticker} className="border-b border-border/60">
                  <td className="py-2.5 pr-4">
                    <Link
                      href={`/quote/${r.ticker}`}
                      className="font-medium hover:text-amber-600 dark:hover:text-amber-500"
                    >
                      {r.ticker}
                    </Link>
                    {r.quantity < 0 && (
                      <span className="ml-2 rounded bg-muted px-1 py-0.5 text-[10px] uppercase tracking-wide text-muted-foreground">
                        short
                      </span>
                    )}
                    {stale.includes(r.ticker) && (
                      <span
                        className="ml-2 rounded bg-muted px-1 py-0.5 text-[10px] uppercase tracking-wide text-muted-foreground"
                        title="No bar that session — carried at its last known price"
                      >
                        stale
                      </span>
                    )}
                  </td>
                  <td className="py-2.5 pr-4 text-right">
                    {Math.abs(r.quantity).toLocaleString()}
                  </td>
                  <td className="py-2.5 pr-4 text-right text-muted-foreground">
                    {fmtMoney(r.avgCost, 2)}
                  </td>
                  <td className="py-2.5 pr-4 text-right">{fmtMoney(r.mark, 2)}</td>
                  <td className="py-2.5 pr-4 text-right text-muted-foreground">
                    {fmtMoney(Math.abs(r.marketValue))}
                  </td>
                  <td className={`py-2.5 text-right font-medium ${toneFor(r.unrealizedPct)}`}>
                    {fmtPct(r.unrealizedPct)}
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              {/* `marketValue` is SIGNED — negative for shorts — so the invested
                  total takes absolute values (gross exposure). P&L sums signed,
                  because there the direction is the point. */}
              <tr className="border-t-2 font-mono tabular-nums">
                <td className="py-3 pr-4 text-[11px] uppercase tracking-widest text-muted-foreground">
                  Total
                </td>
                <td className="py-3 pr-4 text-right text-muted-foreground">
                  {ordered.length}
                  <span className="ml-1 text-[11px]">
                    {ordered.length === 1 ? "name" : "names"}
                  </span>
                </td>
                <td className="py-3 pr-4" />
                <td className="py-3 pr-4" />
                <td className="py-3 pr-4 text-right font-medium">{fmtMoney(invested)}</td>
                <td className={`py-3 text-right font-medium ${toneFor(pnl)}`}>
                  {pnl >= 0 ? "+" : "−"}
                  {fmtMoney(Math.abs(pnl))}
                </td>
              </tr>
            </tfoot>
          </table>
        </div>
      )}

      {ordered.length > 0 && shownNav != null && (
        <p className="mt-3 font-mono text-xs text-muted-foreground">
          {fmtMoney(invested)} invested · {Math.round((invested / shownNav) * 100)}% of{" "}
          {fmtMoney(shownNav)} NAV · {fmtMoney(shownCash ?? 0)} cash
        </p>
      )}
    </>
  );
}
