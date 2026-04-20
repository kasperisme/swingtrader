import { serve } from "https://deno.land/std@0.168.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";
import Stripe from "https://esm.sh/stripe@17?target=deno";

const stripe = new Stripe(Deno.env.get("STRIPE_SECRET_KEY")!, {
  httpClient: Stripe.createFetchHttpClient(),
});

const webhookSecret = Deno.env.get("STRIPE_WEBHOOK_SECRET")!;

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