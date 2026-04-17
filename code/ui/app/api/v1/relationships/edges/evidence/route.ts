import { NextRequest, NextResponse } from "next/server";
import { listRelationshipEdgeEvidenceFromSearchParams } from "@/lib/api-v1/relationships-network-service";
import {
  RELATIONSHIPS_V1_CORS,
  relationshipsV1JsonError,
  relationshipsV1OptionsResponse,
  requireRelationshipsReadBearer,
} from "@/lib/api-v1/relationships-public";

export async function OPTIONS() {
  return relationshipsV1OptionsResponse();
}

export async function GET(req: NextRequest) {
  const auth = await requireRelationshipsReadBearer(req);
  if (!auth.ok) return auth.response;

  const result = await listRelationshipEdgeEvidenceFromSearchParams(req.nextUrl.searchParams);
  if (!result.ok) return relationshipsV1JsonError(result.message, result.status);

  return NextResponse.json(result.body, { headers: RELATIONSHIPS_V1_CORS });
}
