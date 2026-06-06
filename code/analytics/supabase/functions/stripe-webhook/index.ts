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