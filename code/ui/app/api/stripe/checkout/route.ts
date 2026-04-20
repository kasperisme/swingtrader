import { NextRequest, NextResponse } from "next/server";
import { getStripe } from "@/lib/stripe/client";
import { getPriceId, type Plan, type BillingInterval } from "@/lib/stripe/prices";
import { createClient } from "@/lib/supabase/server";

const VALID_PLANS: Plan[] = ["investor", "trader"];
const VALID_INTERVALS: BillingInterval[] = ["monthly", "annual"];

export async function POST(req: NextRequest) {
  try {
    const supabase = await createClient();
    const {
      data: { user },
    } = await supabase.auth.getUser();

    if (!user) {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }

    const body = await req.json();
    const plan = (body.plan ?? "investor") as Plan;
    const interval = (body.interval ?? "monthly") as BillingInterval;

    if (!VALID_PLANS.includes(plan)) {
      return NextResponse.json({ error: "Invalid plan" }, { status: 400 });
    }
    if (!VALID_INTERVALS.includes(interval)) {
      return NextResponse.json({ error: "Invalid billing interval" }, { status: 400 });
    }

    const priceId = getPriceId(plan, interval);
    const stripe = getStripe();

    const origin = req.headers.get("origin") ?? process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000";

    const session = await stripe.checkout.sessions.create({
      mode: "subscription",
      payment_method_types: ["card"],
      allow_promotion_codes: true,
      line_items: [{ price: priceId, quantity: 1 }],
      success_url: `${origin}/protected?checkout=success`,
      cancel_url: `${origin}/pricing?checkout=cancel`,
      client_reference_id: user.id,
      customer_email: user.email,
      metadata: {
        user_id: user.id,
        email: user.email ?? "",
        plan,
        billing_interval: interval,
        phase: "phase1",
      },
      subscription_data: {
        metadata: {
          user_id: user.id,
          email: user.email ?? "",
          plan,
          billing_interval: interval,
          phase: "phase1",
        },
      },
    });

    return NextResponse.json({ url: session.url });
  } catch (err) {
    console.error("Stripe checkout error:", err);
    const message = err instanceof Error ? err.message : "Internal server error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}