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
