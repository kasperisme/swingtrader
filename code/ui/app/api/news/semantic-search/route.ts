import { NextResponse } from "next/server";
import { createServiceClient } from "@/lib/supabase/service";
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

// ts_rank_cd scores are unbounded small floats. The UI renders `similarity` as
// a 0–1 match bar, so rescale relative to the top hit: best result = 1.0, the
// rest proportional. Preserves ordering while making the bar meaningful.
function normalizeSimilarity(rows: SemanticSearchRow[]): SemanticSearchRow[] {
  const max = rows.reduce((m, r) => Math.max(m, r.similarity ?? 0), 0);
  if (max <= 0) return rows;
  return rows.map((r) => ({ ...r, similarity: (r.similarity ?? 0) / max }));
}

export async function POST(req: Request) {
  // Public endpoint: the /articles page is readable by logged-out visitors, so
  // tag/semantic search must work for them too. Use the service-role client to
  // bypass RLS on the swingtrader schema, matching how the page loads articles.
  const supabase = createServiceClient();

  const body = await req.json().catch(() => ({}));
  const query = String(body?.query ?? "").trim();
  const limit = Math.max(1, Math.min(Number(body?.limit ?? 20), 50));
  const lookbackDays = Math.max(1, Math.min(Number(body?.lookback_days ?? 30), 365));
  const streamFilter = body?.stream_filter ? String(body.stream_filter) : null;
  const lookbackHours = lookbackDays * 24;
  const rawMode = body?.mode ? String(body.mode).toLowerCase() : "";
  // "text" = full-text only (skip the tag overlap). "semantic" is the legacy
  // name for it: vector search was retired in Nov 2026 with the
  // news_article_embeddings table, and older clients may still send it.
  const mode: "tags" | "text" | "hybrid" =
    rawMode === "tags"
      ? "tags"
      : rawMode === "text" || rawMode === "semantic"
        ? "text"
        : "hybrid";

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

  if (explicitTags.length === 0 && (!query || query.length < 2)) {
    return NextResponse.json({ results: [], note: "query_too_short" });
  }

  const searchQuery = query || tagFilter.join(" ");

  try {
    // Explicit tag chips (e.g. a clicked ticker/theme) stay an exact GIN-overlap
    // filter — precise and index-fast, no ranking needed.
    if (mode !== "text" && explicitTags.length > 0) {
      const tagRpc = await supabase.schema("swingtrader").rpc("search_news_by_tags", {
        tag_filter: explicitTags,
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
          tags: explicitTags,
        });
      }
      if (mode === "tags") {
        return NextResponse.json({
          results: [],
          note: "tags_no_match",
          tags: explicitTags,
        });
      }
    }

    // Free-text path: ranked full-text search over title + tags + body. ORs
    // the query terms, so "iran oil crisis" matches iran OR oil OR crisis,
    // ranked by ts_rank_cd. Reached by every mode except a "tags" search with
    // tag chips (which returned above), including hybrid when the chips matched
    // nothing — the slot the retired vector fallback used to fill.
    if (searchQuery.length >= 2) {
      const ftsRpc = await supabase.schema("swingtrader").rpc("search_news_fulltext", {
        query_text: searchQuery,
        match_count: limit,
        lookback_hours: lookbackHours,
        stream_filter: streamFilter,
      });
      if (ftsRpc.error) {
        console.error("[semantic-search] fts rpc failed:", ftsRpc.error);
      } else if (Array.isArray(ftsRpc.data) && ftsRpc.data.length > 0) {
        return NextResponse.json({
          results: normalizeSimilarity(ftsRpc.data as SemanticSearchRow[]),
          note: "fulltext",
        });
      }
      if (mode === "tags") {
        return NextResponse.json({ results: [], note: "fulltext_no_match" });
      }
    }

    return NextResponse.json({ results: [], note: "no_match" });
  } catch (err) {
    console.error("[semantic-search] failed:", err);
    return NextResponse.json({ results: [], note: "search_failed" });
  }
}
