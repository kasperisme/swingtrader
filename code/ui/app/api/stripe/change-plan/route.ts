import { NextRequest, NextResponse } from "next/server";
import type Stripe from "stripe";
import { getStripe } from "@/lib/stripe/client";
import {
  changeTiming,
  getPlanOptions,
  getPriceId,
  isSameSelection,
  selectionForPriceId,
  INTERVALS,
  PLANS,
  type BillingInterval,
  type ChangeTiming,
  type Plan,
  type PlanOption,
  type PlanSelection,
} from "@/lib/stripe/prices";
import { createClient } from "@/lib/supabase/server";
import { createServiceClient } from "@/lib/supabase/service";
import { revalidateSubscriptionTier } from "@/lib/subscription";
import { captureServer } from "@/lib/analytics/server";

/**
 * In-app plan changes — switch an existing subscription between Investor/Trader
 * and monthly/annual without sending the customer to the Stripe Billing Portal.
 *
 * Upgrades apply immediately with proration; downgrades (lower tier, or annual →
 * monthly) are scheduled for the next renewal via a Stripe subscription schedule
 * so the customer keeps the period they already paid for. `GET` returns the
 * catalogue plus any pending scheduled change; `POST` applies or cancels one.
 */

interface SubscriptionRow {
  id: string;
  plan: string;
  billing_interval: string;
  status: string;
  stripe_subscription_id: string | null;
  email: string;
  phase: string | null;
}

/** Statuses where a self-service plan change is safe to attempt. */
const CHANGEABLE_STATUSES = ["active", "trialing"];

/**
 * Statuses with nothing left to modify — the customer needs a fresh Checkout
 * session, not a subscription update.
 */
const DEAD_STATUSES = ["canceled", "incomplete_expired"];

/**
 * `checkout` — no live subscription: the same four prices, bought via Checkout.
 * `change`   — a live subscription to switch in place.
 */
type Mode = "checkout" | "change";

function isPlan(value: unknown): value is Plan {
  return typeof value === "string" && PLANS.includes(value as Plan);
}

function isInterval(value: unknown): value is BillingInterval {
  return typeof value === "string" && INTERVALS.includes(value as BillingInterval);
}

/**
 * Period end in epoch seconds. Recent Stripe API versions moved
 * `current_period_end` onto the subscription item; older ones keep it on the
 * subscription. Read both, same as the webhook does.
 */
function periodEndSeconds(sub: Stripe.Subscription): number | null {
  const item = sub.items.data[0] as unknown as Record<string, number> | undefined;
  const fromItem = item?.current_period_end;
  const fromSub = (sub as unknown as Record<string, number>).current_period_end;
  return fromItem ?? fromSub ?? null;
}

function toIso(seconds: number | null | undefined): string | null {
  return seconds ? new Date(seconds * 1000).toISOString() : null;
}

function priceIdOf(
  price: string | Stripe.Price | Stripe.DeletedPrice | null | undefined,
): string | null {
  if (!price) return null;
  return typeof price === "string" ? price : price.id;
}

function scheduleIdOf(sub: Stripe.Subscription): string | null {
  if (!sub.schedule) return null;
  return typeof sub.schedule === "string" ? sub.schedule : sub.schedule.id;
}

/** The schedule phase covering `now` — the one the customer is paying for today. */
function currentPhase(schedule: Stripe.SubscriptionSchedule): Stripe.SubscriptionSchedule.Phase | null {
  const now = Math.floor(Date.now() / 1000);
  return (
    schedule.phases.find(
      (p) => p.start_date <= now && (p.end_date == null || p.end_date > now),
    ) ??
    schedule.phases[0] ??
    null
  );
}

interface PendingChange {
  plan: Plan;
  interval: BillingInterval;
  effectiveAt: string | null;
}

/** A future schedule phase, resolved back to one of our plans. */
async function readPendingChange(
  stripe: Stripe,
  sub: Stripe.Subscription,
  options: PlanOption[],
): Promise<PendingChange | null> {
  const scheduleId = scheduleIdOf(sub);
  if (!scheduleId) return null;

  const schedule = await stripe.subscriptionSchedules.retrieve(scheduleId);
  if (schedule.status === "canceled" || schedule.status === "released") return null;

  const now = Math.floor(Date.now() / 1000);
  const future = schedule.phases.find((p) => p.start_date > now);
  if (!future) return null;

  const selection = selectionForPriceId(options, priceIdOf(future.items[0]?.price));
  if (!selection) return null;

  return { ...selection, effectiveAt: toIso(future.start_date) };
}

async function loadContext(): Promise<
  | { error: NextResponse }
  | { userId: string; row: SubscriptionRow | null }
> {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    return { error: NextResponse.json({ error: "Unauthorized" }, { status: 401 }) };
  }

  const { data } = await supabase
    .schema("swingtrader")
    .from("user_subscriptions")
    .select("id, plan, billing_interval, status, stripe_subscription_id, email, phase")
    .eq("user_id", user.id)
    .maybeSingle();

  return { userId: user.id, row: (data as SubscriptionRow | null) ?? null };
}

export async function GET() {
  try {
    const ctx = await loadContext();
    if ("error" in ctx) return ctx.error;

    const options = await getPlanOptions();
    const { row } = ctx;

    // Free / never-subscribed: no Stripe subscription exists, so the same four
    // prices are offered through Checkout instead of an in-place switch.
    if (!row?.stripe_subscription_id) {
      return NextResponse.json({
        mode: "checkout" satisfies Mode,
        options: options.map((o) => ({ ...o, current: false, timing: null })),
        current: null,
        pending: null,
        changeable: false,
        reason: "no_subscription",
      });
    }

    const stripe = getStripe();
    const sub = await stripe.subscriptions.retrieve(row.stripe_subscription_id);

    // A dead subscription can't be updated either — same Checkout path, so a
    // lapsed customer can resubscribe on any plan without leaving the page.
    if (DEAD_STATUSES.includes(sub.status)) {
      return NextResponse.json({
        mode: "checkout" satisfies Mode,
        options: options.map((o) => ({ ...o, current: false, timing: null })),
        current: null,
        pending: null,
        changeable: false,
        reason: `status_${sub.status}`,
      });
    }

    const current: PlanSelection = {
      plan: isPlan(row.plan) ? row.plan : "investor",
      interval: isInterval(row.billing_interval) ? row.billing_interval : "monthly",
    };

    const pending = await readPendingChange(stripe, sub, options);

    const changeable = CHANGEABLE_STATUSES.includes(sub.status) && !sub.cancel_at_period_end;
    const reason = !CHANGEABLE_STATUSES.includes(sub.status)
      ? `status_${sub.status}`
      : sub.cancel_at_period_end
        ? "canceling"
        : null;

    return NextResponse.json({
      mode: "change" satisfies Mode,
      options: options.map((o) => ({
        ...o,
        current: isSameSelection(current, o),
        timing: isSameSelection(current, o) ? null : changeTiming(current, o),
      })),
      current: {
        ...current,
        status: sub.status,
        cancelAtPeriodEnd: sub.cancel_at_period_end,
        currentPeriodEnd: toIso(periodEndSeconds(sub)),
      },
      pending,
      changeable,
      reason,
    });
  } catch (err) {
    console.error("Stripe change-plan GET error:", err);
    const message = err instanceof Error ? err.message : "Internal server error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

export async function POST(req: NextRequest) {
  try {
    const ctx = await loadContext();
    if ("error" in ctx) return ctx.error;
    const { userId, row } = ctx;

    if (!row?.stripe_subscription_id) {
      return NextResponse.json(
        { error: "No active subscription to change." },
        { status: 404 },
      );
    }

    const body = await req.json().catch(() => ({}));
    const stripe = getStripe();
    const sub = await stripe.subscriptions.retrieve(row.stripe_subscription_id);

    if (body.action === "cancel_scheduled") {
      const scheduleId = scheduleIdOf(sub);
      if (!scheduleId) {
        return NextResponse.json({ error: "No scheduled change to cancel." }, { status: 400 });
      }
      // Release (not cancel) — cancelling a schedule can end the subscription;
      // releasing detaches it and leaves the subscription running as-is.
      await stripe.subscriptionSchedules.release(scheduleId);
      captureServer(userId, "plan_change_canceled", { plan: row.plan });
      return NextResponse.json({ ok: true, pending: null });
    }

    if (!isPlan(body.plan)) {
      return NextResponse.json({ error: "Invalid plan" }, { status: 400 });
    }
    if (!isInterval(body.interval)) {
      return NextResponse.json({ error: "Invalid billing interval" }, { status: 400 });
    }

    const current: PlanSelection = {
      plan: isPlan(row.plan) ? row.plan : "investor",
      interval: isInterval(row.billing_interval) ? row.billing_interval : "monthly",
    };
    const target: PlanSelection = { plan: body.plan, interval: body.interval };

    if (isSameSelection(current, target)) {
      return NextResponse.json({ error: "Already on this plan." }, { status: 400 });
    }
    if (!CHANGEABLE_STATUSES.includes(sub.status)) {
      return NextResponse.json(
        {
          error:
            "This subscription can't be changed right now — open Manage billing to sort out payment first.",
        },
        { status: 409 },
      );
    }
    if (sub.cancel_at_period_end) {
      return NextResponse.json(
        {
          error:
            "Your subscription is set to cancel at the end of the period. Resume it in Manage billing before changing plan.",
        },
        { status: 409 },
      );
    }

    const priceId = getPriceId(target.plan, target.interval);
    const metadata = {
      user_id: userId,
      email: row.email ?? "",
      plan: target.plan,
      billing_interval: target.interval,
      phase: row.phase ?? "phase1",
    };

    // A trial has no money at stake and no period worth preserving, so every
    // change applies immediately (and keeps the trial end untouched).
    const timing: ChangeTiming =
      sub.status === "trialing" ? "immediate" : changeTiming(current, target);

    let effectiveAt: string | null = null;

    if (timing === "immediate") {
      // Item swaps are rejected while a schedule owns the subscription — drop
      // any previously scheduled change first.
      const scheduleId = scheduleIdOf(sub);
      if (scheduleId) await stripe.subscriptionSchedules.release(scheduleId);

      const itemId = sub.items.data[0]?.id;
      if (!itemId) {
        return NextResponse.json(
          { error: "Subscription has no billable item." },
          { status: 409 },
        );
      }

      const updated = await stripe.subscriptions.update(sub.id, {
        items: [{ id: itemId, price: priceId }],
        // Trials aren't invoiced; otherwise bill the difference now so access and
        // payment stay in step.
        proration_behavior: sub.status === "trialing" ? "none" : "always_invoice",
        // Fail loudly instead of leaving a half-applied, unpaid change behind.
        payment_behavior: "error_if_incomplete",
        metadata,
      });

      const periodEnd = toIso(periodEndSeconds(updated));

      // Write through so the profile reflects the change immediately; the
      // customer.subscription.updated webhook converges on the same values.
      await createServiceClient()
        .schema("swingtrader")
        .from("user_subscriptions")
        .update({
          plan: target.plan,
          billing_interval: target.interval,
          status: updated.status,
          current_period_end: periodEnd,
        })
        .eq("id", row.id);

      revalidateSubscriptionTier(userId);
      effectiveAt = new Date().toISOString();
    } else {
      // Keep the paid-for period, then switch at renewal.
      let scheduleId = scheduleIdOf(sub);
      if (!scheduleId) {
        const created = await stripe.subscriptionSchedules.create({
          from_subscription: sub.id,
        });
        scheduleId = created.id;
      }

      const schedule = await stripe.subscriptionSchedules.retrieve(scheduleId);
      const phase = currentPhase(schedule);
      const keepPriceId = priceIdOf(phase?.items[0]?.price);
      if (!phase || !keepPriceId) {
        return NextResponse.json(
          { error: "Could not read the current billing period." },
          { status: 409 },
        );
      }

      await stripe.subscriptionSchedules.update(scheduleId, {
        // When the new phase completes, hand the subscription back to normal
        // billing at the new price rather than cancelling it.
        end_behavior: "release",
        phases: [
          {
            items: phase.items.map((item) => ({
              price: priceIdOf(item.price) as string,
              quantity: item.quantity ?? 1,
            })),
            start_date: phase.start_date,
            end_date: phase.end_date ?? undefined,
            proration_behavior: "none",
          },
          {
            items: [{ price: priceId, quantity: 1 }],
            // Phase metadata lands on the subscription when the phase starts —
            // that's what the webhook reads to move the row to the new plan.
            metadata,
            proration_behavior: "none",
          },
        ],
      });

      effectiveAt = toIso(phase.end_date);
    }

    captureServer(userId, "plan_changed", {
      from_plan: current.plan,
      from_interval: current.interval,
      to_plan: target.plan,
      to_interval: target.interval,
      timing,
    });

    return NextResponse.json({
      ok: true,
      timing,
      effectiveAt,
      pending:
        timing === "period_end"
          ? { plan: target.plan, interval: target.interval, effectiveAt }
          : null,
    });
  } catch (err) {
    console.error("Stripe change-plan POST error:", err);
    // Surface card failures (declines, 3-D Secure) as something actionable.
    const stripeErr = err as { type?: string; message?: string };
    if (stripeErr?.type === "StripeCardError" || stripeErr?.type === "StripeInvalidRequestError") {
      return NextResponse.json(
        {
          error:
            stripeErr.message ??
            "Stripe rejected the change. Try updating your card in Manage billing.",
        },
        { status: 402 },
      );
    }
    const message = err instanceof Error ? err.message : "Internal server error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
