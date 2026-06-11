import { NextResponse } from "next/server";
import { cacheLife } from "next/cache";
import { createServiceClient } from "@/lib/supabase/service";

const SCHEMA = "swingtrader";

function sinceDay(daysAgo: number): string {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() - daysAgo);
  return d.toISOString().slice(0, 10);
}

/** Aggregate a daily view into a top-N list of {value,count}. */
function topN(
  rows: Record<string, unknown>[],
  keyField: string,
  countField: string,
  n: number,
): { value: string; count: number }[] {
  const totals = new Map<string, number>();
  for (const r of rows) {
    const key = r[keyField];
    if (typeof key !== "string" || !key) continue;
    const c = Number(r[countField] ?? 0) || 0;
    totals.set(key, (totals.get(key) ?? 0) + c);
  }
  return [...totals.entries()]
    .map(([value, count]) => ({ value, count }))
    .sort((a, b) => b.count - a.count)
    .slice(0, n);
}

// Cache for an hour — the suggestion set barely moves intraday and every
// /briefings visitor hits this. Under cacheComponents the route-segment
// `revalidate` export is unsupported, so the work is wrapped in "use cache".
async function computeSuggestions(): Promise<{ tickers: string[]; tags: string[] }> {
  "use cache";
  cacheLife("hours");

  const service = createServiceClient();
  const since = sinceDay(7);

  const [tickRes, tagRes] = await Promise.all([
    service
      .schema(SCHEMA)
      .from("news_trends_ticker_daily_v")
      .select("ticker, mention_count, bucket_day")
      .gte("bucket_day", since)
      .limit(2000),
    service
      .schema(SCHEMA)
      .from("news_trends_tag_daily_v")
      .select("tag, article_count, bucket_day")
      .gte("bucket_day", since)
      .limit(2000),
  ]);

  const tickers = topN(tickRes.data ?? [], "ticker", "mention_count", 60).map(
    (t) => t.value,
  );
  const tags = topN(tagRes.data ?? [], "tag", "article_count", 60).map(
    (t) => t.value,
  );

  return { tickers, tags };
}

export async function GET() {
  try {
    return NextResponse.json(await computeSuggestions());
  } catch (e) {
    console.error("[briefings/suggestions]", e);
    return NextResponse.json({ tickers: [], tags: [] });
  }
}
