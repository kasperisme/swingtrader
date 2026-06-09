import { NextResponse, type NextRequest } from "next/server";
import { z } from "zod";
import { createClient } from "@/lib/supabase/server";
import { sendEmail, type SendEmailAttachment } from "@/lib/email/send";
import {
  buildUnsubscribeUrl,
  isValidEmail,
  markConfirmationSent,
  resolveScreeningsBySlugs,
  subscribeEmailToScreenings,
  type ScreeningRef,
} from "@/lib/email/screening-subscriptions";
import { buildLatestResultsCsv } from "@/lib/market-screenings/results-csv";
import {
  renderSubscriptionConfirmationEmail,
  type ConfirmationScreening,
} from "@/emails/SubscriptionConfirmationEmail";
import { humanizeCron } from "@/lib/cron-format";
import {
  getLatestMarketScreeningResultRows,
  getMarketScreeningBySlug,
  submitEarlyAccessSignup,
} from "@/app/actions/market-screenings";
import { captureServer } from "@/lib/analytics/server";

const bodySchema = z.object({
  email: z.string().trim().max(320),
  screeningSlugs: z.array(z.string().trim().max(200)).min(1).max(50),
  source: z.string().trim().max(64).optional(),
});

const APP_URL =
  process.env.NEXT_PUBLIC_APP_URL ?? "https://newsimpactscreener.com";

/** Human-readable cadence for a screening, for the email body. */
async function scheduleLabel(slug: string): Promise<string> {
  try {
    const s = await getMarketScreeningBySlug(slug);
    if (s) return humanizeCron(s.schedule, s.timezone);
  } catch {
    /* ignore */
  }
  return "On schedule";
}

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

  const screenings = await resolveScreeningsBySlugs(parsed.data.screeningSlugs);
  if (screenings.length === 0) {
    return NextResponse.json({ error: "invalid_request" }, { status: 400 });
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
  const referrer = req.headers.get("referer");
  const userAgent = req.headers.get("user-agent");

  const outcome = await subscribeEmailToScreenings({
    email,
    screenings,
    source: parsed.data.source || "email_subscribe",
    userId,
    referrer,
    userAgent,
  });

  // Also capture the lead in early_access_signups for continuity with the
  // existing waitlist analytics. Best-effort — never blocks the real
  // email-delivery subscription above.
  void Promise.allSettled(
    screenings.map((s) =>
      submitEarlyAccessSignup({
        email,
        screeningSlug: s.slug,
        source: parsed.data.source || "email_subscribe",
      }),
    ),
  );

  // Everything requested was already an active subscription → idempotent signal.
  if (outcome.subscribed.length === 0 && outcome.alreadySubscribed.length > 0) {
    return NextResponse.json({ error: "already_subscribed" }, { status: 200 });
  }

  // Confirmation email covers the full requested set (fresh + already-on).
  const confirmFor: ScreeningRef[] = [
    ...outcome.subscribed,
    ...outcome.alreadySubscribed,
  ];

  // Build CSV attachments (5d) — best-effort, never blocks the subscription.
  const attachments: SendEmailAttachment[] = [];
  for (const s of confirmFor) {
    try {
      const csv = await buildLatestResultsCsv(s.id);
      if (csv) {
        attachments.push({
          filename: `${s.slug}-latest.csv`,
          // Resend's API expects attachment `content` to be base64 (the SDK
          // JSON-serializes whatever we pass, then the server base64-decodes
          // it). Sending raw CSV text gets decoded as if it were base64 and
          // arrives corrupted, so encode it ourselves — same contract the
          // Python sender uses (shared/email.py base64-encodes too).
          content: Buffer.from(csv.content, "utf8").toString("base64"),
          contentType: "text/csv",
        });
      } else {
        console.warn(`[subscribe] no results to attach for ${s.slug}`);
      }
    } catch (e) {
      console.warn(`[subscribe] CSV build failed for ${s.slug}`, e);
    }
  }

  // Max tickers shown inline in the email body; the rest live in the CSV.
  const MAX_INLINE_PICKS = 8;

  const confirmationScreenings: ConfirmationScreening[] = await Promise.all(
    confirmFor.map(async (s) => {
      const [schedule, latest] = await Promise.all([
        scheduleLabel(s.slug),
        getLatestMarketScreeningResultRows(s.id).catch(() => ({
          runAt: null,
          rows: [],
        })),
      ]);
      const symbols = latest.rows
        .map((r) => r.symbol)
        .filter((sym): sym is string => Boolean(sym));
      return {
        name: s.name,
        slug: s.slug,
        schedule,
        latest: {
          runAt: latest.runAt,
          rowCount: symbols.length,
          symbols: symbols.slice(0, MAX_INLINE_PICKS),
        },
      };
    }),
  );

  const unsubscribeUrl = buildUnsubscribeUrl(APP_URL, {
    email,
    slugs: confirmFor.map((s) => s.slug),
  });

  const { subject, html, text } = renderSubscriptionConfirmationEmail({
    screenings: confirmationScreenings,
    appUrl: APP_URL,
    unsubscribeUrl,
  });

  // Persisted already — the email is best-effort (mirrors the early-access
  // route). A send failure is logged but the user is still subscribed, so we
  // report success rather than scaring them into resubmitting.
  const sendResult = await sendEmail({
    to: email,
    subject,
    html,
    text,
    attachments,
    tags: [{ name: "type", value: "screening_subscription_confirmation" }],
  });

  if (sendResult.ok) {
    void markConfirmationSent(
      email,
      confirmFor.map((s) => s.id),
    );
  } else {
    console.error("[subscribe] confirmation email failed", sendResult.error);
  }

  captureServer(userId ?? email, "screening_email_subscribed", {
    slugs: confirmFor.map((s) => s.slug),
    fresh: outcome.subscribed.map((s) => s.slug),
    source: parsed.data.source || "email_subscribe",
    authenticated: Boolean(userId),
    email_sent: sendResult.ok,
    $set: { email },
  });

  return NextResponse.json({ success: true });
}
