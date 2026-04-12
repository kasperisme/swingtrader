import { createHash, randomBytes } from "crypto";
import { createServiceClient } from "./supabase/service";

const KEY_PREFIX = "st_live_";
/** Max requests per minute per key */
export const RATE_LIMIT_PER_MINUTE = 60;

// ---------------------------------------------------------------------------
// Key generation
// ---------------------------------------------------------------------------

export function hashApiKey(key: string): string {
  return createHash("sha256").update(key).digest("hex");
}

/**
 * Generate a new API key triple:
 *   key         — the full secret shown to the user once (never stored)
 *   displayPrefix — truncated form stored in DB and shown in the UI
 *   hash        — SHA-256 stored in DB for lookups
 */
export function generateApiKey(): {
  key: string;
  displayPrefix: string;
  hash: string;
} {
  const hex = randomBytes(32).toString("hex");
  const key = `${KEY_PREFIX}${hex}`;
  const displayPrefix = `${KEY_PREFIX}${hex.slice(0, 8)}…`;
  return { key, displayPrefix, hash: hashApiKey(key) };
}

// ---------------------------------------------------------------------------
// Validation
// ---------------------------------------------------------------------------

export type ValidatedKey = {
  keyId: string;
  userId: string;
  scopes: string[];
};

export type ValidationResult =
  | { ok: true; key: ValidatedKey }
  | { ok: false; rateLimited: true }
  | { ok: false; rateLimited: false };

/**
 * Validate a raw API key and enforce per-minute rate limiting.
 *
 * - Returns { ok: true, key } on success.
 * - Returns { ok: false, rateLimited: true } when the key is valid but has
 *   exceeded its rate limit (caller should respond 429).
 * - Returns { ok: false, rateLimited: false } when the key is invalid,
 *   revoked, or expired (caller should respond 401).
 *
 * Uses SECURITY DEFINER function `swingtrader.validate_api_key()` for
 * atomic last_used_at update + rate-limit increment.
 */
export async function validateApiKey(rawKey: string): Promise<ValidationResult> {
  const hash = hashApiKey(rawKey);
  const supabase = createServiceClient();

  const { data, error } = await supabase
    .schema("swingtrader")
    .rpc("validate_api_key", {
      p_key_hash: hash,
      p_rate_limit_per_minute: RATE_LIMIT_PER_MINUTE,
    });

  if (error || !data || (data as unknown[]).length === 0) {
    return { ok: false, rateLimited: false };
  }

  const row = (data as Array<{
    key_id: string;
    user_id: string;
    scopes: string[];
    rate_ok: boolean;
  }>)[0];

  if (!row.rate_ok) {
    return { ok: false, rateLimited: true };
  }

  return {
    ok: true,
    key: { keyId: row.key_id, userId: row.user_id, scopes: row.scopes },
  };
}

// ---------------------------------------------------------------------------
// Shared HTTP Bearer parsing + validation (v1 REST + MCP use the same path)
// ---------------------------------------------------------------------------

/** Same message as v1 `requireBearerApiKey` when the header is missing or not Bearer. */
export const USER_API_KEY_BEARER_EXPECTED =
  "Missing or malformed Authorization header. Expected: Authorization: Bearer <api_key>";

export function userApiKeyRateLimitMessage(): string {
  return `Rate limit exceeded. Maximum ${RATE_LIMIT_PER_MINUTE} requests per minute per key.`;
}

export type UserApiKeyAuthFailureReason =
  | "missing_or_malformed_header"
  | "invalid_key_length"
  | "invalid"
  | "rate_limited";

export type UserApiKeyAuthResult =
  | { ok: true; key: ValidatedKey; rawKey: string }
  | { ok: false; reason: UserApiKeyAuthFailureReason };

/**
 * Parse `Authorization: Bearer <api_key>` and validate via `validateApiKey`.
 * Used by v1 REST and `/api/mcp` so one key has the same limits, scopes from DB, and timing behavior.
 */
export async function authenticateUserApiKeyFromAuthorizationHeader(
  authorizationHeader: string | null,
): Promise<UserApiKeyAuthResult> {
  const authHeader = authorizationHeader ?? "";
  const match = /^Bearer\s+(\S+)$/i.exec(authHeader);
  if (!match) {
    return { ok: false, reason: "missing_or_malformed_header" };
  }
  const rawKey = match[1];
  if (rawKey.length < 16 || rawKey.length > 200) {
    return { ok: false, reason: "invalid_key_length" };
  }

  const result = await validateApiKey(rawKey);
  if (!result.ok && result.rateLimited) {
    return { ok: false, reason: "rate_limited" };
  }
  if (!result.ok) {
    await new Promise((r) => setTimeout(r, 50 + Math.random() * 50));
    return { ok: false, reason: "invalid" };
  }

  return { ok: true, key: result.key, rawKey };
}

/** Scopes that may be assigned when creating an API key in the dashboard. */
export const API_KEY_SCOPE_ALLOWLIST = ["news:read", "screenings:write"] as const;

export type ApiKeyScopeAllowlist = (typeof API_KEY_SCOPE_ALLOWLIST)[number];

/**
 * Parse `scopes` from a create-key request body.
 * Defaults to `["news:read"]` when omitted. Returns an error message if invalid.
 */
export function parseApiKeyScopesInput(raw: unknown): { ok: true; scopes: string[] } | { ok: false; error: string } {
  if (raw === undefined || raw === null) {
    return { ok: true, scopes: ["news:read"] };
  }
  if (!Array.isArray(raw)) {
    return { ok: false, error: "scopes must be an array of strings" };
  }
  const set = new Set<string>();
  const allow = new Set<string>(API_KEY_SCOPE_ALLOWLIST);
  for (const item of raw) {
    if (typeof item !== "string" || !allow.has(item)) {
      return {
        ok: false,
        error: `each scope must be one of: ${API_KEY_SCOPE_ALLOWLIST.join(", ")}`,
      };
    }
    set.add(item);
  }
  if (set.size === 0) {
    return { ok: false, error: "scopes must include at least one allowed scope" };
  }
  return { ok: true, scopes: Array.from(set) };
}
