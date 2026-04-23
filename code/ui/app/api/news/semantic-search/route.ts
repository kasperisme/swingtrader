import { NextResponse } from "next/server";
import { InferenceClient } from "@huggingface/inference";
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

const hfClient = new InferenceClient(process.env.HF_TOKEN!);

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

  try {
    const embedding = (await hfClient.featureExtraction({
      model: "mixedbread-ai/mxbai-embed-large-v1",
      inputs: query,
      provider: "hf-inference",
    })) as number[];

    if (!Array.isArray(embedding) || embedding.length === 0) {
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
