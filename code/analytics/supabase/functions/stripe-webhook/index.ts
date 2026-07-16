import { serve } from "https://deno.land/std@0.168.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";
import Stripe from "https://esm.sh/stripe@17?target=deno";

const stripe = new Stripe(Deno.env.get("STRIPE_SECRET_KEY")!, {
  httpClient: Stripe.createFetchHttpClient(),
});

const webhookSecret = Deno.env.get("STRIPE_WEBHOOK_SECRET")!;

const TELEGRAM_BOT_TOKEN = Deno.env.get("TELEGRAM_BOT_TOKEN") ?? "";
const APP_BASE_URL = (
  Deno.env.get("APP_BASE_URL") ?? "https://www.newsimpactscreener.com"
).replace(/\/$/, "");

// Meta Conversions API (server-side pixel). Fires a "Subscribe" standard event
// on a real paid subscription — the value-bearing counterpart to the browser
// "Lead" pixel on the free lead-magnet forms. No-op until both secrets are set.
//   META_PIXEL_ID       — same pixel id as NEXT_PUBLIC_META_PIXEL_ID
//   META_CAPI_TOKEN     — Conversions API access token (System User, ads perms)
//   META_GRAPH_VERSION  — optional, defaults below
//   META_TEST_EVENT_CODE— optional, routes to the pixel's Test Events tab
const META_PIXEL_ID = Deno.env.get("META_PIXEL_ID") ?? "";
const META_CAPI_TOKEN = Deno.env.get("META_CAPI_TOKEN") ?? "";
const META_GRAPH_VERSION = Deno.env.get("META_GRAPH_VERSION") ?? "v21.0";
const META_TEST_EVENT_CODE = Deno.env.get("META_TEST_EVENT_CODE") ?? "";

// SHA-256 hex — Meta requires PII (email) hashed, lowercased and trimmed.
async function sha256Hex(input: string): Promise<string> {
  const data = new TextEncoder().encode(input.trim().toLowerCase());
  const digest = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

// Best-effort Meta "Subscribe" conversion. `eventId` should be stable per
// subscription so a future browser-side Subscribe pixel can be deduplicated
// against this server event.
async function sendMetaSubscribe(opts: {
  email: string;
  value: number | null;
  currency: string;
  eventId: string;
  predictedLtv?: number | null;
  sourceUrl?: string;
}): Promise<void> {
  if (!META_PIXEL_ID || !META_CAPI_TOKEN) {
    console.warn("META_PIXEL_ID/META_CAPI_TOKEN not set — skipping Meta Subscribe");
    return;
  }
  try {
    const customData: Record<string, unknown> = { currency: opts.currency };
    if (opts.value != null) customData.value = opts.value;
    if (opts.predictedLtv != null) customData.predicted_ltv = opts.predictedLtv;

    const body: Record<string, unknown> = {
      data: [
        {
          event_name: "Subscribe",
          event_time: Math.floor(Date.now() / 1000),
          action_source: "website",
          event_id: opts.eventId,
          ...(opts.sourceUrl ? { event_source_url: opts.sourceUrl } : {}),
          user_data: { em: [await sha256Hex(opts.email)] },
          custom_data: customData,
        },
      ],
    };
    if (META_TEST_EVENT_CODE) body.test_event_code = META_TEST_EVENT_CODE;

    const res = await fetch(
      `https://graph.facebook.com/${META_GRAPH_VERSION}/${META_PIXEL_ID}/events?access_token=${META_CAPI_TOKEN}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
    );
    if (!res.ok) {
      console.error("Meta CAPI Subscribe failed:", res.status, await res.text());
    }
  } catch (err) {
    console.error("Meta CAPI Subscribe error:", err);
  }
}

// Best-effort Telegram send from the webhook (e.g. the trial-ending heads-up).
async function sendTelegram(chatId: string, html: string): Promise<void> {
  if (!TELEGRAM_BOT_TOKEN) {
    console.warn("TELEGRAM_BOT_TOKEN not set — skipping Telegram send");
    return;
  }
  try {
    await fetch(
      `https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ chat_id: chatId, text: html, parse_mode: "HTML" }),
      },
    );
  } catch (err) {
    console.error("Telegram send failed:", err);
  }
}

// deno-lint-ignore no-explicit-any
async function getChatId(supabase: any, userId: string): Promise<string | null> {
  const { data } = await supabase
    .schema("swingtrader")
    .from("user_telegram_connections")
    .select("chat_id")
    .eq("user_id", userId)
    .limit(1)
    .maybeSingle();
  return data?.chat_id ?? null;
}

serve(async (req: Request) => {
  const signature = req.headers.get("stripe-signature");
  if (!signature) {
    return new Response("Missing stripe-signature header", { status: 400 });
  }

  let event: Stripe.Event;
  try {
    const rawBody = await req.text();
    event = await stripe.webhooks.constructEventAsync(
      rawBody,
      signature,
      webhookSecret,
    );
  } catch (err) {
    console.error("Webhook signature verification failed:", err);
    return new Response("Invalid signature", { status: 400 });
  }

  const supabase = createClient(
    Deno.env.get("SUPABASE_URL")!,
    Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
  );

  try {
    switch (event.type) {
      case "checkout.session.completed": {
        const session = event.data.object as Stripe.Checkout.Session;
        const userId = session.metadata?.user_id;
        const email = session.metadata?.email ?? session.customer_email;
        const plan = session.metadata?.plan;
        const billingInterval = session.metadata?.billing_interval;
        const phase = session.metadata?.phase ?? "phase1";

        if (!email || !plan || !billingInterval) {
          console.error("Missing metadata in checkout session:", session.id);
          break;
        }

        const subscriptionId =
          typeof session.subscription === "string"
            ? session.subscription
            : (session.subscription as Stripe.Subscription)?.id;

        const customerId =
          typeof session.customer === "string"
            ? session.customer
            : (session.customer as Stripe.Customer)?.id;

        if (!subscriptionId || !customerId) break;

        const sub = await stripe.subscriptions.retrieve(subscriptionId);
        const periodEnd = sub.items.data[0]
          ? ((sub.items.data[0] as unknown as Record<string, number>)
              .current_period_end ?? (sub as unknown as Record<string, number>).current_period_end)
          : (sub as unknown as Record<string, number>).current_period_end;

        const existing = userId
          ? await supabase
              .schema("swingtrader")
              .from("user_subscriptions")
              .select("id")
              .eq("user_id", userId)
              .maybeSingle()
          : null;

        const row: Record<string, unknown> = {
          email,
          stripe_customer_id: customerId,
          stripe_subscription_id: subscriptionId,
          status: sub.status,
          plan,
          billing_interval: billingInterval,
          phase,
          grandfathered: true,
          current_period_end: periodEnd
            ? new Date(periodEnd * 1000).toISOString()
            : null,
        };

        if (userId) row.user_id = userId;

        if (existing?.data?.id) {
          await supabase
            .schema("swingtrader")
            .from("user_subscriptions")
            .update(row)
            .eq("id", existing.data.id);
        } else {
          await supabase
            .schema("swingtrader")
            .from("user_subscriptions")
            .insert(row);
        }

        // Meta "Subscribe" conversion. Value is the recurring plan price from
        // the subscription item — NOT session.amount_total, which is $0 on a
        // trial checkout. This fires once per subscription (checkout completes
        // once), even when the subscription starts in a trial.
        const price = sub.items.data[0]?.price as Stripe.Price | undefined;
        const value = price?.unit_amount != null ? price.unit_amount / 100 : null;
        const currency = (price?.currency ?? "usd").toUpperCase();
        // Rough 1-year LTV floor: annualize monthly plans; annual is already a year.
        const predictedLtv =
          value == null ? null : billingInterval === "annual" ? value : value * 12;
        await sendMetaSubscribe({
          email,
          value,
          currency,
          predictedLtv,
          eventId: subscriptionId,
          sourceUrl: `${APP_BASE_URL}/pricing`,
        });

        break;
      }

      case "customer.subscription.updated": {
        const sub = event.data.object as Stripe.Subscription;
        const userId = sub.metadata?.user_id;
        const plan = sub.metadata?.plan;
        const billingInterval = sub.metadata?.billing_interval;

        const periodEnd = sub.items.data[0]
          ? ((sub.items.data[0] as unknown as Record<string, number>)
              .current_period_end ?? (sub as unknown as Record<string, number>).current_period_end)
          : (sub as unknown as Record<string, number>).current_period_end;

        const row: Record<string, unknown> = {
          status: sub.status,
          stripe_subscription_id: sub.id,
          current_period_end: periodEnd
            ? new Date(periodEnd * 1000).toISOString()
            : null,
        };

        if (plan) row.plan = plan;
        if (billingInterval) row.billing_interval = billingInterval;

        const query = supabase
          .schema("swingtrader")
          .from("user_subscriptions");

        if (userId) {
          await query.update(row).eq("user_id", userId);
        } else {
          await query.update(row).eq("stripe_subscription_id", sub.id);
        }

        break;
      }

      case "customer.subscription.deleted": {
        const sub = event.data.object as Stripe.Subscription;
        const userId = sub.metadata?.user_id;

        const row = {
          status: "canceled" as const,
          current_period_end: null,
        };

        const query = supabase
          .schema("swingtrader")
          .from("user_subscriptions");

        if (userId) {
          await query.update(row).eq("user_id", userId);
        } else {
          await query.update(row).eq("stripe_subscription_id", sub.id);
        }

        break;
      }

      case "customer.subscription.trial_will_end": {
        // Fires ~3 days before the trial converts to a paid charge. Send a
        // proactive heads-up so a missing/failing card doesn't silently lapse.
        const sub = event.data.object as Stripe.Subscription;
        const userId = sub.metadata?.user_id;
        if (!userId) break;

        const chatId = await getChatId(supabase, userId);
        if (chatId) {
          await sendTelegram(
            chatId,
            "<b>⏳ Your trial is ending soon</b>\n\n" +
              "Add a payment method to keep your News Impact Screener agents " +
              "running without interruption:\n" +
              `<a href="${APP_BASE_URL}/protected/profile">Set up billing</a>`,
          );
        }
        break;
      }

      case "invoice.payment_failed": {
        // Defensive: ensure the subscription is flagged past_due promptly even
        // if customer.subscription.updated is delayed. Enforcement (reminder-
        // only agent runs + dashboard banner) keys off this status.
        const invoice = event.data.object as Stripe.Invoice;
        const customerId =
          typeof invoice.customer === "string"
            ? invoice.customer
            : (invoice.customer as Stripe.Customer)?.id;
        if (!customerId) break;

        await supabase
          .schema("swingtrader")
          .from("user_subscriptions")
          .update({ status: "past_due" })
          .eq("stripe_customer_id", customerId);

        break;
      }

      default:
        break;
    }
  } catch (err) {
    console.error(`Error processing ${event.type}:`, err);
    return new Response("Webhook handler failed", { status: 500 });
  }

  return new Response(JSON.stringify({ received: true }), {
    headers: { "Content-Type": "application/json" },
  });
});