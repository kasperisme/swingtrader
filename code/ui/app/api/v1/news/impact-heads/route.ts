import { NextRequest, NextResponse } from "next/server";
import { validateApiKey } from "@/lib/api-auth";
import { createServiceClient } from "@/lib/supabase/service";

// CORS headers applied to every response from this public endpoint
const CORS: HeadersInit = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, OPTIONS",
  "Access-Control-Allow-Headers": "Authorization",
};

function err(message: string, status: number, extra?: Record<string, unknown>) {
  return NextResponse.json({ error: message, ...extra }, { status, headers: CORS });
}

// OPTIONS is handled by middleware, but keep a handler for robustness
export async function OPTIONS() {
  return new NextResponse(null, {
    status: 204,
    headers: { ...CORS, "Access-Control-Max-Age": "86400" },
  });
}

export async function GET(req: NextRequest) {
  // ── 1. Extract Bearer token ────────────────────────────────────────────────
  const authHeader = req.headers.get("authorization") ?? "";
  const match = /^Bearer\s+(\S+)$/i.exec(authHeader);
  if (!match) {
    return err(
      "Missing or malformed Authorization header. Expected: Authorization: Bearer <api_key>",
      401,
    );
  }

  const rawKey = match[1];

  // Reject obviously-wrong lengths before hitting the DB
  if (rawKey.length < 16 || rawKey.length > 200) {
    return err("Invalid API key", 401);
  }

  // ── 2. Validate key + rate limit ───────────────────────────────────────────
  const result = await validateApiKey(rawKey);

  if (!result.ok && result.rateLimited) {
    return err("Rate limit exceeded. Maximum 60 requests per minute per key.", 429, {
      "Retry-After": "60",
    });
  }

  if (!result.ok) {
    // Small deliberate delay to slow brute-force enumeration
    await new Promise((r) => setTimeout(r, 50 + Math.random() * 50));
    return err("Invalid API key", 401);
  }

  if (!result.key.scopes.includes("news:read")) {
    return err("Forbidden: this key does not have the 'news:read' scope", 403);
  }

  // ── 3. Parse & validate query parameters ──────────────────────────────────
  const sp = req.nextUrl.searchParams;

  const rawLimit = sp.get("limit") ?? "20";
  const rawOffset = sp.get("offset") ?? "0";
  const limit = Math.min(Math.max(parseInt(rawLimit, 10) || 20, 1), 100);
  const offset = Math.max(parseInt(rawOffset, 10) || 0, 0);

  const articleIdParam = sp.get("article_id");
  const clusterParam = sp.get("cluster");
  const tickerParam = sp.get("ticker")?.toUpperCase().slice(0, 12) ?? null;
  const fromParam = sp.get("from");
  const toParam = sp.get("to");
  const minConfidenceParam = sp.get("min_confidence");

  if (articleIdParam !== null && !/^\d{1,19}$/.test(articleIdParam)) {
    return err("'article_id' must be a positive integer", 400);
  }
  if (clusterParam !== null && clusterParam.length > 64) {
    return err("'cluster' too long", 400);
  }
  if (fromParam !== null && isNaN(Date.parse(fromParam))) {
    return err("'from' must be a valid ISO 8601 date", 400);
  }
  if (toParam !== null && isNaN(Date.parse(toParam))) {
    return err("'to' must be a valid ISO 8601 date", 400);
  }
  if (
    minConfidenceParam !== null &&
    (isNaN(Number(minConfidenceParam)) ||
      Number(minConfidenceParam) < 0 ||
      Number(minConfidenceParam) > 1)
  ) {
    return err("'min_confidence' must be a number between 0 and 1", 400);
  }

  // ── 4. Query ──────────────────────────────────────────────────────────────
  const supabase = createServiceClient();

  // If filtering by ticker, first resolve matching article_ids
  let articleIdsFromTicker: number[] | null = null;
  if (tickerParam) {
    const { data: tickerRows, error: tickerErr } = await supabase
      .schema("swingtrader")
      .from("news_article_tickers")
      .select("article_id")
      .eq("ticker", tickerParam);

    if (tickerErr) return err("Internal error", 500);

    articleIdsFromTicker = (tickerRows ?? []).map((r) => Number(r.article_id));
    if (articleIdsFromTicker.length === 0) {
      return NextResponse.json(
        { data: [], pagination: { limit, offset, total: 0 } },
        { headers: CORS },
      );
    }
  }

  let query = supabase
    .schema("swingtrader")
    .from("news_impact_heads")
    .select(
      `id, article_id, cluster, scores_json, reasoning_json, confidence, model, created_at,
       news_articles!fk_news_impact_heads_article ( title, url, slug, source, created_at )`,
      { count: "exact" },
    )
    .order("created_at", { ascending: false })
    .range(offset, offset + limit - 1);

  if (articleIdParam !== null) query = query.eq("article_id", parseInt(articleIdParam, 10));
  if (clusterParam) query = query.eq("cluster", clusterParam);
  if (fromParam) query = query.gte("created_at", new Date(fromParam).toISOString());
  if (toParam) query = query.lte("created_at", new Date(toParam).toISOString());
  if (minConfidenceParam !== null) query = query.gte("confidence", Number(minConfidenceParam));
  if (articleIdsFromTicker !== null) query = query.in("article_id", articleIdsFromTicker);

  const { data, error: queryErr, count } = await query;

  if (queryErr) return err("Internal error", 500);

  // ── 5. Shape response ─────────────────────────────────────────────────────
  type ArticleShape = { title: string; url: string | null; slug: string | null; source: string | null; created_at: string } | null;

  const shaped = (data ?? []).map((row) => {
    const article = (row as unknown as { news_articles: ArticleShape }).news_articles;
    return {
      id: (row as { id: number }).id,
      article_id: (row as { article_id: number }).article_id,
      article,
      cluster: (row as { cluster: string }).cluster,
      scores: (row as { scores_json: unknown }).scores_json,
      reasoning: (row as { reasoning_json: unknown }).reasoning_json,
      confidence: (row as { confidence: number }).confidence,
      model: (row as { model: string }).model,
      created_at: (row as { created_at: string }).created_at,
    };
  });

  return NextResponse.json(
    { data: shaped, pagination: { limit, offset, total: count ?? 0 } },
    { headers: CORS },
  );
}
