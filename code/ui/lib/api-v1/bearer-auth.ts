import { NextRequest, NextResponse } from "next/server";
import { validateApiKey, type ValidatedKey } from "@/lib/api-auth";

export function v1JsonError(
  cors: HeadersInit,
  message: string,
  status: number,
  extra?: Record<string, unknown>,
) {
  return NextResponse.json({ error: message, ...extra }, { status, headers: cors });
}

export function v1OptionsResponse(cors: HeadersInit) {
  return new NextResponse(null, {
    status: 204,
    headers: { ...cors, "Access-Control-Max-Age": "86400" },
  });
}

/**
 * Validate `Authorization: Bearer <api_key>` and that the key has every required scope.
 */
export async function requireBearerApiKey(
  req: NextRequest,
  cors: HeadersInit,
  requiredScopes: readonly string[],
): Promise<{ ok: true; key: ValidatedKey } | { ok: false; response: NextResponse }> {
  const authHeader = req.headers.get("authorization") ?? "";
  const match = /^Bearer\s+(\S+)$/i.exec(authHeader);
  if (!match) {
    return {
      ok: false,
      response: v1JsonError(
        cors,
        "Missing or malformed Authorization header. Expected: Authorization: Bearer <api_key>",
        401,
      ),
    };
  }

  const rawKey = match[1];
  if (rawKey.length < 16 || rawKey.length > 200) {
    return { ok: false, response: v1JsonError(cors, "Invalid API key", 401) };
  }

  const result = await validateApiKey(rawKey);

  if (!result.ok && result.rateLimited) {
    return {
      ok: false,
      response: v1JsonError(cors, "Rate limit exceeded. Maximum 60 requests per minute per key.", 429, {
        "Retry-After": "60",
      }),
    };
  }

  if (!result.ok) {
    await new Promise((r) => setTimeout(r, 50 + Math.random() * 50));
    return { ok: false, response: v1JsonError(cors, "Invalid API key", 401) };
  }

  for (const scope of requiredScopes) {
    if (!result.key.scopes.includes(scope)) {
      return {
        ok: false,
        response: v1JsonError(
          cors,
          `Forbidden: this key does not have the '${scope}' scope`,
          403,
        ),
      };
    }
  }

  return { ok: true, key: result.key };
}
