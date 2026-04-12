import { NextRequest, NextResponse } from "next/server";
import { createServiceClient } from "@/lib/supabase/service";
import { parseFieldsList, parseIncludeSet } from "@/lib/api-v1/collection-params";
import {
  IMPACT_HEAD_FIELD_SET,
  pickImpactHeadFields,
  shapeImpactHeadRow,
} from "@/lib/api-v1/news-impact-head";
import {
  NEWS_V1_CORS,
  newsV1JsonError,
  newsV1OptionsResponse,
  requireNewsReadBearer,
} from "@/lib/api-v1/news-public";

export async function OPTIONS() {
  return newsV1OptionsResponse();
}

export async function GET(
  req: NextRequest,
  ctx: { params: Promise<{ id: string }> },
) {
  const auth = await requireNewsReadBearer(req);
  if (!auth.ok) return auth.response;

  const { id: idParam } = await ctx.params;
  if (!/^\d{1,19}$/.test(idParam)) {
    return newsV1JsonError("'id' must be a positive integer", 400);
  }
  const id = parseInt(idParam, 10);

  const sp = req.nextUrl.searchParams;

  const fieldsResult = parseFieldsList(sp, IMPACT_HEAD_FIELD_SET);
  if (!fieldsResult.ok) return newsV1JsonError(fieldsResult.message, 400);

  const includeResult = parseIncludeSet(sp, new Set(["article"]), new Set(["article"]));
  if (!includeResult.ok) return newsV1JsonError(includeResult.message, 400);
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

  if (error) return newsV1JsonError("Internal error", 500);
  if (data === null) {
    return newsV1JsonError("Impact head not found", 404);
  }

  type RowIn = Parameters<typeof shapeImpactHeadRow>[0];
  const row = data as unknown as RowIn;
  const shaped = includeArticle
    ? shapeImpactHeadRow(row)
    : shapeImpactHeadRow({ ...row, news_articles: null });

  const fields = fieldsResult.value;
  const body =
    fields === null ? shaped : pickImpactHeadFields(shaped, fields);

  return NextResponse.json({ data: body }, { headers: NEWS_V1_CORS });
}
