import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { embedQuery } from "@/lib/embeddings/query-embedding";
import {
  expandSearchTagCandidates,
  tagCandidatesFromQuery,
} from "@/lib/news/search-tags";

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
  const lookbackHours = lookbackDays * 24;
  const rawMode = body?.mode ? String(body.mode).toLowerCase() : "";
  const mode: "tags" | "semantic" | "hybrid" =
    rawMode === "tags" || rawMode === "semantic" ? rawMode : "hybrid";

  // Expand each requested tag into its plausible stored forms (lowercase theme
  // slug + uppercase ticker) so the GIN overlap matches regardless of how the
  // token was cased on input (e.g. "japan" → ["japan", "JAPAN"]).
  const explicitTags = Array.isArray(body?.tags)
    ? [
        ...new Set(
          body.tags.flatMap((t: unknown) =>
            expandSearchTagCandidates(String(t)),
          ),
        ),
      ]
    : [];
  const tagFilter =
    explicitTags.length > 0 ? explicitTags : tagCandidatesFromQuery(query);

  if (explicitTags.length === 0 && (!query || query.length < 3)) {
    return NextResponse.json({ results: [], note: "query_too_short" });
  }

  const searchQuery = query || tagFilter.join(" ");

  try {
    // Tag path (forced or hybrid-first): indexed GIN overlap, no embedding pod.
    if (mode !== "semantic" && tagFilter.length > 0) {
      const tagRpc = await supabase.schema("swingtrader").rpc("search_news_by_tags", {
        tag_filter: tagFilter,
        match_count: limit,
        lookback_hours: lookbackHours,
        stream_filter: streamFilter,
      });
      if (tagRpc.error) {
        console.error("[semantic-search] tag rpc failed:", tagRpc.error);
      } else if (Array.isArray(tagRpc.data) && tagRpc.data.length > 0) {
        return NextResponse.json({
          results: tagRpc.data as SemanticSearchRow[],
          note: "tags",
          tags: tagFilter,
        });
      }
      if (mode === "tags") {
        // Explicit tag mode: no fallback to semantic.
        return NextResponse.json({
          results: [],
          note: "tags_no_match",
          tags: tagFilter,
        });
      }
    }

    const embedding = await embedQuery(searchQuery);
    if (!embedding) {
      return NextResponse.json({ results: [], note: "embedding_failed" });
    }

    const rpc = await supabase.schema("swingtrader").rpc("search_news_embeddings", {
      query_embedding: embedding,
      match_count: limit,
      lookback_hours: lookbackHours,
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
