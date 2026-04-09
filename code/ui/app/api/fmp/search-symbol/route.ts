import { NextRequest, NextResponse } from "next/server";

const MAX_QUERY_LEN = 80;

/**
 * Proxies FMP Stock Symbol Search (company name or ticker).
 * https://site.financialmodelingprep.com/developer/docs/stable/search-symbol
 */
export async function GET(req: NextRequest) {
  const raw = req.nextUrl.searchParams.get("query") ?? "";
  const query = raw.trim();
  if (query.length < 1) {
    return NextResponse.json({ error: "query required" }, { status: 400 });
  }
  if (query.length > MAX_QUERY_LEN) {
    return NextResponse.json({ error: "query too long" }, { status: 400 });
  }

  const apiKey = process.env.FMP_API_KEY;
  if (!apiKey) {
    return NextResponse.json({ error: "FMP_API_KEY not configured" }, { status: 500 });
  }

  const url = `https://financialmodelingprep.com/stable/search-symbol?query=${encodeURIComponent(query)}&apikey=${encodeURIComponent(apiKey)}`;
  const res = await fetch(url, { next: { revalidate: 120 } });
  if (!res.ok) {
    return NextResponse.json({ error: "FMP request failed" }, { status: 502 });
  }

  const data: unknown = await res.json();
  if (!Array.isArray(data)) {
    return NextResponse.json({ error: "Unexpected FMP response" }, { status: 502 });
  }

  return NextResponse.json(data);
}
