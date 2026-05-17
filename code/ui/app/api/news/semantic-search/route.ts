import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { embedQuery } from "@/lib/embeddings/query-embedding";

type SemanticSearchRow = {
  article_id: number;
  title: string | null;
  url: string | null;
  source: string | null;
  slug: string | null;
  image_url: string | null;
  article_stream: string | null;
  published_at: string | null;
  snippet: string | null;
  similarity: number;
};

export async function POST(req: Request) {
  const supabase = await createClient();
  const { data: claims, error: claimsError } = await supabase.auth.getClaims();
  if (claimsError || !claims?.claims) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const body = await req.json().catch(() => ({}));
  const query = String(body?.query ?? "").trim();
  const limit = Math.max(1, Math.min(Number(body?.limit ?? 20), 50));
  const lookbackDays = Math.max(1, Math.min(Number(body?.lookback_days ?? 30), 365));
  const streamFilter = body?.stream_filter ? String(body.stream_filter) : null;

  if (!query || query.length < 3) {
    return NextResponse.json({ results: [], note: "query_too_short" });
  }

  try {
    const embedding = await embedQuery(query);
    if (!embedding) {
      return NextResponse.json({ results: [], note: "embedding_failed" });
    }

    const rpc = await supabase.schema("swingtrader").rpc("search_news_embeddings", {
      query_embedding: embedding,
      match_count: limit,
      lookback_hours: lookbackDays * 24,
      stream_filter: streamFilter,
    });

    if (rpc.error) {
      console.error("[semantic-search] rpc failed:", rpc.error);
      return NextResponse.json({ results: [], note: "rpc_failed" });
    }

    return NextResponse.json({
      results: (rpc.data ?? []) as SemanticSearchRow[],
      note: "semantic",
    });
  } catch (err) {
    console.error("[semantic-search] failed:", err);
    return NextResponse.json({ results: [], note: "search_failed" });
  }
}
