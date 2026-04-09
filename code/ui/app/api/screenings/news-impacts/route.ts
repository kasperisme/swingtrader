import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

function asNumberMap(v: unknown): Record<string, number> {
  if (!v) return {};
  if (typeof v === "string") {
    try {
      return asNumberMap(JSON.parse(v));
    } catch {
      return {};
    }
  }
  if (typeof v !== "object") return {};
  const out: Record<string, number> = {};
  for (const [k, raw] of Object.entries(v as Record<string, unknown>)) {
    const n = Number(raw);
    if (Number.isFinite(n)) out[String(k).trim().toUpperCase()] = n;
  }
  return out;
}

export async function GET() {
  const supabase = await createClient();

  const [vectorsRes, headsRes] = await Promise.all([
    supabase
      .schema("swingtrader")
      .from("news_impact_vectors")
      .select("article_id, impact_json, created_at, news_articles(published_at)")
      .order("created_at", { ascending: true }),
    supabase
      .schema("swingtrader")
      .from("news_impact_heads")
      .select("article_id, scores_json")
      .eq("cluster", "TICKER_SENTIMENT"),
  ]);

  if (vectorsRes.error) {
    return NextResponse.json({ error: vectorsRes.error.message }, { status: 500 });
  }
  if (headsRes.error) {
    return NextResponse.json({ error: headsRes.error.message }, { status: 500 });
  }

  const tickerSentimentByArticleId = new Map<number, Record<string, number>>();
  for (const row of headsRes.data ?? []) {
    const articleId = Number((row as any).article_id);
    if (!Number.isFinite(articleId)) continue;
    tickerSentimentByArticleId.set(articleId, asNumberMap((row as any).scores_json));
  }

  const articles = (vectorsRes.data ?? []).map((row: any) => ({
    impact_json: row.impact_json as Record<string, number>,
    published_at: (row.news_articles?.published_at ?? row.created_at) as string,
    ticker_sentiment: tickerSentimentByArticleId.get(Number(row.article_id)) ?? {},
  }));

  return NextResponse.json(articles, {
    headers: { "Cache-Control": "s-maxage=300, stale-while-revalidate=60" },
  });
}
