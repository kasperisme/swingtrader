import { NextRequest, NextResponse } from "next/server";
import { createServiceClient } from "@/lib/supabase/service";

// Telegram sends this header when a secret_token was set during setWebhook.
// Set TELEGRAM_WEBHOOK_SECRET to any random string in Vercel env vars,
// and pass the same value when registering the webhook (see README).
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

// ── GET /api/user/telegram/webhook ───────────────────────────────────────────
// Health-check — confirms the endpoint is reachable (Telegram only sends POST).
export function GET() {
  return NextResponse.json({ ok: true, note: "Telegram webhook endpoint. Expects POST from Telegram." });
}

// ── POST /api/user/telegram/webhook ──────────────────────────────────────────
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

  // 2. Extract the message — only handle text messages
  const message = update.message as Record<string, unknown> | undefined;
  if (!message) return NextResponse.json({ ok: true }); // ignore non-message updates

  const text = (message.text as string | undefined)?.trim() ?? "";
  const chat = message.chat as Record<string, unknown>;
  const chat_id = chat.id as number;
  const first_name = ((message.from as Record<string, unknown>)?.first_name as string) ?? "there";

  // 3. Route commands
  if (text.startsWith("/start")) {
    const token = text.slice("/start".length).trim();
    await handleStart(chat_id, first_name, token);
  }
  // Ignore all other messages — no noisy replies

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

  // Look up the token — must be valid and not expired
  const { data: rows, error } = await supabase
    .schema("swingtrader")
    .from("user_narrative_preferences")
    .select("user_id, telegram_link_expires_at")
    .eq("telegram_link_token", token)
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
  if (row.telegram_link_expires_at && row.telegram_link_expires_at < now) {
    await sendTelegramMessage(
      chat_id,
      "❌ This link has <b>expired</b> (links are valid for 15 minutes).\n\n" +
      "Please go back to the app and generate a new one.",
    );
    return;
  }

  // Fetch current delivery_method so we don't downgrade 'both'
  const { data: prefs } = await supabase
    .schema("swingtrader")
    .from("user_narrative_preferences")
    .select("delivery_method")
    .eq("user_id", row.user_id)
    .limit(1)
    .single();

  const currentMethod = prefs?.delivery_method ?? "in_app";
  const newMethod = currentMethod === "both" ? "both" : "telegram";

  // Save chat_id, clear the token
  const { error: updateErr } = await supabase
    .schema("swingtrader")
    .from("user_narrative_preferences")
    .update({
      telegram_chat_id: String(chat_id),
      telegram_link_token: null,
      telegram_link_expires_at: null,
      delivery_method: newMethod,
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
