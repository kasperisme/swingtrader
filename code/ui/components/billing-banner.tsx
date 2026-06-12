"use client";

/**
 * Dashboard billing banner. Surfaces a failing-billing state (red) or an
 * imminent trial end (amber) on every protected page. Dismissible per session,
 * keyed by status so it reappears if the situation changes.
 *
 * Rendered by the protected layout, which passes the current subscription
 * status + period end read via getUserSubscription().
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import { AlertTriangle, Clock, X } from "lucide-react";

const FAILING = new Set(["past_due", "unpaid", "canceled", "incomplete_expired"]);
const TRIAL_WARN_DAYS = 3;

type Props = {
  status: string | null;
  currentPeriodEnd: string | null;
  /**
   * End of the app-managed signup trial (created_at + TRIAL_DAYS), for users
   * with no active paid subscription. Drives the free-trial countdown and the
   * "trial ended" nudge. Null for paid users or when unknown.
   */
  trialEndsAt?: string | null;
};

function daysUntil(iso: string | null): number | null {
  if (!iso) return null;
  const end = new Date(iso).getTime();
  if (Number.isNaN(end)) return null;
  return Math.ceil((end - Date.now()) / (1000 * 60 * 60 * 24));
}

export function BillingBanner({ status, currentPeriodEnd, trialEndsAt = null }: Props) {
  const [mounted, setMounted] = useState(false);
  const [dismissed, setDismissed] = useState(false);

  const failing = status != null && FAILING.has(status);

  // A paid Stripe trial drives the countdown when present; otherwise fall back
  // to the app-managed signup trial (which also has an "ended" state).
  const stripeTrialDays = status === "trialing" ? daysUntil(currentPeriodEnd) : null;
  const appTrialDays = trialEndsAt ? daysUntil(trialEndsAt) : null;

  const stripeTrialEnding =
    stripeTrialDays != null && stripeTrialDays <= TRIAL_WARN_DAYS && stripeTrialDays >= 0;
  const appTrialEnding =
    appTrialDays != null && appTrialDays <= TRIAL_WARN_DAYS && appTrialDays >= 0;
  const appTrialEnded = appTrialDays != null && appTrialDays < 0;

  const variant = failing
    ? "failing"
    : stripeTrialEnding || appTrialEnding
      ? "trial"
      : appTrialEnded
        ? "ended"
        : null;

  // Days shown in the countdown copy (whichever trial is driving it).
  const trialDays = stripeTrialEnding ? stripeTrialDays : appTrialDays;

  const dismissKey = variant ? `billing-banner-dismissed:${variant}:${status ?? "trial"}` : "";

  useEffect(() => {
    setMounted(true);
    if (dismissKey && sessionStorage.getItem(dismissKey) === "1") {
      setDismissed(true);
    }
  }, [dismissKey]);

  if (!mounted || !variant || dismissed) return null;

  function dismiss() {
    if (dismissKey) sessionStorage.setItem(dismissKey, "1");
    setDismissed(true);
  }

  const isFailing = variant === "failing";
  const isEnded = variant === "ended";
  const wrap = isFailing
    ? "border-red-500/40 bg-red-500/10"
    : "border-amber-500/40 bg-amber-500/10";
  const Icon = isFailing || isEnded ? AlertTriangle : Clock;
  const iconColor = isFailing ? "text-red-500" : "text-amber-500";

  const message = isFailing
    ? "Your billing needs attention — agents are paused and will only send a reminder until it's fixed."
    : isEnded
      ? "Your free trial has ended — add a payment method to reactivate your agents and keep full access."
      : trialDays === 0
        ? "Your free trial ends today. Add a payment method to keep your agents running."
        : `Your free trial ends in ${trialDays} ${trialDays === 1 ? "day" : "days"}. Add a payment method to keep your agents running.`;

  return (
    <div
      className={`mb-4 flex items-start gap-3 rounded-lg border px-4 py-3 text-sm ${wrap}`}
      role="status"
    >
      <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${iconColor}`} aria-hidden />
      <p className="min-w-0 flex-1 text-foreground">{message}</p>
      <Link
        href="/protected/profile"
        className="shrink-0 whitespace-nowrap rounded-md border border-border bg-background px-2.5 py-1 text-xs font-medium text-foreground transition-colors hover:bg-muted"
      >
        {isFailing ? "Set up billing" : "Add payment method"}
      </Link>
      <button
        type="button"
        onClick={dismiss}
        aria-label="Dismiss"
        className="shrink-0 rounded-md p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}
