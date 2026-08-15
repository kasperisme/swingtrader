import { describe, expect, it } from "vitest";
import {
  buildPortfolioFromTrades,
  type TradeLedgerRow,
} from "@/app/protected/trades/portfolio-from-trades";

/**
 * The close button appends an offsetting trade instead of editing history, so
 * the only thing that makes a position "closed" is the ledger replay landing on
 * zero. That is arithmetic, not UI — so assert it directly.
 *
 * Mirrors closingTradeFor() in trades-ui.tsx: long closes with a sell, short
 * covers with a buy, quantity = |netQty|, price = the live mark.
 */
function closingTradeFor(p: { netQty: number; ticker: string; currency: string }, mark: number): TradeLedgerRow {
  return {
    ticker: p.ticker,
    currency: p.currency,
    quantity: Math.abs(p.netQty),
    price_per_unit: mark,
    side: p.netQty > 0 ? "sell" : "buy",
    executed_at: "2026-08-15T12:00:00.000Z",
  };
}

const T = (
  side: "buy" | "sell",
  quantity: number,
  price: number,
  executed_at: string,
): TradeLedgerRow => ({
  ticker: "NVDA",
  currency: "USD",
  quantity,
  price_per_unit: price,
  side,
  executed_at,
});

describe("close position", () => {
  it("flattens a long built from multiple buys", () => {
    const trades = [
      T("buy", 10, 100, "2026-01-05T10:00:00.000Z"),
      T("buy", 5, 120, "2026-02-05T10:00:00.000Z"),
    ];
    const [pos] = buildPortfolioFromTrades(trades);
    expect(pos.netQty).toBe(15);
    expect(pos.sideLabel).toBe("long");

    const closed = buildPortfolioFromTrades([...trades, closingTradeFor(pos, 150)]);
    // A flat position drops out of the portfolio entirely.
    expect(closed.find((p) => p.ticker === "NVDA" && p.netQty !== 0)).toBeUndefined();
  });

  it("covers a short with a buy", () => {
    const trades = [T("sell", 8, 200, "2026-03-01T10:00:00.000Z")];
    const [pos] = buildPortfolioFromTrades(trades);
    expect(pos.netQty).toBe(-8);
    expect(pos.sideLabel).toBe("short");

    const t = closingTradeFor(pos, 180);
    expect(t.side).toBe("buy");
    expect(t.quantity).toBe(8);

    const closed = buildPortfolioFromTrades([...trades, t]);
    expect(closed.find((p) => p.ticker === "NVDA" && p.netQty !== 0)).toBeUndefined();
  });

  it("does not flip the position past zero on a partially-closed long", () => {
    const trades = [
      T("buy", 10, 100, "2026-01-05T10:00:00.000Z"),
      T("sell", 4, 130, "2026-04-05T10:00:00.000Z"),
    ];
    const [pos] = buildPortfolioFromTrades(trades);
    expect(pos.netQty).toBe(6);

    // Closes the REMAINING 6, not the original 10 — the button reads netQty.
    const t = closingTradeFor(pos, 140);
    expect(t.quantity).toBe(6);
    const closed = buildPortfolioFromTrades([...trades, t]);
    expect(closed.find((p) => p.ticker === "NVDA" && p.netQty !== 0)).toBeUndefined();
  });

  it("leaves an unrelated ticker untouched", () => {
    const trades: TradeLedgerRow[] = [
      T("buy", 10, 100, "2026-01-05T10:00:00.000Z"),
      { ...T("buy", 3, 50, "2026-01-06T10:00:00.000Z"), ticker: "AMD" },
    ];
    const nvda = buildPortfolioFromTrades(trades).find((p) => p.ticker === "NVDA")!;
    const closed = buildPortfolioFromTrades([...trades, closingTradeFor(nvda, 150)]);
    const amd = closed.find((p) => p.ticker === "AMD");
    expect(amd?.netQty).toBe(3);
  });
});
