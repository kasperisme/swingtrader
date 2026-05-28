/**
 * Closed-position derivation.
 *
 * A "position" is the time between a (ticker, currency, paper-vs-real) book
 * going from flat to non-zero and back to flat. We replay buys/sells in
 * chronological order using average-cost accounting (same semantics as
 * portfolio-from-trades.ts) and emit one ClosedPosition per round trip.
 *
 * Each ClosedPosition is keyed by the closing trade's id — the trade row that
 * flattens the book — so the URL `/protected/trades/positions/[id]/review`
 * resolves deterministically and can be deep-linked.
 *
 * v1: only fully-flat positions (qty exactly 0 within EPS) are emitted.
 * Partial closes are not reviewable yet.
 */

export type TradeLedgerInput = {
  id: number;
  ticker: string;
  currency: string;
  quantity: number | string;
  price_per_unit: number | string;
  side: "buy" | "sell";
  executed_at: string;
  is_paper: boolean;
};

export type ClosedPosition = {
  /** Closing trade id — stable URL key. */
  positionKey: number;
  ticker: string;
  currency: string;
  isPaper: boolean;
  /** "long" if the position opened with a buy, "short" if with a sell. */
  side: "long" | "short";
  qty: number;
  avgEntry: number;
  avgExit: number;
  openedAt: string;
  closedAt: string;
  holdingDays: number;
  /** Long: (avgExit - avgEntry) * qty. Short: (avgEntry - avgExit) * qty. */
  realizedPnl: number;
  /** Realized P&L as a fraction of entry cost (e.g. 0.12 = +12%). */
  realizedPnlPct: number;
  openTradeIds: number[];
  closeTradeIds: number[];
};

const EPS = 1e-8;

function toNum(v: number | string): number {
  const n = typeof v === "number" ? v : parseFloat(String(v));
  return Number.isFinite(n) ? n : 0;
}

type BookKey = string;

type OpenLeg = {
  ticker: string;
  currency: string;
  isPaper: boolean;
  side: "long" | "short";
  qty: number;
  avgEntry: number;
  openedAt: string;
  openTradeIds: number[];
  /** Sum of entry cost * qty across all opening fills (for avg accuracy). */
  entryCostQty: number;
  /** Sum of exit proceeds * qty across all closing fills. */
  exitProceedsQty: number;
  closedQty: number;
  closeTradeIds: number[];
};

function bookKey(t: TradeLedgerInput): BookKey {
  const ticker = String(t.ticker).trim().toUpperCase();
  const ccy = (String(t.currency || "USD").trim().toUpperCase() || "USD");
  return `${ticker}\0${ccy}\0${t.is_paper ? "P" : "R"}`;
}

/**
 * Replay trades chronologically and yield closed positions.
 *
 * Behavior on flips: if a fill exceeds the open size, we flatten the existing
 * leg first (emit the closed position) and open a new leg with the excess at
 * the flip price. This matches the avg-cost semantics in portfolio-from-trades.
 */
export function deriveClosedPositions(
  trades: TradeLedgerInput[],
): ClosedPosition[] {
  const sorted = [...trades].sort(
    (a, b) => new Date(a.executed_at).getTime() - new Date(b.executed_at).getTime(),
  );

  const open = new Map<BookKey, OpenLeg>();
  const closed: ClosedPosition[] = [];

  function emitClosed(leg: OpenLeg, closingTradeId: number, closedAt: string): void {
    const avgEntry = leg.closedQty > 0 ? leg.entryCostQty / leg.closedQty : 0;
    const avgExit = leg.closedQty > 0 ? leg.exitProceedsQty / leg.closedQty : 0;
    const sideMul = leg.side === "long" ? 1 : -1;
    const realizedPnl = (avgExit - avgEntry) * sideMul * leg.closedQty;
    const entryCost = avgEntry * leg.closedQty;
    const realizedPnlPct = entryCost > 0 ? realizedPnl / entryCost : 0;
    const openedAtMs = new Date(leg.openedAt).getTime();
    const closedAtMs = new Date(closedAt).getTime();
    const holdingDays = Number.isFinite(openedAtMs) && Number.isFinite(closedAtMs)
      ? Math.max(0, (closedAtMs - openedAtMs) / 86_400_000)
      : 0;

    closed.push({
      positionKey: closingTradeId,
      ticker: leg.ticker,
      currency: leg.currency,
      isPaper: leg.isPaper,
      side: leg.side,
      qty: leg.closedQty,
      avgEntry,
      avgExit,
      openedAt: leg.openedAt,
      closedAt,
      holdingDays,
      realizedPnl,
      realizedPnlPct,
      openTradeIds: [...leg.openTradeIds],
      closeTradeIds: [...leg.closeTradeIds],
    });
  }

  for (const t of sorted) {
    const ticker = String(t.ticker).trim().toUpperCase();
    if (!ticker) continue;
    const qty = toNum(t.quantity);
    const price = toNum(t.price_per_unit);
    if (qty <= 0 || !Number.isFinite(price) || price < 0) continue;

    const key = bookKey(t);
    const leg = open.get(key);
    const sideOpen: "long" | "short" = t.side === "buy" ? "long" : "short";

    if (!leg) {
      // No open leg — this trade opens a new one.
      open.set(key, {
        ticker,
        currency: (String(t.currency || "USD").trim().toUpperCase() || "USD"),
        isPaper: !!t.is_paper,
        side: sideOpen,
        qty,
        avgEntry: price,
        openedAt: t.executed_at,
        openTradeIds: [t.id],
        entryCostQty: qty * price,
        exitProceedsQty: 0,
        closedQty: 0,
        closeTradeIds: [],
      });
      continue;
    }

    const isAdding = (leg.side === "long" && t.side === "buy") || (leg.side === "short" && t.side === "sell");

    if (isAdding) {
      // Same direction — average up/down.
      const newQty = leg.qty + qty;
      leg.avgEntry = (leg.qty * leg.avgEntry + qty * price) / newQty;
      leg.qty = newQty;
      leg.entryCostQty += qty * price;
      leg.openTradeIds.push(t.id);
      continue;
    }

    // Opposite direction — closing (possibly with flip).
    const closeQty = Math.min(qty, leg.qty);
    leg.closedQty += closeQty;
    leg.exitProceedsQty += closeQty * price;
    leg.closeTradeIds.push(t.id);
    leg.qty -= closeQty;

    const excess = qty - closeQty;

    if (leg.qty <= EPS) {
      emitClosed(leg, t.id, t.executed_at);
      open.delete(key);

      if (excess > EPS) {
        const flipSide: "long" | "short" = sideOpen;
        open.set(key, {
          ticker,
          currency: leg.currency,
          isPaper: leg.isPaper,
          side: flipSide,
          qty: excess,
          avgEntry: price,
          openedAt: t.executed_at,
          openTradeIds: [t.id],
          entryCostQty: excess * price,
          exitProceedsQty: 0,
          closedQty: 0,
          closeTradeIds: [],
        });
      }
    }
  }

  closed.sort((a, b) => new Date(b.closedAt).getTime() - new Date(a.closedAt).getTime());
  return closed;
}

/** Set of trade ids that are the closing fill of a fully-closed position. */
export function closingTradeIdSet(trades: TradeLedgerInput[]): Set<number> {
  const positions = deriveClosedPositions(trades);
  return new Set(positions.map((p) => p.positionKey));
}

/** Find a single closed position by its closing trade id. */
export function findClosedPosition(
  trades: TradeLedgerInput[],
  closingTradeId: number,
): ClosedPosition | null {
  const positions = deriveClosedPositions(trades);
  return positions.find((p) => p.positionKey === closingTradeId) ?? null;
}
