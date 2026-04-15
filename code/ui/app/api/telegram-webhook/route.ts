import { NextRequest, NextResponse } from "next/server";
import { createServiceClient } from "@/lib/supabase/service";

const WEBHOOK_SECRET = process.env.TELEGRAM_WEBHOOK_SECRET ?? "";
const BOT_TOKEN = process.env.TELEGRAM_BOT_TOKEN ?? "";
const SCHEMA = "swingtrader";

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
  if (text.startsWith("/update")) {
    await handleUpdate(chat_id, first_name);
  }
  if (text.startsWith("/search")) {
    const query = text.slice("/search".length).trim();
    await handleSearch(chat_id, first_name, query);
  }
  if (text.startsWith("/health")) {
    await handleHealth(chat_id);
  }

  // Always return 200 so Telegram doesn't retry
  return NextResponse.json({ ok: true });
}

async function handleStart(chat_id: number, first_name: string, token: string): Promise<void> {
  if (!token) {
    await sendTelegramMessage(
      chat_id,
      `👋 Hi <b>${first_name}</b>!\n\n` +
      "To connect your NewsImpactScreener account, open the app and click " +
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
      "Please go back to the NewsImpactScreener app and generate a new one.",
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

async function handleUpdate(chat_id: number, first_name: string): Promise<void> {
  const inserted = await enqueueTelegramRequest(chat_id, first_name, "update", null);
  if (!inserted) {
    await sendTelegramMessage(
      chat_id,
      "⚠️ I couldn't queue your update right now. Please try /update again in a minute.",
    );
    return;
  }

  await sendTelegramMessage(
    chat_id,
    "🧠 Got it — building your personalised news update now.\n\nI'll send it here shortly.",
  );
}

async function handleSearch(chat_id: number, first_name: string, query: string): Promise<void> {
  if (!query) {
    await sendTelegramMessage(
      chat_id,
      "🔎 Usage: <code>/search &lt;search terms&gt;</code>\n\n" +
      "Example: <code>/search Novo Nordisk obesity trial results</code>",
    );
    return;
  }

  const inserted = await enqueueTelegramRequest(chat_id, first_name, "search", query);
  if (!inserted) {
    await sendTelegramMessage(
      chat_id,
      "⚠️ I couldn't queue your search right now. Please try /search again in a minute.",
    );
    return;
  }

  await sendTelegramMessage(
    chat_id,
    `🔎 Searching latest articles for: <b>${query}</b>\n\nI'll send the top matches shortly.`,
  );
}

async function enqueueTelegramRequest(
  chat_id: number,
  first_name: string,
  requestType: "update" | "search",
  requestText: string | null,
): Promise<boolean> {
  const supabase = createServiceClient();
  const { data: connRows, error: connError } = await supabase
    .schema(SCHEMA)
    .from("user_telegram_connections")
    .select("user_id")
    .eq("chat_id", String(chat_id))
    .limit(1);

  if (connError || !connRows?.length) {
    await sendTelegramMessage(
      chat_id,
      `👋 Hi <b>${first_name}</b>!\n\n` +
      "Your Telegram is not linked to a NewsImpactScreener account yet.\n" +
      "Open the app and use <b>Connect Telegram</b>, then try again.",
    );
    return false;
  }

  const userId = connRows[0].user_id as string;
  const { data: activeRows } = await supabase
    .schema(SCHEMA)
    .from("telegram_update_requests")
    .select("id")
    .eq("user_id", userId)
    .in("status", ["pending", "processing"])
    .limit(1);

  if (activeRows?.length) {
    await sendTelegramMessage(
      chat_id,
      "⏳ You already have a request in progress.\n\nI'll send it here as soon as it's ready.",
    );
    return false;
  }

  const { error: insertErr } = await supabase.schema(SCHEMA).from("telegram_update_requests").insert({
    user_id: userId,
    chat_id: String(chat_id),
    request_type: requestType,
    request_text: requestText,
    status: "pending",
  });

  return !insertErr;
}

function _parseIntervalH(raw: unknown): number | null {
  if (raw == null) return null;
  if (typeof raw === "number") return raw;
  if (typeof raw === "string") {
    try {
      let days = 0;
      let s = raw;
      if (s.includes("day")) {
        const [dayPart, rest] = s.split("day");
        days = parseInt(dayPart.trim(), 10);
        s = rest.replace(/^s/, "").trim();
      }
      const [h, m, sec] = s.split(":").map(Number);
      return days * 24 + h + m / 60 + sec / 3600;
    } catch { return null; }
  }
  return null;
}

function _fmtAge(isoStr: string | null): string {
  if (!isoStr) return "never";
  const diffMs = Date.now() - new Date(isoStr).getTime();
  const mins = Math.floor(diffMs / 60_000);
  if (mins < 90) return `${mins}m ago`;
  const h = diffMs / 3_600_000;
  if (h < 48) return `${h.toFixed(1)}h ago`;
  return `${(h / 24).toFixed(1)}d ago`;
}

async function handleHealth(chat_id: number): Promise<void> {
  const supabase = createServiceClient();
  const now = Date.now();

  const { data: jobs, error } = await supabase
    .schema(SCHEMA)
    .from("job_health")
    .select("job_name,last_finished_at,last_status,consecutive_fails,expected_interval,metadata")
    .order("job_name");

  if (error || !jobs) {
    await sendTelegramMessage(chat_id, "⚠️ Could not fetch health data from database.");
    return;
  }

  const alerts: string[] = [];
  const lines: string[] = [];

  for (const job of jobs) {
    const intervalH = _parseIntervalH(job.expected_interval);
    const status: string = job.last_status ?? "unknown";
    const finishedAt: string | null = job.last_finished_at;
    const fails: number = job.consecutive_fails ?? 0;

    let icon = "✅";
    let note = finishedAt ? _fmtAge(finishedAt) : "never run";

    if (status === "failed") {
      icon = "❌";
      note = `failed (×${fails})`;
      alerts.push(job.job_name);
    } else if (status === "running") {
      icon = "⏳";
      note = "running";
    } else if (intervalH && finishedAt) {
      const ageH = (now - new Date(finishedAt).getTime()) / 3_600_000;
      if (ageH > intervalH * 1.5) {
        icon = "⚠️";
        note = `stale — ${_fmtAge(finishedAt)}`;
        alerts.push(job.job_name);
      }
    } else if (intervalH && !finishedAt) {
      icon = "⚠️";
      note = "never finished";
      alerts.push(job.job_name);
    }

    lines.push(`${icon} <code>${job.job_name}</code> — ${note}`);
  }

  // Watchdog metadata summary
  const watchdog = jobs.find((j) => j.job_name === "watchdog");
  const meta = watchdog?.metadata as Record<string, unknown> | null;
  const watchdogLine = meta
    ? `\n🐾 <b>Watchdog</b>: checked ${meta.jobs_checked ?? "?"} jobs, ` +
      `${meta.alerts_fired ?? 0} alert(s), ` +
      `${(meta.logs_clean as string[] | undefined)?.length ?? 0} log(s) clean`
    : "";

  const header = alerts.length === 0
    ? "✅ <b>All systems go</b>"
    : `⚠️ <b>${alerts.length} alert(s)</b>: ${alerts.join(", ")}`;

  const msg = [
    header,
    "",
    ...lines,
    watchdogLine,
  ].filter((l) => l !== undefined).join("\n").trim();

  await sendTelegramMessage(chat_id, msg);
}
