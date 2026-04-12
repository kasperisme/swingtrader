import { NextRequest, NextResponse } from "next/server";
import { createServiceClient } from "@/lib/supabase/service";

const WEBHOOK_SECRET = process.env.TELEGRAM_WEBHOOK_SECRET ?? "";
const BOT_TOKEN = process.env.TELEGRAM_BOT_TOKEN ?? "";

async function sendTelegramMessage(chat_id: number, text: string): Promise<void> {
  if (!BOT_TOKEN) return;
  await fetch(`https://api.telegram.org/bot${BOT_TOKEN}/sendMessage`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chat_id, text, parse_mode: "HTML" }),
  }).catch(() => {});
}

// ── GET /api/telegram-webhook ─────────────────────────────────────────────────
// Health-check — Telegram only sends POST, this is just for browser verification.
export function GET() {
  return NextResponse.json({ ok: true, note: "Telegram webhook endpoint. Expects POST from Telegram." });
}

// ── POST /api/telegram-webhook ────────────────────────────────────────────────
// Telegram pushes all bot updates here. Must return 200 quickly or Telegram retries.
export async function POST(req: NextRequest) {
  // 1. Verify the request is from Telegram
  if (WEBHOOK_SECRET) {
    const incoming = req.headers.get("x-telegram-bot-api-secret-token") ?? "";
    if (incoming !== WEBHOOK_SECRET) {
      return NextResponse.json({ error: "Forbidden" }, { status: 403 });
    }
  }

  let update: Record<string, unknown>;
  try {
    update = await req.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON" }, { status: 400 });
  }

  const message = update.message as Record<string, unknown> | undefined;
  if (!message) return NextResponse.json({ ok: true });

  const text = (message.text as string | undefined)?.trim() ?? "";
  const chat = message.chat as Record<string, unknown>;
  const chat_id = chat.id as number;
  const first_name = ((message.from as Record<string, unknown>)?.first_name as string) ?? "there";

  if (text.startsWith("/start")) {
    const token = text.slice("/start".length).trim();
    await handleStart(chat_id, first_name, token);
  }

  // Always return 200 so Telegram doesn't retry
  return NextResponse.json({ ok: true });
}

async function handleStart(chat_id: number, first_name: string, token: string): Promise<void> {
  if (!token) {
    await sendTelegramMessage(
      chat_id,
      `👋 Hi <b>${first_name}</b>!\n\n` +
      "To connect your Swingtrader account, open the app and click " +
      "<b>Connect Telegram</b> — you'll get a personal link to tap here.",
    );
    return;
  }

  // Service-role client — bypasses RLS since there is no user session on a webhook request
  const supabase = createServiceClient();
  const now = new Date().toISOString();

  // Look up the token in user_telegram_connections
  const { data: rows, error } = await supabase
    .schema("swingtrader")
    .from("user_telegram_connections")
    .select("user_id, link_expires_at")
    .eq("link_token", token)
    .limit(1);

  if (error || !rows?.length) {
    await sendTelegramMessage(
      chat_id,
      "❌ This link has <b>expired or is invalid</b>.\n\n" +
      "Please go back to the Swingtrader app and generate a new one.",
    );
    return;
  }

  const row = rows[0];
  if (row.link_expires_at && row.link_expires_at < now) {
    await sendTelegramMessage(
      chat_id,
      "❌ This link has <b>expired</b> (links are valid for 15 minutes).\n\n" +
      "Please go back to the app and generate a new one.",
    );
    return;
  }

  // Save chat_id, clear the token, record connected_at
  const { error: updateErr } = await supabase
    .schema("swingtrader")
    .from("user_telegram_connections")
    .update({
      chat_id: String(chat_id),
      link_token: null,
      link_expires_at: null,
      connected_at: now,
    })
    .eq("user_id", row.user_id);

  if (updateErr) {
    await sendTelegramMessage(
      chat_id,
      "⚠️ Something went wrong linking your account. Please try again from the app.",
    );
    return;
  }

  await sendTelegramMessage(
    chat_id,
    "✅ <b>Telegram connected!</b>\n\n" +
    "You'll receive your personalised Daily Narrative each weekday at <b>08:30 ET</b> — " +
    "covering your portfolio positions, active screening candidates, and alert watch.\n\n" +
    "<i>Not financial advice.</i>",
  );
}
