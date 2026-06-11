import { NextResponse, type NextRequest } from "next/server";
import { z } from "zod";
import {
  normalizeTags,
  normalizeTickers,
  unsubscribeBriefing,
  updateBriefingPreferences,
  verifyBriefingToken,
} from "@/lib/email/briefing-subscriptions";
import { captureServer } from "@/lib/analytics/server";

const bodySchema = z.object({
  token: z.string().min(1).max(2000),
  action: z.enum(["update", "unsubscribe"]).default("update"),
  tickers: z.array(z.string().trim().max(20)).max(50).optional().default([]),
  tags: z.array(z.string().trim().max(50)).max(50).optional().default([]),
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

  const payload = verifyBriefingToken(parsed.data.token);
  if (!payload) {
    return NextResponse.json({ error: "invalid_token" }, { status: 401 });
  }
  const email = payload.email;

  if (parsed.data.action === "unsubscribe") {
    await unsubscribeBriefing(email);
    captureServer(email, "briefing_unsubscribed", { via: "manage" });
    return NextResponse.json({ success: true, unsubscribed: true });
  }

  const tickers = normalizeTickers(parsed.data.tickers);
  const tags = normalizeTags(parsed.data.tags);
  if (tickers.length === 0 && tags.length === 0) {
    return NextResponse.json({ error: "empty_watchlist" }, { status: 400 });
  }

  const ok = await updateBriefingPreferences({ email, tickers, tags });
  if (!ok) {
    return NextResponse.json({ error: "server_error" }, { status: 500 });
  }
  captureServer(email, "briefing_updated", { tickers, tags });
  return NextResponse.json({ success: true });
}
