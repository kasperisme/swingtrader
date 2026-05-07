import { NextResponse, type NextRequest } from "next/server";
import { z } from "zod";
import { addToWaitlistSegment } from "@/lib/email/segments";
import { sendTemplateEmail } from "@/lib/email/send";
import { createServiceClient } from "@/lib/supabase/service";
import { captureServer } from "@/lib/analytics/server";

const bodySchema = z.object({
  email: z.string().trim().email().max(320),
  source: z.string().trim().max(64).optional(),
});

async function sendWaitlistWelcome(email: string, source: string) {
  const templateId = process.env.RESEND_WAITLIST_WELCOME_TEMPLATE_ID;
  const appUrl = process.env.NEXT_PUBLIC_APP_URL ?? "https://newsimpactscreener.com";

  // Skip the send entirely if no template is configured. Segment add still runs.
  const sendPromise = templateId
    ? sendTemplateEmail({
        to: email,
        templateId,
        variables: { email, appUrl },
        tags: [
          { name: "type", value: "waitlist_welcome" },
          { name: "source", value: source.replace(/[^a-zA-Z0-9_-]/g, "_").slice(0, 64) },
        ],
      })
    : Promise.resolve({ ok: true as const, id: "skipped" });

  const [emailResult, segmentResult] = await Promise.allSettled([
    sendPromise,
    addToWaitlistSegment(email),
  ]);

  if (emailResult.status === "rejected") {
    console.error("[early-access] welcome email threw", emailResult.reason);
  } else if (!emailResult.value.ok) {
    console.error("[early-access] welcome email failed", emailResult.value.error);
  }
  if (segmentResult.status === "rejected") {
    console.error("[early-access] segment add threw", segmentResult.reason);
  } else if (!segmentResult.value.ok) {
    console.error("[early-access] segment add failed", segmentResult.value.error);
  }
}

/**
 * Public waitlist signup from the marketing site.
 * Persists to swingtrader.early_access_signups using the service role.
 */
export async function POST(req: NextRequest) {
  let json: unknown;
  try {
    json = await req.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON" }, { status: 400 });
  }

  const parsed = bodySchema.safeParse(json);
  if (!parsed.success) {
    return NextResponse.json({ error: "Invalid email" }, { status: 400 });
  }

  const email = parsed.data.email.toLowerCase();
  const source = parsed.data.source?.trim() || "landing";

  let supabase;
  try {
    supabase = createServiceClient();
  } catch {
    return NextResponse.json({ error: "Waitlist is temporarily unavailable." }, { status: 503 });
  }

  const { error } = await supabase
    .schema("swingtrader")
    .from("early_access_signups")
    .insert({ email, source });

  if (error) {
    // Unique violation — treat as idempotent success for UX / privacy
    if (error.code === "23505") {
      return NextResponse.json({ ok: true, duplicate: true });
    }
    console.error("[early-access] insert failed", error.message);
    return NextResponse.json({ error: "Could not save your signup. Please try again." }, { status: 500 });
  }

  // Fire-and-forget: don't block signup response on email/audience side effects.
  void sendWaitlistWelcome(email, source);

  captureServer(email, "waitlist_joined", { source, $set: { email } });

  return NextResponse.json({ ok: true });
}
