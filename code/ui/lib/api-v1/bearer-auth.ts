import { NextRequest, NextResponse } from "next/server";
import {
  authenticateUserApiKeyFromAuthorizationHeader,
  type ValidatedKey,
  userApiKeyRateLimitMessage,
  USER_API_KEY_BEARER_EXPECTED,
} from "@/lib/api-auth";

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
  const auth = await authenticateUserApiKeyFromAuthorizationHeader(req.headers.get("authorization"));

  if (!auth.ok) {
    switch (auth.reason) {
      case "missing_or_malformed_header":
        return { ok: false, response: v1JsonError(cors, USER_API_KEY_BEARER_EXPECTED, 401) };
      case "invalid_key_length":
      case "invalid":
        return { ok: false, response: v1JsonError(cors, "Invalid API key", 401) };
      case "rate_limited":
        return {
          ok: false,
          response: v1JsonError(cors, userApiKeyRateLimitMessage(), 429, {
            "Retry-After": "60",
          }),
        };
    }
  }

  for (const scope of requiredScopes) {
    if (!auth.key.scopes.includes(scope)) {
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

  return { ok: true, key: auth.key };
}
