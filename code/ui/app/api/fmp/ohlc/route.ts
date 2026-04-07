import { NextRequest, NextResponse } from "next/server";

export async function GET(req: NextRequest) {
  const symbol = req.nextUrl.searchParams.get("symbol");
  if (!symbol) {
    return NextResponse.json({ error: "symbol required" }, { status: 400 });
  }

  const apiKey = process.env.FMP_API_KEY;
  if (!apiKey) {
    return NextResponse.json({ error: "FMP_API_KEY not configured" }, { status: 500 });
  }

  const to = new Date();
  const from = new Date();
  from.setFullYear(from.getFullYear() - 1);
  const toStr = to.toISOString().split("T")[0];
  const fromStr = from.toISOString().split("T")[0];

  // v3 supports explicit from/to. The stable /historical-price-eod/full endpoint often ignores
  // `from` and returns a short default window (~6 months of trading days).
  const url =
    `https://financialmodelingprep.com/api/v3/historical-price-full/${encodeURIComponent(symbol)}` +
    `?from=${fromStr}&to=${toStr}&apikey=${encodeURIComponent(apiKey)}`;

  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) {
    return NextResponse.json({ error: "FMP request failed" }, { status: 502 });
  }

  const data = await res.json();
  const historical: unknown[] = Array.isArray(data) ? data : (data?.historical ?? []);

  const normalized = historical
    .map((row: unknown) => {
      if (row == null || typeof row !== "object") return null;
      const r = row as Record<string, unknown>;
      if (r.date == null) return null;
      return {
        date: String(r.date),
        open: Number(r.open),
        high: Number(r.high),
        low: Number(r.low),
        close: Number(r.close),
        volume: Number(r.volume),
      };
    })
    .filter((b): b is NonNullable<typeof b> => b != null && Number.isFinite(b.close));

  const sorted = [...normalized].sort(
    (a, b) => new Date(a.date).getTime() - new Date(b.date).getTime()
  );
  return NextResponse.json(sorted);
}
