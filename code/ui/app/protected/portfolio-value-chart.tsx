"use client";

import { useEffect, useState, useMemo } from "react";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { Loader2 } from "lucide-react";
import { fmpGetOhlc } from "@/app/actions/fmp";
import type { UserTradeRow } from "./ops-center-ui";
import { computePortfolioValueSeries, type PortfolioValuePoint } from "./portfolio-value-series";

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

type CustomTooltipProps = {
  active?: boolean;
  payload?: { value: number }[];
  label?: string;
  currency: string;
};

function CustomTooltip({ active, payload, label, currency }: CustomTooltipProps) {
  if (!active || !payload?.length || !label) return null;
  return (
    <div className="rounded-lg border border-border bg-card px-3 py-2 shadow-md text-xs">
      <p className="text-muted-foreground">{label}</p>
      <p className="font-semibold tabular-nums mt-0.5">
        {fmtCcy(currency, payload[0].value)}
      </p>
    </div>
  );
}

export function PortfolioValueChart({ trades }: { trades: UserTradeRow[] }) {
  const [data, setData] = useState<PortfolioValuePoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const positions = useMemo(() => {
    const map = new Map<string, string>();
    for (const t of trades) {
      const ticker = String(t.ticker).trim().toUpperCase();
      if (ticker) map.set(ticker, t.currency);
    }
    return map;
  }, [trades]);

  const currency = useMemo(() => {
    const ccys = new Set(positions.values());
    return ccys.size === 1 ? [...ccys][0] : "USD";
  }, [positions]);

  useEffect(() => {
    if (trades.length === 0 || positions.size === 0) {
      setData([]);
      setLoading(false);
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError(null);

    async function fetchOhlc() {
      const ohlcByTicker: Record<string, import("@/app/actions/fmp").FmpOhlcBar[]> = {};
      const tickers = [...positions.keys()];

      const earliestTrade = [...trades].sort(
        (a, b) => new Date(a.executed_at).getTime() - new Date(b.executed_at).getTime(),
      )[0];
      const from = new Date(earliestTrade.executed_at);
      from.setMonth(from.getMonth() - 1);
      const fromStr = from.toISOString().slice(0, 10);
      const toStr = new Date().toISOString().slice(0, 10);

      for (const ticker of tickers) {
        try {
          const res = await fmpGetOhlc(ticker, "1day", { from: fromStr, to: toStr });
          if (res.ok && res.data.length > 0) {
            ohlcByTicker[ticker] = res.data;
          }
        } catch {
          // skip failed tickers
        }
      }

      if (cancelled) return;

      const series = computePortfolioValueSeries(trades, ohlcByTicker);
      setData(series);
    }

    void fetchOhlc().catch(() => {
      if (!cancelled) setError("Failed to load chart data");
    }).finally(() => {
      if (!cancelled) setLoading(false);
    });

    return () => {
      cancelled = true;
    };
  }, [trades, positions]);

  if (trades.length === 0) return null;

  if (loading) {
    return (
      <div className="rounded-xl border border-border bg-card p-5">
        <h2 className="text-lg font-semibold mb-4">Portfolio Value</h2>
        <div className="h-[220px] flex items-center justify-center text-muted-foreground text-sm">
          <Loader2 className="h-4 w-4 animate-spin mr-2" />
          Loading chart…
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-xl border border-border bg-card p-5">
        <h2 className="text-lg font-semibold mb-4">Portfolio Value</h2>
        <p className="text-sm text-rose-600 dark:text-rose-400">{error}</p>
      </div>
    );
  }

  if (data.length === 0) return null;

  const prevValue = data.length > 1 ? data[data.length - 2].value : null;
  const lastValue = data[data.length - 1].value;
  const valueChange = prevValue != null ? lastValue - prevValue : null;
  const isPositive = valueChange != null ? valueChange >= 0 : lastValue >= 0;

  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold">Portfolio Value</h2>
        <div className="text-right">
          <p className="text-lg font-semibold tabular-nums">
            {fmtCcy(currency, lastValue)}
          </p>
          {valueChange != null && (
            <p
              className={`text-xs tabular-nums ${
                isPositive
                  ? "text-emerald-600 dark:text-emerald-400"
                  : "text-rose-600 dark:text-rose-400"
              }`}
            >
              {isPositive ? "+" : ""}
              {fmtCcy(currency, valueChange)}
            </p>
          )}
        </div>
      </div>
      <div className="h-[220px]">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 2, right: 4, left: 4, bottom: 0 }}>
            <defs>
              <linearGradient id="portfolioGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="hsl(45 93% 47%)" stopOpacity={0.3} />
                <stop offset="100%" stopColor="hsl(45 93% 47%)" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
            <XAxis
              dataKey="date"
              tickFormatter={(v: string) => v.slice(5, 10)}
              tick={{ fontSize: 11 }}
              className="fill-muted-foreground"
              tickLine={false}
              axisLine={false}
            />
            <YAxis
              tickFormatter={(v: number) => fmtCcy(currency, v)}
              tick={{ fontSize: 11 }}
              className="fill-muted-foreground"
              tickLine={false}
              axisLine={false}
              width={80}
              domain={["auto", "auto"]}
            />
            <Tooltip content={<CustomTooltip currency={currency} />} />
            <Area
              type="monotone"
              dataKey="value"
              stroke="hsl(45 93% 47%)"
              strokeWidth={2}
              fill="url(#portfolioGradient)"
              dot={false}
              activeDot={{ r: 4, fill: "hsl(45 93% 47%)", stroke: "hsl(var(--background))", strokeWidth: 2 }}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}