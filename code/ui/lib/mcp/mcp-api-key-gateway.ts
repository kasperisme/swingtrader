import type { AuthInfo } from "@modelcontextprotocol/sdk/server/auth/types.js";
import {
  authenticateUserApiKeyFromAuthorizationHeader,
  type UserApiKeyAuthFailureReason,
  type ValidatedKey,
  userApiKeyRateLimitMessage,
  USER_API_KEY_BEARER_EXPECTED,
} from "@/lib/api-auth";

const JSON_HEADERS = { "Content-Type": "application/json" };

export function validatedKeyToMcpAuthInfo(key: ValidatedKey, rawKey: string): AuthInfo {
  return {
    token: rawKey,
    clientId: key.userId,
    scopes: key.scopes,
    extra: { keyId: key.keyId },
  };
}

/** Same status bodies as v1 REST (`{ error: string }`) for pre-MCP auth failures. */
export function mcpJsonResponseForUserApiKeyFailure(reason: UserApiKeyAuthFailureReason): Response {
  switch (reason) {
    case "missing_or_malformed_header":
      return new Response(JSON.stringify({ error: USER_API_KEY_BEARER_EXPECTED }), {
        status: 401,
        headers: JSON_HEADERS,
      });
    case "invalid_key_length":
    case "invalid":
      return new Response(JSON.stringify({ error: "Invalid API key" }), {
        status: 401,
        headers: JSON_HEADERS,
      });
    case "rate_limited":
      return new Response(JSON.stringify({ error: userApiKeyRateLimitMessage() }), {
        status: 429,
        headers: { ...JSON_HEADERS, "Retry-After": "60" },
      });
  }
}

/**
 * Run MCP only after the same user API key checks as v1 REST. Attaches `req.auth` for tools.
 */
export async function runMcpWithUserApiKeyAuth(
  req: Request,
  mcpHandler: (request: Request) => Response | Promise<Response>,
): Promise<Response> {
  const auth = await authenticateUserApiKeyFromAuthorizationHeader(req.headers.get("authorization"));
  if (!auth.ok) {
    return mcpJsonResponseForUserApiKeyFailure(auth.reason);
  }

  const authInfo = validatedKeyToMcpAuthInfo(auth.key, auth.rawKey);
  (req as Request & { auth?: AuthInfo }).auth = authInfo;
  return mcpHandler(req);
}
