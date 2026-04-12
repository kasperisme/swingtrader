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

const SORTABLE_COLUMNS = ["created_at", "confidence", "article_id", "id", "cluster"] as const;

export type NewsImpactHeadsListFailure = { ok: false; status: number; message: string };

export type NewsImpactHeadsListSuccess = {
  ok: true;
  body: {
    data: ImpactHeadJson[] | Record<string, unknown>[];
    pagination: { limit: number; offset: number; total: number };
  };
};

export type NewsImpactHeadsListResult = NewsImpactHeadsListFailure | NewsImpactHeadsListSuccess;

/**
 * Shared implementation for GET /api/v1/news/impact-heads (and MCP tools).
 * Caller must already have enforced `news:read` (or equivalent).
 */
export async function listNewsImpactHeadsFromSearchParams(
  sp: URLSearchParams,
): Promise<NewsImpactHeadsListResult> {
  const pag = parseOffsetPagination(sp);
  if (!pag.ok) return { ok: false, status: 400, message: pag.message };

  const sort = parseSort(sp, SORTABLE_COLUMNS, "created_at", false);
  if (!sort.ok) return { ok: false, status: 400, message: sort.message };

  const fieldsResult = parseFieldsList(sp, IMPACT_HEAD_FIELD_SET);
  if (!fieldsResult.ok) return { ok: false, status: 400, message: fieldsResult.message };

  const includeResult = parseIncludeSet(sp, new Set(["article"]), new Set(["article"]));
  if (!includeResult.ok) return { ok: false, status: 400, message: includeResult.message };
  const includeArticle = includeResult.value.has("article");

  const { limit, offset } = pag.value;

  const articleIdParam = sp.get("article_id");
  const clusterParam = sp.get("cluster");
  const tickerParam = sp.get("ticker")?.toUpperCase().slice(0, 12) ?? null;
  const fromParam = sp.get("from");
  const toParam = sp.get("to");
  const minConfidenceParam = sp.get("min_confidence");

  if (articleIdParam !== null && !/^\d{1,19}$/.test(articleIdParam)) {
    return { ok: false, status: 400, message: "'article_id' must be a positive integer" };
  }
  if (clusterParam !== null && clusterParam.length > 64) {
    return { ok: false, status: 400, message: "'cluster' too long" };
  }
  if (fromParam !== null && isNaN(Date.parse(fromParam))) {
    return { ok: false, status: 400, message: "'from' must be a valid ISO 8601 date" };
  }
  if (toParam !== null && isNaN(Date.parse(toParam))) {
    return { ok: false, status: 400, message: "'to' must be a valid ISO 8601 date" };
  }
  if (
    minConfidenceParam !== null &&
    (isNaN(Number(minConfidenceParam)) ||
      Number(minConfidenceParam) < 0 ||
      Number(minConfidenceParam) > 1)
  ) {
    return { ok: false, status: 400, message: "'min_confidence' must be a number between 0 and 1" };
  }

  const supabase = createServiceClient();

  let articleIdsFromTicker: number[] | null = null;
  if (tickerParam) {
    const { data: tickerRows, error: tickerErr } = await supabase
      .schema("swingtrader")
      .from("news_article_tickers")
      .select("article_id")
      .eq("ticker", tickerParam);

    if (tickerErr) return { ok: false, status: 500, message: "Internal error" };

    articleIdsFromTicker = (tickerRows ?? []).map((r) => Number(r.article_id));
    if (articleIdsFromTicker.length === 0) {
      return {
        ok: true,
        body: { data: [], pagination: { limit, offset, total: 0 } },
      };
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

  if (queryErr) return { ok: false, status: 500, message: "Internal error" };

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

  return {
    ok: true,
    body: { data: payload, pagination: { limit, offset, total: count ?? 0 } },
  };
}

export type NewsImpactHeadGetFailure = { ok: false; status: number; message: string };

export type NewsImpactHeadGetSuccess = {
  ok: true;
  body: { data: ImpactHeadJson | Record<string, unknown> };
};

export type NewsImpactHeadGetResult = NewsImpactHeadGetFailure | NewsImpactHeadGetSuccess;

export async function getNewsImpactHeadById(
  id: number,
  sp: URLSearchParams,
): Promise<NewsImpactHeadGetResult> {
  const fieldsResult = parseFieldsList(sp, IMPACT_HEAD_FIELD_SET);
  if (!fieldsResult.ok) return { ok: false, status: 400, message: fieldsResult.message };

  const includeResult = parseIncludeSet(sp, new Set(["article"]), new Set(["article"]));
  if (!includeResult.ok) return { ok: false, status: 400, message: includeResult.message };
  const includeArticle = includeResult.value.has("article");

  const baseSelect = includeArticle
    ? "id, article_id, cluster, scores_json, reasoning_json, confidence, model, created_at, news_articles!fk_news_impact_heads_article ( title, url, slug, source, created_at )"
    : "id, article_id, cluster, scores_json, reasoning_json, confidence, model, created_at";

  const supabase = createServiceClient();
  const { data, error } = await supabase
    .schema("swingtrader")
    .from("news_impact_heads")
    .select(baseSelect)
    .eq("id", id)
    .maybeSingle();

  if (error) return { ok: false, status: 500, message: "Internal error" };
  if (data === null) return { ok: false, status: 404, message: "Impact head not found" };

  type RowIn = Parameters<typeof shapeImpactHeadRow>[0];
  const row = data as unknown as RowIn;
  const shaped = includeArticle
    ? shapeImpactHeadRow(row)
    : shapeImpactHeadRow({ ...row, news_articles: null });

  const fields = fieldsResult.value;
  const body =
    fields === null ? shaped : pickImpactHeadFields(shaped, fields);

  return { ok: true, body: { data: body } };
}
