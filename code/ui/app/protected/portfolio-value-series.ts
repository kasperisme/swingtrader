import type { UserTradeRow } from "./ops-center-ui";
import type { FmpOhlcBar } from "@/app/actions/fmp";

export type PortfolioValuePoint = {
  date: string;
  value: number;
};

export function computePortfolioValueSeries(
  trades: UserTradeRow[],
  ohlcByTicker: Record<string, FmpOhlcBar[]>,
): PortfolioValuePoint[] {
  if (trades.length === 0) return [];

  const chronological = [...trades].sort(
    (a, b) => new Date(a.executed_at).getTime() - new Date(b.executed_at).getTime(),
  );

  const firstTradeDate = new Date(chronological[0].executed_at);
  const fromDate = firstTradeDate.toISOString().slice(0, 10);

  const ohlcMapByTicker = new Map<string, Map<string, number>>();
  for (const [ticker, bars] of Object.entries(ohlcByTicker)) {
    const dateMap = new Map<string, number>();
    for (const bar of bars) {
      const d = bar.date.slice(0, 10);
      if (Number.isFinite(bar.close)) {
        dateMap.set(d, bar.close);
      }
    }
    ohlcMapByTicker.set(ticker.toUpperCase(), dateMap);
  }

  const allDateStrings = new Set<string>();
  for (const dateMap of ohlcMapByTicker.values()) {
    for (const d of dateMap.keys()) {
      if (d >= fromDate) allDateStrings.add(d);
    }
  }
  const dates = [...allDateStrings].sort();
  if (dates.length === 0) return [];

  interface PositionState {
    qty: number;
    currency: string;
  }
  const positions = new Map<string, PositionState>();
  let tradeIdx = 0;

  function toNum(v: number | string): number {
    const n = typeof v === "number" ? v : parseFloat(String(v));
    return Number.isFinite(n) ? n : 0;
  }

  function applyTrade(t: UserTradeRow) {
    const ticker = String(t.ticker).trim().toUpperCase();
    if (!ticker) return;
    const key = `${ticker}\0${t.currency}`;
    const qty = toNum(t.quantity);
    const price = toNum(t.price_per_unit);
    if (qty <= 0 || !Number.isFinite(price) || price < 0) return;

    let state = positions.get(key);
    if (!state) {
      state = { qty: 0, currency: t.currency };
      positions.set(key, state);
    }

    if (t.side === "buy") {
      if (state.qty >= 0) {
        state.qty += qty;
      } else {
        const shortAbs = -state.qty;
        if (qty <= shortAbs) {
          state.qty += qty;
        } else {
          state.qty = qty - shortAbs;
        }
      }
    } else {
      if (state.qty > 0) {
        if (qty <= state.qty) {
          state.qty -= qty;
        } else {
          state.qty = -(qty - state.qty);
        }
      } else {
        state.qty -= qty;
      }
    }
  }

  const result: PortfolioValuePoint[] = [];
  const prevCloseCache = new Map<string, number>();

  for (const date of dates) {
    while (
      tradeIdx < chronological.length &&
      chronological[tradeIdx].executed_at.slice(0, 10) <= date
    ) {
      applyTrade(chronological[tradeIdx]);
      tradeIdx++;
    }

    let dayValue = 0;
    let hasValue = false;

    for (const [key, state] of positions) {
      if (Math.abs(state.qty) < 1e-8) continue;
      const ticker = key.split("\0")[0];
      const dateMap = ohlcMapByTicker.get(ticker);
      let price: number | undefined;
      if (dateMap) {
        price = dateMap.get(date);
      }
      if (price == null) {
        const cacheKey = ticker;
        const prev = prevCloseCache.get(cacheKey);
        if (prev != null) {
          price = prev;
        }
      }
      if (price != null && Number.isFinite(price)) {
        dayValue += state.qty * price;
        hasValue = true;
        const cacheKey = ticker;
        prevCloseCache.set(cacheKey, price);
      }
    }

    if (hasValue) {
      result.push({ date, value: dayValue });
    }
  }

  return result;
}