"use client";

import Link from "next/link";
import { Lock, ArrowRight } from "lucide-react";
import type { PlanTier } from "@/lib/plans";
import { PLAN_GATE } from "@/lib/plans";

interface UpgradePromptProps {
  requiredPlan: PlanTier;
  userPlan: PlanTier;
  /** Explicit message to show. If omitted, a default is generated from the gate settings. */
  message?: string;
}

export function UpgradePrompt({ requiredPlan, userPlan, message }: UpgradePromptProps) {
  const requiredLabel = PLAN_GATE[requiredPlan].label;
  const userLabel = PLAN_GATE[userPlan].label;

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
        className="inline-flex items-center gap-1 rounded-lg bg-amber-500/20 px-3 py-1.5 text-xs font-semibold text-amber-300 transition-colors hover:bg-amber-500/30"
      >
        Upgrade
        <ArrowRight className="h-3 w-3" />
      </Link>
    </div>
  );
}
