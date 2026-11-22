import { NextResponse, type NextRequest } from "next/server";
import { z } from "zod";
import { createClient } from "@/lib/supabase/server";
import { sendEmail } from "@/lib/email/send";
import { isValidEmail, verifyUnsubscribeToken } from "@/lib/email/screening-subscriptions";
import {
  buildListUnsubscribeUrl,
  markListConfirmationSent,
  subscribeToList,
  unsubscribeFromList,
  type UpdateList,
} from "@/lib/email/update-lists";
import { captureServer } from "@/lib/analytics/server";
import { cleanAttribution } from "@/lib/attribution-server";

/**
 * Route handlers shared by every update list (/api/correction/*, /api/arena/*):
 * the lists differ only in table, copy and confirmation email.
 */

const APP_URL = (process.env.NEXT_PUBLIC_APP_URL ?? "https://newsimpactscreener.com").replace(/\/$/, "");

const bodySchema = z.object({
  email: z.string().trim().max(320),
  source: z.string().trim().max(64).optional(),
  attribution: z.unknown().optional(),
});

export function subscribeHandler(
  list: UpdateList,
  confirmation: (args: { appUrl: string; unsubscribeUrl: string }) => Promise<{ subject: string; html: string; text: string }>,
) {
  return async function POST(req: NextRequest) {
    let json: unknown;
    try {
      json = await req.json();
    } catch {
      return NextResponse.json({ error: "invalid_request" }, { status: 400 });
    }
    const parsed = bodySchema.safeParse(json);
    if (!parsed.success) return NextResponse.json({ error: "invalid_request" }, { status: 400 });
    const email = parsed.data.email.toLowerCase();
    if (!isValidEmail(email)) return NextResponse.json({ error: "invalid_email" }, { status: 400 });

    let userId: string | null = null;
    try {
      const { data: claims } = await (await createClient()).auth.getClaims();
      userId = claims?.claims?.sub ?? null;
    } catch {
      userId = null;
    }
    const utm = cleanAttribution(parsed.data.attribution);
    const source = parsed.data.source || `${list.slug}_subscribe`;

    const outcome = await subscribeToList(list, {
      email,
      source,
      userId,
      referrer: req.headers.get("referer"),
      userAgent: req.headers.get("user-agent"),
      metadata: Object.keys(utm).length > 0 ? { utm } : undefined,
    });
    if (outcome === "failed") return NextResponse.json({ error: "server_error" }, { status: 500 });

    captureServer(userId ?? email, `${list.slug}_updates_subscribed`, { source, outcome });
    if (outcome === "already_subscribed") return NextResponse.json({ success: true, already: true });

    const { subject, html, text } = await confirmation({
      appUrl: APP_URL,
      unsubscribeUrl: buildListUnsubscribeUrl(list, APP_URL, email),
    });
    // Persisted already; the confirmation is best-effort, as on the other lead magnets.
    const sent = await sendEmail({
      to: email,
      subject,
      html,
      text,
      tags: [{ name: "type", value: `${list.slug}_updates_confirmation` }],
    });
    if (sent.ok && outcome === "subscribed") void markListConfirmationSent(list, email);
    else if (!sent.ok) console.error(`[${list.slug}-subscribe] confirmation failed`, sent.error);

    return NextResponse.json({ success: true });
  };
}

function page(eyebrow: string, title: string, body: string, cta: { label: string; href: string }, status: number): Response {
  const html = `<!doctype html>
<html lang="en"><head><meta charset="utf-8" /><meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="robots" content="noindex" /><title>${title} — News Impact Screener</title>
<style>
  :root { color-scheme: dark; }
  body { margin:0; min-height:100vh; display:flex; align-items:center; justify-content:center; background:#0b0f17;
    font-family:'Plus Jakarta Sans',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif; color:#e6e9ef; padding:24px; }
  .card { max-width:420px; width:100%; background:#111620; border:1px solid #1e2533; border-radius:12px; padding:28px; }
  .eyebrow { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:11px; letter-spacing:.18em; text-transform:uppercase; color:#f5a623; margin:0 0 14px; }
  h1 { font-size:20px; line-height:1.3; margin:0 0 10px; }
  p { font-size:14px; line-height:1.6; color:#8b93a7; margin:0 0 18px; }
  a.btn { display:inline-block; font-size:14px; font-weight:600; color:#0b0f17; background:#f5a623; padding:10px 18px; border-radius:8px; text-decoration:none; }
</style></head>
<body><div class="card"><p class="eyebrow">${eyebrow}</p><h1>${title}</h1><p>${body}</p>
<a class="btn" href="${APP_URL}${cta.href}">${cta.label}</a></div></body></html>`;
  return new Response(html, { status, headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" } });
}

export function unsubscribeHandler(
  list: UpdateList,
  copy: { eyebrow: string; what: string; cta: { label: string; href: string } },
) {
  return async function GET(req: NextRequest) {
    const payload = verifyUnsubscribeToken(req.nextUrl.searchParams.get("token") ?? "");
    if (!payload || !payload.slugs.includes(list.slug)) {
      return page(
        copy.eyebrow,
        "Invalid link",
        "This unsubscribe link is invalid. If you keep receiving emails you didn't ask for, reply to one and we'll remove you.",
        copy.cta,
        400,
      );
    }
    const removed = await unsubscribeFromList(list, payload.email);
    captureServer(payload.email, `${list.slug}_updates_unsubscribed`, { removed });
    return page(
      copy.eyebrow,
      "You've been unsubscribed",
      removed ? `You won't get ${copy.what} anymore.` : "You're already unsubscribed. Nothing else to do.",
      copy.cta,
      200,
    );
  };
}
