import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { generateTelegramLink, getTelegramStatus } from "@/lib/telegram/link";

// ── POST /api/user/telegram ───────────────────────────────────────────────────
// Generate a one-time link token and return the Telegram deep link.
// The webhook resolves the token → user_id mapping when the user taps /start.
export async function POST() {
  const supabase = await createClient();
  const { data: { user }, error: authErr } = await supabase.auth.getUser();
  if (authErr || !user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const result = await generateTelegramLink(supabase, user.id);
  if (!result.ok) {
    return NextResponse.json({ error: result.error }, { status: 500 });
  }

  return NextResponse.json({
    deep_link: result.deep_link,
    expires_at: result.expires_at,
  });
}

// ── GET /api/user/telegram ────────────────────────────────────────────────────
// Returns the current Telegram connection status for the authenticated user.
export async function GET() {
  const supabase = await createClient();
  const { data: { user }, error: authErr } = await supabase.auth.getUser();
  if (authErr || !user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const status = await getTelegramStatus(supabase, user.id);
  return NextResponse.json(status);
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
