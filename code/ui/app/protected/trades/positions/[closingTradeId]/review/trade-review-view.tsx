"use client";

import { useMemo, useState } from "react";
import { CandlestickSvg } from "@/components/ticker-charts/candlestick-svg";
import { TradeReviewChat } from "@/components/trade-review-chat";
import type {
  ChartAnnotation,
  OhlcBar,
} from "@/components/ticker-charts/types";
import type { ChartAiChatMessage } from "@/app/actions/chart-workspace";
import type { ClosedPosition } from "@/lib/trades/closed-positions";

function fmtCcy(currency: string, n: number): string {
  const c = currency.trim().toUpperCase();
  if (!/^[A-Z]{3}$/.test(c)) {
    return n.toLocaleString("en-US", { maximumFractionDigits: 2 });
  }
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: c,
      maximumFractionDigits: 2,
    }).format(n);
  } catch {
    return n.toLocaleString("en-US", { maximumFractionDigits: 2 });
  }
}

function fmtDate(iso: string): string {
  return iso.slice(0, 10);
}

export interface TradeReviewViewProps {
  closingTradeId: number;
  position: ClosedPosition;
  initialMessages: ChartAiChatMessage[];
  initialSummary: string | null;
  ohlcData: OhlcBar[];
  tradeMarkers: Array<{
    date: string;
    price: number;
    side: "buy" | "sell";
    position_side: "long" | "short";
  }>;
}

export function TradeReviewView({
  closingTradeId,
  position,
  initialMessages,
  ohlcData,
  tradeMarkers,
}: TradeReviewViewProps) {
  const [messages, setMessages] = useState<ChartAiChatMessage[]>(initialMessages);

  const annotations: ChartAnnotation[] = useMemo(
    () => [
      {
        id: "review-entry",
        type: "horizontal",
        price: position.avgEntry,
        role: "entry",
        label: `Avg entry ${position.avgEntry.toFixed(2)}`,
      },
      {
        id: "review-exit",
        type: "horizontal",
        price: position.avgExit,
        role: position.realizedPnl >= 0 ? "target" : "stop",
        label: `Avg exit ${position.avgExit.toFixed(2)}`,
      },
    ],
    [position],
  );

  const dateRange = useMemo(() => {
    const fromD = new Date(position.openedAt);
    fromD.setUTCDate(fromD.getUTCDate() - 10);
    const toD = new Date(position.closedAt);
    toD.setUTCDate(toD.getUTCDate() + 10);
    return {
      from: fromD.toISOString().slice(0, 10),
      to: toD.toISOString().slice(0, 10),
    };
  }, [position]);

  const pnlPositive = position.realizedPnl >= 0;
  const pnlClass = pnlPositive
    ? "text-emerald-600 dark:text-emerald-400"
    : "text-rose-600 dark:text-rose-400";

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[1fr_420px] gap-4 min-h-[600px]">
      {/* Left: position summary + chart */}
      <div className="flex flex-col gap-4 min-w-0">
        <div className="rounded-xl border border-border bg-card p-5">
          <div className="flex flex-wrap items-baseline justify-between gap-3">
            <div className="flex items-baseline gap-3">
              <h2 className="text-xl font-bold font-mono tracking-tight">
                {position.ticker}
              </h2>
              <span
                className={
                  "rounded px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide " +
                  (position.side === "long"
                    ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400"
                    : "bg-rose-500/15 text-rose-700 dark:text-rose-400")
                }
              >
                {position.side}
              </span>
              {position.isPaper ? (
                <span className="rounded bg-amber-500/15 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-amber-700 dark:text-amber-400">
                  Paper
                </span>
              ) : null}
            </div>
            <div className="flex flex-col items-end">
              <span className={`text-lg font-semibold tabular-nums ${pnlClass}`}>
                {pnlPositive ? "+" : ""}
                {fmtCcy(position.currency, position.realizedPnl)}
              </span>
              <span className={`text-xs tabular-nums ${pnlClass}`}>
                {pnlPositive ? "+" : ""}
                {(position.realizedPnlPct * 100).toFixed(2)}%
              </span>
            </div>
          </div>
          <dl className="mt-4 grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
            <div>
              <dt className="text-[11px] uppercase tracking-wide text-muted-foreground">
                Qty
              </dt>
              <dd className="font-medium tabular-nums">{position.qty}</dd>
            </div>
            <div>
              <dt className="text-[11px] uppercase tracking-wide text-muted-foreground">
                Avg entry
              </dt>
              <dd className="font-medium tabular-nums">
                {fmtCcy(position.currency, position.avgEntry)}
              </dd>
            </div>
            <div>
              <dt className="text-[11px] uppercase tracking-wide text-muted-foreground">
                Avg exit
              </dt>
              <dd className="font-medium tabular-nums">
                {fmtCcy(position.currency, position.avgExit)}
              </dd>
            </div>
            <div>
              <dt className="text-[11px] uppercase tracking-wide text-muted-foreground">
                Held
              </dt>
              <dd className="font-medium tabular-nums">
                {position.holdingDays.toFixed(1)}d
              </dd>
            </div>
            <div>
              <dt className="text-[11px] uppercase tracking-wide text-muted-foreground">
                Opened
              </dt>
              <dd className="font-medium tabular-nums text-muted-foreground">
                {fmtDate(position.openedAt)}
              </dd>
            </div>
            <div>
              <dt className="text-[11px] uppercase tracking-wide text-muted-foreground">
                Closed
              </dt>
              <dd className="font-medium tabular-nums text-muted-foreground">
                {fmtDate(position.closedAt)}
              </dd>
            </div>
            <div>
              <dt className="text-[11px] uppercase tracking-wide text-muted-foreground">
                Open fills
              </dt>
              <dd className="font-medium tabular-nums">
                {position.openTradeIds.length}
              </dd>
            </div>
            <div>
              <dt className="text-[11px] uppercase tracking-wide text-muted-foreground">
                Close fills
              </dt>
              <dd className="font-medium tabular-nums">
                {position.closeTradeIds.length}
              </dd>
            </div>
          </dl>
        </div>

        <div className="rounded-xl border border-border bg-card p-3 overflow-hidden">
          <p className="px-2 pb-2 text-[11px] uppercase tracking-wide text-muted-foreground">
            Price action around the trade
          </p>
          <div className="h-[380px]">
            <CandlestickSvg
              symbol={position.ticker}
              annotations={annotations}
              tradeMarkers={tradeMarkers}
              dateRange={dateRange}
              interval="1day"
              fillContainer
            />
          </div>
        </div>
      </div>

      {/* Right: AI review chat */}
      <div className="rounded-xl border border-border bg-card overflow-hidden flex flex-col min-h-[600px] lg:max-h-[calc(100vh-200px)]">
        <TradeReviewChat
          closingTradeId={closingTradeId}
          ticker={position.ticker}
          ohlcData={ohlcData}
          messages={messages}
          setMessages={setMessages}
          autoStart={initialMessages.length === 0}
        />
      </div>
    </div>
  );
}
