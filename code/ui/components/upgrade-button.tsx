"use client";

import Link from "next/link";
import { useState } from "react";
import { CreditCard } from "lucide-react";
import { track } from "@/lib/analytics/events";
import { getAttribution } from "@/lib/attribution";
import { getMetaClickIds, trackInitiateCheckout } from "@/lib/pixels";
import type { PlanTier } from "@/lib/plans";

type Interval = "monthly" | "annual";

/**
 * Start Stripe Checkout for a paid plan — the same flow onboarding uses
 * (`POST /api/stripe/checkout` → `{ url }` → redirect). If the visitor isn't
 * authenticated (401), send them to sign-up first (they can't check out without
 * an account); after signup the onboarding plan step resumes the upgrade.
 */
export function useStripeCheckout(surface: string) {
  const [busy, setBusy] = useState<PlanTier | null>(null);

  async function start(plan: PlanTier, interval: Interval = "monthly") {
    if (plan === "observer") return;
    setBusy(plan);
    track("upgrade_clicked", { from_plan: "observer", to_plan: plan, surface });
    trackInitiateCheckout({ plan, interval });
    try {
      const res = await fetch("/api/stripe/checkout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        // The ad click that produced this checkout is only knowable in the
        // browser; the webhook that records the sale runs hours later with no
        // cookies. Send both along so the sale can be attributed to the ad.
        body: JSON.stringify({
          plan,
          interval,
          attribution: getAttribution(),
          ...getMetaClickIds(),
        }),
      });
      if (res.status === 401) {
        window.location.href = `/auth/sign-up?plan=${plan}`;
        return;
      }
      const data = (await res.json()) as { url?: string; error?: string };
      if (data.url) {
        window.location.href = data.url; // → Stripe Checkout
        return;
      }
      setBusy(null);
    } catch {
      setBusy(null);
    }
  }

  return { start, busy };
}

/**
 * Profile "Upgrade plan" — starts Stripe Checkout for the entry paid tier, with a
 * link to compare all plans (for Trader / annual). Replaces the old dead-end link.
 */
export function UpgradeButton({
  plan = "investor",
  interval = "monthly",
}: {
  plan?: PlanTier;
  interval?: Interval;
}) {
  const { start, busy } = useStripeCheckout("profile");
  return (
    <div className="flex flex-wrap items-center gap-4">
      <button
        onClick={() => start(plan, interval)}
        disabled={busy !== null}
        className="inline-flex items-center gap-2 rounded-lg bg-amber-500 px-3.5 py-2 text-sm font-semibold text-black transition-colors hover:bg-amber-400 disabled:opacity-60"
      >
        <CreditCard className="h-4 w-4" />
        {busy ? "Redirecting to Stripe…" : "Upgrade plan"}
      </button>
      <Link
        href="/pricing"
        className="text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
      >
        Compare plans →
      </Link>
    </div>
  );
}
