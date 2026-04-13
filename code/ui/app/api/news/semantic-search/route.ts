import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

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
  const {
    data: { user },
    error: authErr,
  } = await supabase.auth.getUser();
  if (authErr || !user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const body = await req.json().catch(() => ({}));
  const query = String(body?.query ?? "").trim();
  const limit = Math.max(1, Math.min(Number(body?.limit ?? 20), 50));
  const lookbackDays = Math.max(1, Math.min(Number(body?.lookback_days ?? 30), 365));
  const streamFilter = body?.stream_filter ? String(body.stream_filter) : null;

  if (!query || query.length < 3) {
    return NextResponse.json({ results: [], note: "query_too_short" });
  }

  let semanticNote: string | null = null;
  try {
    // 1) Query embedding via Supabase Edge Function.
    const embedResp = await supabase.functions.invoke("embed", { body: { input: query } });
    const embedding = (embedResp.data as { embedding?: number[] } | null)?.embedding;

    if (!embedResp.error && Array.isArray(embedding) && embedding.length > 0) {
      // 2) Vector retrieval via SQL function.
      const rpc = await supabase.schema("swingtrader").rpc("search_news_article_embeddings_gte", {
        query_embedding: embedding,
        match_count: limit,
        lookback_days: lookbackDays,
        stream_filter: streamFilter,
      });
      if (!rpc.error) {
        return NextResponse.json({ results: (rpc.data ?? []) as SemanticSearchRow[] });
      }
      semanticNote = "semantic_rpc_failed";
      console.error("[semantic-search] rpc failed:", rpc.error);
    } else {
      semanticNote = "semantic_embed_unavailable";
      if (embedResp.error) {
        console.error("[semantic-search] embed invoke failed:", embedResp.error);
      }
    }
  } catch (err) {
    semanticNote = "semantic_embed_exception";
    console.error("[semantic-search] semantic phase exception:", err);
  }

  // 3) Fallback: keyword search if semantic path unavailable or empty corpus.
  const safe = query.replace(/[%_,]/g, " ").trim();
  const kw = await supabase
    .schema("swingtrader")
    .from("news_articles")
    .select("id,title,url,source,slug,image_url,article_stream,published_at,created_at,body")
    .or(`title.ilike.%${safe}%,body.ilike.%${safe}%`)
    .gte("created_at", new Date(Date.now() - lookbackDays * 24 * 60 * 60 * 1000).toISOString())
    .order("published_at", { ascending: false })
    .limit(limit);

  if (kw.error) {
    console.error("[semantic-search] keyword fallback failed:", kw.error);
    return NextResponse.json({ error: "search_failed" }, { status: 500 });
  }

  const results: SemanticSearchRow[] = (kw.data ?? []).map((r: any) => ({
    article_id: r.id,
    title: r.title ?? null,
    url: r.url ?? null,
    source: r.source ?? null,
    slug: r.slug ?? null,
    image_url: r.image_url ?? null,
    article_stream: r.article_stream ?? null,
    published_at: r.published_at ?? r.created_at ?? null,
    snippet: (r.body ?? "").slice(0, 220) || null,
    similarity: 0,
  }));
  if (results.length > 0) {
    return NextResponse.json({ results, note: semanticNote ?? "keyword_fallback" });
  }

  // Last-resort fallback: return recent articles so the UI never looks broken.
  const recent = await supabase
    .schema("swingtrader")
    .from("news_articles")
    .select("id,title,url,source,slug,image_url,article_stream,published_at,created_at,body")
    .order("published_at", { ascending: false, nullsFirst: false })
    .order("created_at", { ascending: false })
    .limit(limit);

  if (recent.error) {
    return NextResponse.json({ results: [], note: semanticNote ?? "no_results" });
  }

  const recentResults: SemanticSearchRow[] = (recent.data ?? []).map((r: any) => ({
    article_id: r.id,
    title: r.title ?? null,
    url: r.url ?? null,
    source: r.source ?? null,
    slug: r.slug ?? null,
    image_url: r.image_url ?? null,
    article_stream: r.article_stream ?? null,
    published_at: r.published_at ?? r.created_at ?? null,
    snippet: (r.body ?? "").slice(0, 220) || null,
    similarity: 0,
  }));

  return NextResponse.json({ results: recentResults, note: semanticNote ?? "recent_fallback" });
}
