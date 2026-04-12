import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { randomBytes } from "crypto";

const TOKEN_TTL_MINUTES = 15;
const BOT_USERNAME = process.env.TELEGRAM_BOT_USERNAME ?? "";

// ── POST /api/user/telegram ───────────────────────────────────────────────────
// Generate a one-time link token and return the Telegram deep link.
// The bot script resolves the token → user_id mapping when the user clicks start.
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

  // Upsert preferences row — create it if this user hasn't set prefs yet
  const { error } = await supabase
    .schema("swingtrader")
    .from("user_narrative_preferences")
    .upsert(
      {
        user_id: user.id,
        telegram_link_token: token,
        telegram_link_expires_at: expiresAt,
      },
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
    .from("user_narrative_preferences")
    .select("telegram_chat_id, delivery_method, is_enabled, delivery_time, lookback_hours")
    .eq("user_id", user.id)
    .limit(1)
    .single();

  if (error && error.code !== "PGRST116") {
    // PGRST116 = no rows found — user simply hasn't set prefs yet
    return NextResponse.json({ error: "Failed to fetch status" }, { status: 500 });
  }

  return NextResponse.json({
    connected: Boolean(data?.telegram_chat_id),
    chat_id: data?.telegram_chat_id ?? null,
    delivery_method: data?.delivery_method ?? "in_app",
    is_enabled: data?.is_enabled ?? true,
    delivery_time: data?.delivery_time ?? "08:30:00",
    lookback_hours: data?.lookback_hours ?? 24,
  });
}

// ── DELETE /api/user/telegram ─────────────────────────────────────────────────
// Disconnect Telegram — clears chat_id and reverts delivery_method to in_app.
export async function DELETE() {
  const supabase = await createClient();
  const { data: { user }, error: authErr } = await supabase.auth.getUser();
  if (authErr || !user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const { error } = await supabase
    .schema("swingtrader")
    .from("user_narrative_preferences")
    .upsert(
      {
        user_id: user.id,
        telegram_chat_id: null,
        telegram_link_token: null,
        telegram_link_expires_at: null,
        delivery_method: "in_app",
      },
      { onConflict: "user_id" },
    );

  if (error) return NextResponse.json({ error: "Failed to disconnect" }, { status: 500 });
  return NextResponse.json({ ok: true });
}
