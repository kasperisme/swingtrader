import { NextRequest, NextResponse } from "next/server";

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

function subtractCalendarDays(ymd: string, days: number): string {
  const [y, m, d] = ymd.split("-").map((x) => Number.parseInt(x, 10));
  if (!Number.isFinite(y) || !Number.isFinite(m) || !Number.isFinite(d)) return ymd;
  const ms = Date.UTC(y, m - 1, d) - days * 86_400_000;
  return new Date(ms).toISOString().slice(0, 10);
}

function pickHistoricalClose(
  rows: { date: string; close: unknown }[],
  dateStr: string,
): { close: number; asOfDate: string } | null {
  const eligible = rows.filter((h) => {
    if (typeof h.date !== "string" || h.date > dateStr) return false;
    const c = typeof h.close === "number" ? h.close : Number(h.close);
    return Number.isFinite(c);
  });
  if (eligible.length === 0) return null;
  eligible.sort((a, b) => b.date.localeCompare(a.date));
  const top = eligible[0];
  const close = typeof top.close === "number" ? top.close : Number(top.close);
  return { close, asOfDate: top.date };
}

/**
 * Daily close on or before `date` (YYYY-MM-DD), else latest live quote from FMP.
 * `date` is the user's local calendar day for the trade.
 */
export async function GET(req: NextRequest) {
  const symbolParam = req.nextUrl.searchParams.get("symbol");
  const dateStr = req.nextUrl.searchParams.get("date");
  if (!symbolParam?.trim()) {
    return NextResponse.json({ error: "symbol required" }, { status: 400 });
  }
  if (!dateStr || !DATE_RE.test(dateStr)) {
    return NextResponse.json({ error: "date must be YYYY-MM-DD" }, { status: 400 });
  }

  let symbol = symbolParam.trim();
  for (let i = 0; i < 2; i++) {
    try {
      const decoded = decodeURIComponent(symbol);
      if (decoded === symbol) break;
      symbol = decoded;
    } catch {
      break;
    }
  }

  if (symbol.replace(/^\^/, "").toUpperCase() === "GSPC") {
    symbol = "^GSPC";
  }

  const symbolCandidates = Array.from(
    new Set([
      symbol,
      symbol === "^GSPC"
        ? "GSPC"
        : symbol.startsWith("^")
          ? symbol.slice(1)
          : symbol,
    ]),
  );

  const apiKey = process.env.FMP_API_KEY;
  if (!apiKey) {
    return NextResponse.json({ error: "FMP_API_KEY not configured" }, { status: 500 });
  }

  const fromStr = subtractCalendarDays(dateStr, 60);

  for (const candidate of symbolCandidates) {
    const histUrl = `https://financialmodelingprep.com/api/v3/historical-price-full/${encodeURIComponent(candidate)}?from=${fromStr}&to=${dateStr}&apikey=${encodeURIComponent(apiKey)}`;
    const histRes = await fetch(histUrl, { next: { revalidate: 300 } });
    if (!histRes.ok) continue;

    const histJson: unknown = await histRes.json();
    const historical = Array.isArray(histJson)
      ? histJson
      : typeof histJson === "object" &&
          histJson !== null &&
          Array.isArray((histJson as { historical?: unknown }).historical)
        ? (histJson as { historical: { date: string; close: unknown }[] }).historical
        : [];

    const picked = pickHistoricalClose(historical, dateStr);
    if (picked) {
      return NextResponse.json({
        price: picked.close,
        source: "historical" as const,
        asOfDate: picked.asOfDate,
      });
    }
  }

  for (const candidate of symbolCandidates) {
    const quoteUrl = `https://financialmodelingprep.com/stable/quote?symbol=${encodeURIComponent(candidate)}&apikey=${encodeURIComponent(apiKey)}`;
    const quoteRes = await fetch(quoteUrl, { next: { revalidate: 60 } });
    if (!quoteRes.ok) continue;
    const quoteJson: unknown = await quoteRes.json();
    const row = Array.isArray(quoteJson) ? quoteJson[0] : null;
    if (
      row &&
      typeof row === "object" &&
      row !== null &&
      typeof (row as { price?: unknown }).price === "number" &&
      Number.isFinite((row as { price: number }).price)
    ) {
      const price = (row as { price: number }).price;
      return NextResponse.json({
        price,
        source: "quote" as const,
        asOfDate: dateStr,
      });
    }
  }

  return NextResponse.json({ error: "No price data for symbol/date" }, { status: 404 });
}
