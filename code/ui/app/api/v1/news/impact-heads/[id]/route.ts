import { NextRequest, NextResponse } from "next/server";
import { getNewsImpactHeadById } from "@/lib/api-v1/news-impact-heads-service";
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

  const result = await getNewsImpactHeadById(id, req.nextUrl.searchParams);
  if (!result.ok) return newsV1JsonError(result.message, result.status);

  return NextResponse.json(result.body, { headers: NEWS_V1_CORS });
}
