import { NextResponse, type NextRequest } from "next/server";
import { z } from "zod";
import { createClient } from "@/lib/supabase/server";
import { sendEmail } from "@/lib/email/send";
import { isValidEmail } from "@/lib/email/screening-subscriptions";
import {
  buildCorrectionUnsubscribeUrl,
  markCorrectionConfirmationSent,
  subscribeToCorrection,
} from "@/lib/email/correction-subscriptions";
import { renderCorrectionUpdatesConfirmation } from "@/emails/CorrectionUpdatesConfirmation";
import { getLatestRun } from "@/lib/drawdown/narrative";
import { captureServer } from "@/lib/analytics/server";
import { cleanAttribution } from "@/lib/attribution-server";

const bodySchema = z.object({
  email: z.string().trim().max(320),
  source: z.string().trim().max(64).optional(),
  attribution: z.unknown().optional(),
});

const APP_URL = process.env.NEXT_PUBLIC_APP_URL ?? "https://newsimpactscreener.com";

export async function POST(req: NextRequest) {
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
  const source = parsed.data.source || "correction_subscribe";

  const outcome = await subscribeToCorrection({
    email,
    source,
    userId,
    referrer: req.headers.get("referer"),
    userAgent: req.headers.get("user-agent"),
    metadata: Object.keys(utm).length > 0 ? { utm } : undefined,
  });
  if (outcome === "failed") return NextResponse.json({ error: "server_error" }, { status: 500 });

  captureServer(userId ?? email, "correction_updates_subscribed", { source, outcome });
  if (outcome === "already_subscribed") return NextResponse.json({ success: true, already: true });

  const latest = await getLatestRun().catch(() => null);
  const { subject, html, text } = renderCorrectionUpdatesConfirmation({
    appUrl: APP_URL,
    unsubscribeUrl: buildCorrectionUnsubscribeUrl(APP_URL, email),
    latestAsOf: latest?.asOf ?? null,
  });
  // Persisted already; the confirmation is best-effort, as on the other lead magnets.
  const sent = await sendEmail({ to: email, subject, html, text, tags: [{ name: "type", value: "correction_updates_confirmation" }] });
  if (sent.ok && outcome === "subscribed") void markCorrectionConfirmationSent(email);
  else if (!sent.ok) console.error("[correction-subscribe] confirmation failed", sent.error);

  return NextResponse.json({ success: true });
}
