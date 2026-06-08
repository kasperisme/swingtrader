// Server-side Telegram sender. Posts an HTML message to a user's chat via the
// Bot API. Best-effort: returns false (and logs) on any failure so callers can
// fire confirmations without risking the surrounding operation.

const BOT_TOKEN = process.env.TELEGRAM_BOT_TOKEN ?? "";

/** Escape the five characters Telegram's HTML parse mode treats specially. */
export function escapeTelegramHtml(input: string): string {
  return input
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

export async function sendTelegramMessage(
  chatId: string,
  html: string,
): Promise<boolean> {
  if (!BOT_TOKEN || !chatId) return false;
  try {
    const res = await fetch(
      `https://api.telegram.org/bot${BOT_TOKEN}/sendMessage`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          chat_id: chatId,
          text: html,
          parse_mode: "HTML",
          disable_web_page_preview: true,
        }),
      },
    );
    if (!res.ok) {
      console.error("[telegram] sendMessage failed", res.status, await res.text().catch(() => ""));
    }
    return res.ok;
  } catch (err) {
    console.error("[telegram] sendMessage error", err);
    return false;
  }
}
