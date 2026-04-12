import { NextRequest, NextResponse } from "next/server";
import { listNewsImpactHeadsFromSearchParams } from "@/lib/api-v1/news-impact-heads-service";
import {
  NEWS_V1_CORS,
  newsV1JsonError,
  newsV1OptionsResponse,
  requireNewsReadBearer,
} from "@/lib/api-v1/news-public";

export async function OPTIONS() {
  return newsV1OptionsResponse();
}

export async function GET(req: NextRequest) {
  const auth = await requireNewsReadBearer(req);
  if (!auth.ok) return auth.response;

  const result = await listNewsImpactHeadsFromSearchParams(req.nextUrl.searchParams);
  if (!result.ok) return newsV1JsonError(result.message, result.status);

  return NextResponse.json(result.body, { headers: NEWS_V1_CORS });
}
