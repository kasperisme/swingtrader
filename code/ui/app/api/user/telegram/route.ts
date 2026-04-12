import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { randomBytes } from "crypto";

const TOKEN_TTL_MINUTES = 15;
const BOT_USERNAME = process.env.TELEGRAM_BOT_USERNAME ?? "";

// ── POST /api/user/telegram ───────────────────────────────────────────────────
// Generate a one-time link token and return the Telegram deep link.
// The webhook resolves the token → user_id mapping when the user taps /start.
export async function POST() {
  const supabase = await createClient();
  const { data: { user }, error: authErr } = await supabase.auth.getUser();
  if (authErr || !user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  if (!BOT_USERNAME) {
    return NextResponse.json(
      { error: "TELEGRAM_BOT_USERNAME is not configured on the server" },
      { status: 500 },
    );
  }

  const token = randomBytes(18).toString("base64url"); // 24-char URL-safe token
  const expiresAt = new Date(Date.now() + TOKEN_TTL_MINUTES * 60 * 1000).toISOString();

  const { error } = await supabase
    .schema("swingtrader")
    .from("user_telegram_connections")
    .upsert(
      { user_id: user.id, link_token: token, link_expires_at: expiresAt },
      { onConflict: "user_id" },
    );

  if (error) {
    console.error("telegram connect upsert failed:", error);
    return NextResponse.json({ error: "Failed to generate link" }, { status: 500 });
  }

  const deep_link = `https://t.me/${BOT_USERNAME}?start=${token}`;
  return NextResponse.json({ deep_link, expires_at: expiresAt });
}

// ── GET /api/user/telegram ────────────────────────────────────────────────────
// Returns the current Telegram connection status for the authenticated user.
export async function GET() {
  const supabase = await createClient();
  const { data: { user }, error: authErr } = await supabase.auth.getUser();
  if (authErr || !user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const { data, error } = await supabase
    .schema("swingtrader")
    .from("user_telegram_connections")
    .select("chat_id, connected_at")
    .eq("user_id", user.id)
    .limit(1)
    .single();

  if (error && error.code !== "PGRST116") {
    return NextResponse.json({ error: "Failed to fetch status" }, { status: 500 });
  }

  return NextResponse.json({
    connected: Boolean(data?.chat_id),
    chat_id: data?.chat_id ?? null,
    connected_at: data?.connected_at ?? null,
  });
}

// ── DELETE /api/user/telegram ─────────────────────────────────────────────────
// Disconnect — clears chat_id so no further messages are sent.
export async function DELETE() {
  const supabase = await createClient();
  const { data: { user }, error: authErr } = await supabase.auth.getUser();
  if (authErr || !user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const { error } = await supabase
    .schema("swingtrader")
    .from("user_telegram_connections")
    .update({ chat_id: null, link_token: null, link_expires_at: null })
    .eq("user_id", user.id);

  if (error) return NextResponse.json({ error: "Failed to disconnect" }, { status: 500 });
  return NextResponse.json({ ok: true });
}
