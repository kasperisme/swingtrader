"use server";

import { createClient } from "@/lib/supabase/server";
import {
  deriveClosedPositions,
  findClosedPosition,
  type ClosedPosition,
  type TradeLedgerInput,
} from "@/lib/trades/closed-positions";
import type { ChartAiChatMessage } from "@/app/actions/chart-workspace";

type ActionError = { ok: false; error: string };
type ActionSuccess<T> = { ok: true; data: T };

export type TradeReviewScores = {
  execution: number;
  timing: number;
  risk_mgmt: number;
  lesson: number;
};

export type TradeReviewRecord = {
  id: number;
  user_id: string;
  closing_trade_id: number;
  ticker: string;
  position_snapshot: ClosedPosition;
  messages: ChartAiChatMessage[];
  summary: string | null;
  scores: TradeReviewScores | null;
  created_at: string;
  updated_at: string;
};

export type TradeReviewBootstrap = {
  position: ClosedPosition;
  review: TradeReviewRecord;
  /** All user_trades rows that participated in this position, ordered ascending. */
  positionTrades: {
    id: number;
    side: "buy" | "sell";
    quantity: number;
    price_per_unit: number;
    executed_at: string;
    notes: string | null;
  }[];
};

function parseMessages(raw: unknown): ChartAiChatMessage[] {
  if (!Array.isArray(raw)) return [];
  const out: ChartAiChatMessage[] = [];
  for (const item of raw) {
    if (!item || typeof item !== "object") continue;
    const o = item as Record<string, unknown>;
    const role = o.role === "user" || o.role === "assistant" ? o.role : null;
    const content = typeof o.content === "string" ? o.content : "";
    if (!role) continue;
    const msg: ChartAiChatMessage = { role, content };
    if (Array.isArray(o.chartAnnotations)) {
      msg.chartAnnotations = o.chartAnnotations as ChartAiChatMessage["chartAnnotations"];
    }
    if (Array.isArray(o.personaReports)) {
      msg.personaReports = o.personaReports as ChartAiChatMessage["personaReports"];
    }
    out.push(msg);
  }
  return out;
}

function parseScores(raw: unknown): TradeReviewScores | null {
  if (!raw || typeof raw !== "object") return null;
  const o = raw as Record<string, unknown>;
  const clamp = (v: unknown) => Math.min(100, Math.max(0, Math.round(Number(v))));
  if (
    typeof o.execution !== "number" &&
    typeof o.timing !== "number" &&
    typeof o.risk_mgmt !== "number" &&
    typeof o.lesson !== "number"
  ) {
    return null;
  }
  return {
    execution: clamp(o.execution ?? 50),
    timing: clamp(o.timing ?? 50),
    risk_mgmt: clamp(o.risk_mgmt ?? 50),
    lesson: clamp(o.lesson ?? 50),
  };
}

async function loadAllUserTrades(): Promise<
  { ok: true; userId: string; trades: TradeLedgerInput[] } | ActionError
> {
  const supabase = await createClient();
  const { data: claims } = await supabase.auth.getClaims();
  const userId = claims?.claims?.sub;
  if (!userId) return { ok: false, error: "Unauthorized" };

  const { data, error } = await supabase
    .schema("swingtrader")
    .from("user_trades")
    .select("id, ticker, currency, quantity, price_per_unit, side, executed_at, is_paper")
    .order("executed_at", { ascending: true })
    .limit(2000);

  if (error) return { ok: false, error: error.message };
  return { ok: true, userId, trades: (data ?? []) as TradeLedgerInput[] };
}

/**
 * Load a review for the given closing trade id, creating it on first access.
 * Also returns the participating trade rows so the UI can render entry/exit
 * markers and the notes column.
 */
export async function tradeReviewBootstrap(
  closingTradeId: number,
): Promise<ActionSuccess<TradeReviewBootstrap> | ActionError> {
  if (!Number.isFinite(closingTradeId) || closingTradeId <= 0) {
    return { ok: false, error: "Invalid trade id" };
  }
  const all = await loadAllUserTrades();
  if (!("ok" in all) || !all.ok) return all;

  const position = findClosedPosition(all.trades, closingTradeId);
  if (!position) {
    return { ok: false, error: "No closed position for this trade." };
  }

  const supabase = await createClient();

  // Fetch participating trade rows (with notes) for UI context.
  const participatingIds = [...position.openTradeIds, ...position.closeTradeIds];
  const { data: rows, error: rowsErr } = await supabase
    .schema("swingtrader")
    .from("user_trades")
    .select("id, side, quantity, price_per_unit, executed_at, notes")
    .in("id", participatingIds);

  if (rowsErr) return { ok: false, error: rowsErr.message };

  const positionTrades = (rows ?? [])
    .map((r) => ({
      id: r.id as number,
      side: r.side as "buy" | "sell",
      quantity: Number(r.quantity),
      price_per_unit: Number(r.price_per_unit),
      executed_at: r.executed_at as string,
      notes: (r.notes ?? null) as string | null,
    }))
    .sort((a, b) => new Date(a.executed_at).getTime() - new Date(b.executed_at).getTime());

  // Get-or-create the review row.
  const { data: existing, error: selErr } = await supabase
    .schema("swingtrader")
    .from("user_trade_reviews")
    .select("*")
    .eq("user_id", all.userId)
    .eq("closing_trade_id", closingTradeId)
    .maybeSingle();

  if (selErr) return { ok: false, error: selErr.message };

  let row = existing as Record<string, unknown> | null;

  if (!row) {
    const { data: inserted, error: insErr } = await supabase
      .schema("swingtrader")
      .from("user_trade_reviews")
      .insert({
        user_id: all.userId,
        closing_trade_id: closingTradeId,
        ticker: position.ticker,
        position_snapshot: position,
        messages: [],
      })
      .select("*")
      .single();
    if (insErr) return { ok: false, error: insErr.message };
    row = inserted as Record<string, unknown>;
  }

  const review: TradeReviewRecord = {
    id: row!.id as number,
    user_id: row!.user_id as string,
    closing_trade_id: row!.closing_trade_id as number,
    ticker: row!.ticker as string,
    position_snapshot: (row!.position_snapshot as ClosedPosition) ?? position,
    messages: parseMessages(row!.messages),
    summary: (row!.summary as string | null) ?? null,
    scores: parseScores(row!.scores),
    created_at: row!.created_at as string,
    updated_at: row!.updated_at as string,
  };

  return { ok: true, data: { position, review, positionTrades } };
}

/**
 * Persist the chat messages (and optional summary + scores) for a review.
 * Owner-only via RLS.
 */
export async function tradeReviewSave(
  closingTradeId: number,
  payload: {
    messages: ChartAiChatMessage[];
    summary?: string | null;
    scores?: TradeReviewScores | null;
  },
): Promise<ActionSuccess<{ updated: boolean }> | ActionError> {
  if (!Number.isFinite(closingTradeId) || closingTradeId <= 0) {
    return { ok: false, error: "Invalid trade id" };
  }
  const supabase = await createClient();
  const { data: claims } = await supabase.auth.getClaims();
  const userId = claims?.claims?.sub;
  if (!userId) return { ok: false, error: "Unauthorized" };

  const update: Record<string, unknown> = { messages: payload.messages };
  if (payload.summary !== undefined) update.summary = payload.summary;
  if (payload.scores !== undefined) update.scores = payload.scores;

  const { error } = await supabase
    .schema("swingtrader")
    .from("user_trade_reviews")
    .update(update)
    .eq("user_id", userId)
    .eq("closing_trade_id", closingTradeId);

  if (error) return { ok: false, error: error.message };
  return { ok: true, data: { updated: true } };
}

/**
 * Return the set of trade ids that close a fully-flat position.
 * Used by the trades list to show "Review" buttons only where they make sense.
 */
export async function listClosingTradeIds(): Promise<
  ActionSuccess<{ closingTradeIds: number[] }> | ActionError
> {
  const all = await loadAllUserTrades();
  if (!("ok" in all) || !all.ok) return all;
  const positions = deriveClosedPositions(all.trades);
  return { ok: true, data: { closingTradeIds: positions.map((p) => p.positionKey) } };
}
