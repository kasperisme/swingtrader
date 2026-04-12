import { NextRequest, NextResponse } from "next/server";
import type { ValidatedKey } from "@/lib/api-auth";
import { requireBearerApiKey, v1JsonError, v1OptionsResponse } from "@/lib/api-v1/bearer-auth";

/** CORS for public Bearer-authenticated news JSON endpoints */
export const NEWS_V1_CORS: HeadersInit = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, OPTIONS",
  "Access-Control-Allow-Headers": "Authorization",
};

export function newsV1JsonError(
  message: string,
  status: number,
  extra?: Record<string, unknown>,
) {
  return v1JsonError(NEWS_V1_CORS, message, status, extra);
}

/**
 * Validate `Authorization: Bearer <api_key>` and `news:read` scope.
 * On success returns the validated key record (for future auditing if needed).
 */
export async function requireNewsReadBearer(
  req: NextRequest,
): Promise<{ ok: true; key: ValidatedKey } | { ok: false; response: NextResponse }> {
  return requireBearerApiKey(req, NEWS_V1_CORS, ["news:read"]);
}

export function newsV1OptionsResponse() {
  return v1OptionsResponse(NEWS_V1_CORS);
}
