import { NextRequest, NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { screeningsGetTickerSentimentHeadRows } from "@/app/actions/screenings";

// ── POST /api/screenings/ticker-sentiment ────────────────────────────────────
// Body: { symbols: string[] }.
// Returns the same shape as the screeningsGetTickerSentimentHeadRows action:
//   { ok: true, data: ScreeningTickerSentimentHeadRow[] } | { ok: false, error }
//
// Moved off the server-action queue: the underlying query, even after the
// ticker_sentiment_heads materialization, should not share Next.js's sequential
// action queue with the chart's OHLC fetch. The action is invoked in-process
// here (no client-action serialization).
export async function POST(req: NextRequest) {
  const supabase = await createClient();
  const { data: claims } = await supabase.auth.getClaims();
  if (!claims?.claims?.sub) {
    return NextResponse.json({ ok: false, error: "Unauthorized" }, { status: 401 });
  }

  let body: { symbols?: unknown } = {};
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ ok: false, error: "Invalid JSON body" }, { status: 400 });
  }

  const symbols = Array.isArray(body.symbols)
    ? body.symbols.filter((s): s is string => typeof s === "string")
    : [];

  const result = await screeningsGetTickerSentimentHeadRows(symbols);
  return NextResponse.json(result);
}
