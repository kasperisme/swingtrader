export type TradeLedgerRow = {
  ticker: string;
  currency: string;
  quantity: number | string;
  price_per_unit: number | string;
  side: "buy" | "sell";
  executed_at: string;
};

export type PortfolioPosition = {
  ticker: string;
  currency: string;
  /** Positive = long shares, negative = short. */
  netQty: number;
  /** Long: average purchase price. Short: average entry (sell) price. */
  avgEntry: number;
  sideLabel: "long" | "short";
};

function toNum(v: number | string): number {
  const n = typeof v === "number" ? v : parseFloat(String(v));
  return Number.isFinite(n) ? n : 0;
}

/**
 * Replays trades in chronological order with average-cost inventory.
 * Matches ledger semantics: buy/sell × long/short as documented in user_trades migration.
 */
export function buildPortfolioFromTrades(trades: TradeLedgerRow[]): PortfolioPosition[] {
  const byKey = new Map<string, { q: number; avg: number; currency: string; ticker: string }>();

  const chronological = [...trades].sort(
    (a, b) => new Date(a.executed_at).getTime() - new Date(b.executed_at).getTime(),
  );

  for (const t of chronological) {
    const ticker = String(t.ticker).trim().toUpperCase();
    if (!ticker) continue;
    const currency = (String(t.currency || "USD").trim().toUpperCase() || "USD") as string;
    const key = `${ticker}\0${currency}`;
    const qty = toNum(t.quantity);
    const price = toNum(t.price_per_unit);
    if (qty <= 0 || !Number.isFinite(price) || price < 0) continue;

    let state = byKey.get(key);
    if (!state) {
      state = { q: 0, avg: 0, currency, ticker };
      byKey.set(key, state);
    }

    if (t.side === "buy") {
      if (state.q >= 0) {
        const newQ = state.q + qty;
        state.avg = newQ === 0 ? 0 : (state.q * state.avg + qty * price) / newQ;
        state.q = newQ;
      } else {
        const shortAbs = -state.q;
        if (qty <= shortAbs) {
          state.q += qty;
        } else {
          const excess = qty - shortAbs;
          state.q = excess;
          state.avg = price;
        }
      }
    } else {
      if (state.q > 0) {
        if (qty <= state.q) {
          state.q -= qty;
        } else {
          const excess = qty - state.q;
          state.q = -excess;
          state.avg = price;
        }
      } else {
        const newQ = state.q - qty;
        if (state.q === 0) {
          state.q = -qty;
          state.avg = price;
        } else {
          const oldAbs = -state.q;
          const newAbs = -newQ;
          state.avg = (oldAbs * state.avg + qty * price) / newAbs;
          state.q = newQ;
        }
      }
    }
  }

  const EPS = 1e-8;
  const out: PortfolioPosition[] = [];
  for (const s of byKey.values()) {
    if (Math.abs(s.q) < EPS) continue;
    out.push({
      ticker: s.ticker,
      currency: s.currency,
      netQty: s.q,
      avgEntry: s.avg,
      sideLabel: s.q > 0 ? "long" : "short",
    });
  }
  out.sort((a, b) => a.ticker.localeCompare(b.ticker));
  return out;
}
