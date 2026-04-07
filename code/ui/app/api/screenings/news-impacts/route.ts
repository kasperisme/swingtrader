import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

export async function GET() {
  const supabase = await createClient();

  const { data, error } = await supabase
    .schema("swingtrader")
    .from("news_impact_vectors")
    .select("impact_json, created_at, news_articles(published_at)")
    .order("created_at", { ascending: true });

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  const articles = (data ?? []).map((row: any) => ({
    impact_json: row.impact_json as Record<string, number>,
    published_at: (row.news_articles?.published_at ?? row.created_at) as string,
  }));

  return NextResponse.json(articles, {
    headers: { "Cache-Control": "s-maxage=300, stale-while-revalidate=60" },
  });
}
