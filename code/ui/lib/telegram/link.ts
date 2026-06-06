import { randomBytes } from "crypto";
import type { createClient } from "@/lib/supabase/server";

type ServerClient = Awaited<ReturnType<typeof createClient>>;

export const TELEGRAM_TOKEN_TTL_MINUTES = 15;

export function getTelegramBotUsername(): string {
  return process.env.TELEGRAM_BOT_USERNAME ?? "";
}

export type TelegramLinkResult =
  | { ok: true; deep_link: string; expires_at: string }
  | { ok: false; error: string };

export type TelegramStatus = {
  connected: boolean;
  chat_id: string | null;
  connected_at: string | null;
};

/**
 * Mint a one-time link token and return the Telegram deep link the user taps to
 * pair their account. The webhook resolves the token → user_id when the user
 * sends /start. Shared by the /api/user/telegram route and the AI setup tools.
 */
export async function generateTelegramLink(
  supabase: ServerClient,
  userId: string,
): Promise<TelegramLinkResult> {
  const botUsername = getTelegramBotUsername();
  if (!botUsername) {
    return {
      ok: false,
      error: "TELEGRAM_BOT_USERNAME is not configured on the server",
    };
  }

  const token = randomBytes(18).toString("base64url"); // 24-char URL-safe token
  const expiresAt = new Date(
    Date.now() + TELEGRAM_TOKEN_TTL_MINUTES * 60 * 1000,
  ).toISOString();

  const { error } = await supabase
    .schema("swingtrader")
    .from("user_telegram_connections")
    .upsert(
      { user_id: userId, link_token: token, link_expires_at: expiresAt },
      { onConflict: "user_id" },
    );

  if (error) {
    console.error("telegram connect upsert failed:", error);
    return { ok: false, error: "Failed to generate link" };
  }

  return {
    ok: true,
    deep_link: `https://t.me/${botUsername}?start=${token}`,
    expires_at: expiresAt,
  };
}

/**
 * Read the current Telegram connection status for a user. `connected` is true
 * once the webhook has written a chat_id (i.e. the user tapped /start).
 */
export async function getTelegramStatus(
  supabase: ServerClient,
  userId: string,
): Promise<TelegramStatus> {
  const { data, error } = await supabase
    .schema("swingtrader")
    .from("user_telegram_connections")
    .select("chat_id, connected_at")
    .eq("user_id", userId)
    .limit(1)
    .single();

  // PGRST116 = no row yet; treat as "not connected" rather than an error.
  if (error && error.code !== "PGRST116") {
    console.error("telegram status fetch failed:", error);
  }

  return {
    connected: Boolean(data?.chat_id),
    chat_id: data?.chat_id ?? null,
    connected_at: data?.connected_at ?? null,
  };
}
