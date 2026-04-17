import { NextRequest, NextResponse } from "next/server";
import type { ValidatedKey } from "@/lib/api-auth";
import { requireBearerApiKey, v1JsonError, v1OptionsResponse } from "@/lib/api-v1/bearer-auth";

/** CORS for Bearer-authenticated relationships JSON endpoints */
export const RELATIONSHIPS_V1_CORS: HeadersInit = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, OPTIONS",
  "Access-Control-Allow-Headers": "Authorization",
};

export function relationshipsV1JsonError(message: string, status: number, extra?: Record<string, unknown>) {
  return v1JsonError(RELATIONSHIPS_V1_CORS, message, status, extra);
}

/** Validate `Authorization: Bearer <api_key>` and `relationships:read` scope. */
export async function requireRelationshipsReadBearer(
  req: NextRequest,
): Promise<{ ok: true; key: ValidatedKey } | { ok: false; response: NextResponse }> {
  return requireBearerApiKey(req, RELATIONSHIPS_V1_CORS, ["relationships:read"]);
}

export function relationshipsV1OptionsResponse() {
  return v1OptionsResponse(RELATIONSHIPS_V1_CORS);
}
