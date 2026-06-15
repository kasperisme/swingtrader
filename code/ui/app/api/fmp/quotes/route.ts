import { NextRequest, NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { fmpGetQuote } from "@/app/actions/fmp";

// ── POST /api/fmp/quotes ──────────────────────────────────────────────────────
// Bulk quote fetch. Body: { symbols: string[] }.
// Returns: { quotes: Record<UPPER_SYMBOL, FmpQuote | null> }.
//
// Why a route handler instead of the per-symbol fmpGetQuote server action:
// Next.js executes client-invoked Server Actions sequentially, so the screening
// grid's ~60 useQuotes calls queued one behind another (~7s) and starved the
// chart's own OHLC action. A route handler runs OFF that queue and fans the FMP
// requests out concurrently in a single round-trip. fmpGetQuote is called
// in-process here (not as a client action), so it keeps its caching + shape and
// never touches the action queue.
export async function POST(req: NextRequest) {
  const supabase = await createClient();
  const { data: claims } = await supabase.auth.getClaims();
  if (!claims?.claims?.sub) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  let body: { symbols?: unknown } = {};
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }

  // Preserve the caller's exact symbol strings as response keys (callers look up
  // quotes[symbol] by the value they passed). Dedup on the trimmed string.
  const symbols = Array.isArray(body.symbols)
    ? [
        ...new Set(
          body.symbols
            .map((s) => (typeof s === "string" ? s.trim() : ""))
            .filter(Boolean),
        ),
      ]
    : [];

  if (symbols.length === 0) {
    return NextResponse.json({ quotes: {} });
  }

  const quotes: Record<string, unknown | null> = {};
  // Bound outbound concurrency (FMP rate limits / socket exhaustion) — fan out in
  // windows rather than all symbols at once. fmpGetQuote's revalidate cache makes
  // repeat windows cheap.
  const CONCURRENCY = 12;
  for (let i = 0; i < symbols.length; i += CONCURRENCY) {
    const window = symbols.slice(i, i + CONCURRENCY);
    await Promise.all(
      window.map(async (sym) => {
        try {
          const res = await fmpGetQuote(sym);
          if (!res.ok) {
            quotes[sym] = null;
            return;
          }
          const data = res.data;
          quotes[sym] = Array.isArray(data) ? (data[0] ?? null) : null;
        } catch {
          quotes[sym] = null;
        }
      }),
    );
  }

  return NextResponse.json({ quotes });
}
