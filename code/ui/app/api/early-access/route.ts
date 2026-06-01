import { NextResponse, type NextRequest } from "next/server";
import { z } from "zod";
import { addToWaitlistSegment } from "@/lib/email/segments";
import { sendTemplateEmail } from "@/lib/email/send";
import { createServiceClient } from "@/lib/supabase/service";
import { captureServer } from "@/lib/analytics/server";

const bodySchema = z.object({
  email: z.string().trim().email().max(320),
  source: z.string().trim().max(64).optional(),
  // A/B test variant the user was exposed to (e.g. the article CTA copy).
  variant: z.string().trim().max(64).optional(),
  // The full CTA copy the user actually saw (heading/body/label, etc.). Capped
  // field count + length because this endpoint is public and client-supplied.
  ctaText: z
    .record(z.string().max(64), z.string().max(2000))
    .refine((o) => Object.keys(o).length <= 12, "Too many CTA fields")
    .optional(),
  // Which article the signup came from (article CTA only).
  article: z
    .object({
      slug: z.string().max(200).optional(),
      id: z.number().int().optional(),
      title: z.string().max(500).optional(),
      tickers: z.array(z.string().max(12)).max(20).optional(),
    })
    .optional(),
  // Generic client context collected at submit time.
  context: z
    .object({
      referrer: z.string().max(500).optional(),
      page_path: z.string().max(300).optional(),
      utm: z.record(z.string().max(64), z.string().max(300)).optional(),
      engagement: z
        .object({
          dwell_ms: z.number().int().nonnegative().max(86_400_000).optional(),
          scroll_pct: z.number().int().min(0).max(100).optional(),
        })
        .optional(),
      session_article_views: z
        .number()
        .int()
        .nonnegative()
        .max(100_000)
        .optional(),
    })
    .optional(),
});

function deviceType(ua: string): "mobile" | "tablet" | "desktop" {
  if (/iPad|Tablet/i.test(ua)) return "tablet";
  if (/Mobi|Android|iPhone|iPod/i.test(ua)) return "mobile";
  return "desktop";
}

/** Pull device + geo from request headers (Vercel injects the geo ones). */
function serverContext(req: NextRequest) {
  const ua = req.headers.get("user-agent") ?? "";
  const decode = (v: string | null) => {
    if (!v) return undefined;
    try {
      return decodeURIComponent(v);
    } catch {
      return v;
    }
  };
  const geo = {
    country: req.headers.get("x-vercel-ip-country") ?? undefined,
    region: req.headers.get("x-vercel-ip-country-region") ?? undefined,
    city: decode(req.headers.get("x-vercel-ip-city")),
    timezone: req.headers.get("x-vercel-ip-timezone") ?? undefined,
  };
  const hasGeo = Object.values(geo).some(Boolean);
  return {
    device: { type: deviceType(ua), ua: ua.slice(0, 300) },
    geo: hasGeo ? geo : undefined,
  };
}

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
  const variant = parsed.data.variant?.trim() || null;
  const ctaText = parsed.data.ctaText ?? null;
  const article = parsed.data.article ?? null;
  const context = parsed.data.context ?? null;
  const server = serverContext(req);
  // `source` stays a clean channel label; everything else about the signup —
  // the CTA variant + exact copy, which article it came from, traffic source,
  // engagement, and device/geo — goes in the structured `metadata` column so
  // it's queryable without polluting source. PostHog gets the key dimensions
  // as discrete properties for breakdowns.
  const metadata: Record<string, unknown> = {
    ...(variant ? { cta_variant: variant } : {}),
    ...(ctaText ? { cta_text: ctaText } : {}),
    ...(article ? { article } : {}),
    ...(context?.referrer ? { referrer: context.referrer } : {}),
    ...(context?.page_path ? { page_path: context.page_path } : {}),
    ...(context?.utm && Object.keys(context.utm).length
      ? { utm: context.utm }
      : {}),
    ...(context?.engagement ? { engagement: context.engagement } : {}),
    ...(typeof context?.session_article_views === "number"
      ? { session_article_views: context.session_article_views }
      : {}),
    device: server.device,
    ...(server.geo ? { geo: server.geo } : {}),
  };

  let supabase;
  try {
    supabase = createServiceClient();
  } catch {
    return NextResponse.json({ error: "Waitlist is temporarily unavailable." }, { status: 503 });
  }

  const { error } = await supabase
    .schema("swingtrader")
    .from("early_access_signups")
    .insert({ email, source, metadata });

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

  captureServer(email, "waitlist_joined", {
    source,
    cta_variant: variant,
    article_slug: article?.slug ?? null,
    article_title: article?.title ?? null,
    referrer: context?.referrer ?? null,
    utm_source: context?.utm?.utm_source ?? null,
    utm_campaign: context?.utm?.utm_campaign ?? null,
    device_type: server.device.type,
    country: server.geo?.country ?? null,
    dwell_ms: context?.engagement?.dwell_ms ?? null,
    scroll_pct: context?.engagement?.scroll_pct ?? null,
    $set: { email, cta_variant: variant },
  });

  return NextResponse.json({ ok: true });
}
