import { NextResponse, type NextRequest } from "next/server";
import { z } from "zod";
import { createClient } from "@/lib/supabase/server";
import {
  isValidEmail,
  normalizeTags,
  normalizeTickers,
  upsertBriefingSubscription,
} from "@/lib/email/briefing-subscriptions";
import { recordEarlyAccessSignup } from "@/lib/email/early-access-signups";
import { captureServer } from "@/lib/analytics/server";

const bodySchema = z.object({
  email: z.string().trim().max(320),
  tickers: z.array(z.string().trim().max(20)).max(50).optional().default([]),
  tags: z.array(z.string().trim().max(50)).max(50).optional().default([]),
  source: z.string().trim().max(64).optional(),
});

export async function POST(req: NextRequest) {
  let json: unknown;
  try {
    json = await req.json();
  } catch {
    return NextResponse.json({ error: "invalid_request" }, { status: 400 });
  }

  const parsed = bodySchema.safeParse(json);
  if (!parsed.success) {
    return NextResponse.json({ error: "invalid_request" }, { status: 400 });
  }

  const email = parsed.data.email.toLowerCase();
  if (!isValidEmail(email)) {
    return NextResponse.json({ error: "invalid_email" }, { status: 400 });
  }

  const tickers = normalizeTickers(parsed.data.tickers);
  const tags = normalizeTags(parsed.data.tags);
  if (tickers.length === 0 && tags.length === 0) {
    return NextResponse.json({ error: "empty_watchlist" }, { status: 400 });
  }

  // Best-effort: attach the current auth user + request context.
  let userId: string | null = null;
  try {
    const supabase = await createClient();
    const { data: claims } = await supabase.auth.getClaims();
    userId = claims?.claims?.sub ?? null;
  } catch {
    userId = null;
  }

  const source = parsed.data.source || "briefing_subscribe";

  try {
    await upsertBriefingSubscription({
      email,
      tickers,
      tags,
      source,
      userId,
      referrer: req.headers.get("referer"),
      userAgent: req.headers.get("user-agent"),
    });
  } catch {
    return NextResponse.json({ error: "server_error" }, { status: 500 });
  }

  // Every briefing subscriber also belongs on the early-access list. Best-effort
  // and idempotent — never fail the subscription if this insert hiccups.
  try {
    const result = await recordEarlyAccessSignup({
      email,
      source,
      metadata: {
        via: "news_briefing",
        tickers,
        tags,
        authenticated: Boolean(userId),
        referrer: req.headers.get("referer") ?? undefined,
      },
    });
    if (!result.ok) {
      console.error("[briefings/subscribe] early-access record failed", result.error);
    }
  } catch (err) {
    console.error("[briefings/subscribe] early-access record threw", err);
  }

  captureServer(userId ?? email, "briefing_subscribed", {
    tickers,
    tags,
    source,
    authenticated: Boolean(userId),
    $set: { email },
  });

  // The first PDF is generated + sent by the Python briefing tick within ~1 min
  // (it reads initial_briefing_requested_at). The route never renders a PDF.
  return NextResponse.json({ success: true });
}
