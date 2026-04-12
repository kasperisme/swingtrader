import { NextRequest, NextResponse } from "next/server";
import { createServiceClient } from "@/lib/supabase/service";
import {
  parseFieldsList,
  parseIncludeSet,
  parseOffsetPagination,
  parseSort,
} from "@/lib/api-v1/collection-params";
import {
  IMPACT_HEAD_FIELD_SET,
  pickImpactHeadFields,
  shapeImpactHeadRow,
  type ImpactHeadJson,
} from "@/lib/api-v1/news-impact-head";
import {
  NEWS_V1_CORS,
  newsV1JsonError,
  newsV1OptionsResponse,
  requireNewsReadBearer,
} from "@/lib/api-v1/news-public";

const SORTABLE_COLUMNS = ["created_at", "confidence", "article_id", "id", "cluster"] as const;

export async function OPTIONS() {
  return newsV1OptionsResponse();
}

export async function GET(req: NextRequest) {
  const auth = await requireNewsReadBearer(req);
  if (!auth.ok) return auth.response;

  const sp = req.nextUrl.searchParams;

  const pag = parseOffsetPagination(sp);
  if (!pag.ok) return newsV1JsonError(pag.message, 400);

  const sort = parseSort(sp, SORTABLE_COLUMNS, "created_at", false);
  if (!sort.ok) return newsV1JsonError(sort.message, 400);

  const fieldsResult = parseFieldsList(sp, IMPACT_HEAD_FIELD_SET);
  if (!fieldsResult.ok) return newsV1JsonError(fieldsResult.message, 400);

  const includeResult = parseIncludeSet(sp, new Set(["article"]), new Set(["article"]));
  if (!includeResult.ok) return newsV1JsonError(includeResult.message, 400);
  const includeArticle = includeResult.value.has("article");

  const { limit, offset } = pag.value;

  const articleIdParam = sp.get("article_id");
  const clusterParam = sp.get("cluster");
  const tickerParam = sp.get("ticker")?.toUpperCase().slice(0, 12) ?? null;
  const fromParam = sp.get("from");
  const toParam = sp.get("to");
  const minConfidenceParam = sp.get("min_confidence");

  if (articleIdParam !== null && !/^\d{1,19}$/.test(articleIdParam)) {
    return newsV1JsonError("'article_id' must be a positive integer", 400);
  }
  if (clusterParam !== null && clusterParam.length > 64) {
    return newsV1JsonError("'cluster' too long", 400);
  }
  if (fromParam !== null && isNaN(Date.parse(fromParam))) {
    return newsV1JsonError("'from' must be a valid ISO 8601 date", 400);
  }
  if (toParam !== null && isNaN(Date.parse(toParam))) {
    return newsV1JsonError("'to' must be a valid ISO 8601 date", 400);
  }
  if (
    minConfidenceParam !== null &&
    (isNaN(Number(minConfidenceParam)) ||
      Number(minConfidenceParam) < 0 ||
      Number(minConfidenceParam) > 1)
  ) {
    return newsV1JsonError("'min_confidence' must be a number between 0 and 1", 400);
  }

  const supabase = createServiceClient();

  let articleIdsFromTicker: number[] | null = null;
  if (tickerParam) {
    const { data: tickerRows, error: tickerErr } = await supabase
      .schema("swingtrader")
      .from("news_article_tickers")
      .select("article_id")
      .eq("ticker", tickerParam);

    if (tickerErr) return newsV1JsonError("Internal error", 500);

    articleIdsFromTicker = (tickerRows ?? []).map((r) => Number(r.article_id));
    if (articleIdsFromTicker.length === 0) {
      return NextResponse.json(
        { data: [], pagination: { limit, offset, total: 0 } },
        { headers: NEWS_V1_CORS },
      );
    }
  }

  const baseSelect = includeArticle
    ? "id, article_id, cluster, scores_json, reasoning_json, confidence, model, created_at, news_articles!fk_news_impact_heads_article ( title, url, slug, source, created_at )"
    : "id, article_id, cluster, scores_json, reasoning_json, confidence, model, created_at";

  let query = supabase
    .schema("swingtrader")
    .from("news_impact_heads")
    .select(baseSelect, { count: "exact" })
    .order(sort.value.column, { ascending: sort.value.ascending })
    .range(offset, offset + limit - 1);

  if (articleIdParam !== null) query = query.eq("article_id", parseInt(articleIdParam, 10));
  if (clusterParam) query = query.eq("cluster", clusterParam);
  if (fromParam) query = query.gte("created_at", new Date(fromParam).toISOString());
  if (toParam) query = query.lte("created_at", new Date(toParam).toISOString());
  if (minConfidenceParam !== null) query = query.gte("confidence", Number(minConfidenceParam));
  if (articleIdsFromTicker !== null) query = query.in("article_id", articleIdsFromTicker);

  const { data, error: queryErr, count } = await query;

  if (queryErr) return newsV1JsonError("Internal error", 500);

  type RowIn = Parameters<typeof shapeImpactHeadRow>[0];

  const shaped: ImpactHeadJson[] = (data ?? []).map((row) => {
    const r = row as unknown as RowIn;
    if (!includeArticle) {
      return shapeImpactHeadRow({ ...r, news_articles: null });
    }
    return shapeImpactHeadRow(r);
  });

  const fields = fieldsResult.value;
  const payload: ImpactHeadJson[] | Record<string, unknown>[] =
    fields === null ? shaped : shaped.map((row) => pickImpactHeadFields(row, fields));

  return NextResponse.json(
    { data: payload, pagination: { limit, offset, total: count ?? 0 } },
    { headers: NEWS_V1_CORS },
  );
}
