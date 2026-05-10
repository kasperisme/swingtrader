"use client";

import { useEffect } from "react";
import Link from "next/link";
import { Lock, ArrowRight } from "lucide-react";
import type { PlanTier } from "@/lib/plans";
import { PLAN_GATE } from "@/lib/plans";
import { track } from "@/lib/analytics/events";

interface UpgradePromptProps {
  requiredPlan: PlanTier;
  userPlan: PlanTier;
  /** Explicit message to show. If omitted, a default is generated from the gate settings. */
  message?: string;
  /** Surface identifier for analytics, e.g. "news_trends", "screenings_create". */
  surface?: string;
}

export function UpgradePrompt({ requiredPlan, userPlan, message, surface }: UpgradePromptProps) {
  const requiredLabel = PLAN_GATE[requiredPlan].label;
  const userLabel = PLAN_GATE[userPlan].label;
  const trackSurface = surface ?? "unknown";

  useEffect(() => {
    track("paywall_viewed", {
      surface: trackSurface,
      user_plan: userPlan,
      required_plan: requiredPlan,
    });
  }, [trackSurface, userPlan, requiredPlan]);

  const defaultMessage =
    userPlan === "observer"
      ? `Unlock up to ${PLAN_GATE[requiredPlan].newsTrendsLookbackDays} days of history with the ${requiredLabel} plan.`
      : `Your ${userLabel} plan is limited. Upgrade to ${requiredLabel} for full access.`;

  return (
    <div className="flex items-center gap-3 rounded-xl border border-amber-500/20 bg-amber-500/5 px-4 py-3 text-sm">
      <Lock className="h-4 w-4 shrink-0 text-amber-400" />
      <p className="flex-1 text-amber-100/90">
        {message ?? defaultMessage}
      </p>
      <Link
        href="/pricing"
        onClick={() =>
          track("upgrade_clicked", {
            from_plan: userPlan,
            to_plan: requiredPlan,
            surface: trackSurface,
          })
        }
        className="inline-flex items-center gap-1 rounded-lg bg-amber-500/20 px-3 py-1.5 text-xs font-semibold text-amber-300 transition-colors hover:bg-amber-500/30"
      >
        Upgrade
        <ArrowRight className="h-3 w-3" />
      </Link>
    </div>
  );
}
