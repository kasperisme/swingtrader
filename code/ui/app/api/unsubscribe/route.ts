import { type NextRequest } from "next/server";
import {
  unsubscribeEmail,
  verifyUnsubscribeToken,
} from "@/lib/email/screening-subscriptions";
import { captureServer } from "@/lib/analytics/server";

const APP_URL =
  process.env.NEXT_PUBLIC_APP_URL ?? "https://newsimpactscreener.com";

function page(title: string, body: string, status: number): Response {
  const html = `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <meta name="robots" content="noindex" />
    <title>${title} — News Impact Screener</title>
    <style>
      :root { color-scheme: dark; }
      body {
        margin: 0; min-height: 100vh; display: flex; align-items: center;
        justify-content: center; background: #0b0f17;
        font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont,
          'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
        color: #e6e9ef; padding: 24px;
      }
      .card {
        max-width: 420px; width: 100%; background: #111620;
        border: 1px solid #1e2533; border-radius: 12px; padding: 28px;
      }
      .eyebrow {
        font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
        font-size: 11px; letter-spacing: 0.18em; text-transform: uppercase;
        color: #f5a623; margin: 0 0 14px 0;
      }
      h1 { font-size: 20px; line-height: 1.3; margin: 0 0 10px 0; }
      p { font-size: 14px; line-height: 1.6; color: #8b93a7; margin: 0 0 18px 0; }
      a.btn {
        display: inline-block; font-size: 14px; font-weight: 600; color: #0b0f17;
        background: #f5a623; padding: 10px 18px; border-radius: 8px;
        text-decoration: none;
      }
    </style>
  </head>
  <body>
    <div class="card">
      <p class="eyebrow">News Impact Screener</p>
      <h1>${title}</h1>
      <p>${body}</p>
      <a class="btn" href="${APP_URL.replace(/\/$/, "")}/marketscreenings">Browse screenings</a>
    </div>
  </body>
</html>`;
  return new Response(html, {
    status,
    headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" },
  });
}

export async function GET(req: NextRequest) {
  const token = req.nextUrl.searchParams.get("token") ?? "";
  const payload = verifyUnsubscribeToken(token);
  if (!payload) {
    return page(
      "Invalid link",
      "This unsubscribe link is invalid or has expired. If you keep receiving emails you didn't ask for, reply to one and we'll remove you.",
      400,
    );
  }

  const { removed } = await unsubscribeEmail({
    email: payload.email,
    slugs: payload.slugs,
  });

  captureServer(payload.email, "screening_email_unsubscribed", {
    slugs: payload.slugs,
    removed_count: removed.length,
  });

  const detail =
    removed.length > 0
      ? `You won't receive results for ${removed.join(", ")} anymore.`
      : "You're already unsubscribed — nothing else to do.";

  return page("You've been unsubscribed", detail, 200);
}
