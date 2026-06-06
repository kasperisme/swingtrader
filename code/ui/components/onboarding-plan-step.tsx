"use client";

/**
 * Onboarding plan step. Shown after the AI setup chat (via the welcome dialog's
 * "Next" button). Recommends the plan that best supports what the user just set
 * up, then starts Stripe checkout for the chosen paid plan.
 */

import { useEffect, useState } from "react";
import { ArrowLeft, Check, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { getScreeningLimits } from "@/app/actions/screenings-agent";
import { track } from "@/lib/analytics/events";
import type { PlanTier } from "@/lib/plans";

type Interval = "monthly" | "annual";

type PlanInfo = {
  id: PlanTier;
  name: string;
  tagline: string;
  priceMonthly: number;
  priceAnnual: number;
  paid: boolean;
  features: string[];
};

// Phase-1 (early-access) pricing, mirroring /pricing.
const PLANS: PlanInfo[] = [
  {
    id: "observer",
    name: "Observer",
    tagline: "Free forever",
    priceMonthly: 0,
    priceAnnual: 0,
    paid: false,
    features: [
      "Daily top-5 impacted stocks",
      "Manual screening & research",
      "Results delayed 1 day",
    ],
  },
  {
    id: "investor",
    name: "Investor",
    tagline: "Best for your setup",
    priceMonthly: 9,
    priceAnnual: 99,
    paid: true,
    features: [
      "Real-time news impact on your holdings",
      "Up to 5 agents, as often as every 4h",
      "Watchlist & portfolio alerts",
      "30-day history",
    ],
  },
  {
    id: "trader",
    name: "Trader",
    tagline: "For active traders",
    priceMonthly: 19,
    priceAnnual: 199,
    paid: true,
    features: [
      "Everything in Investor",
      "Up to 25 agents, as often as every 15 min",
      "AI stock summaries & portfolio impact view",
      "400-day history",
    ],
  },
];

const REASON: Record<PlanTier, string> = {
  observer: "It covers the basics — you can always upgrade later.",
  investor:
    "Your portfolio-news agent works best with real-time data and alerts — Investor unlocks both, plus room for more agents.",
  trader:
    "You set up enough automation that you'll want frequent runs and more agents — Trader gives you the most headroom.",
};

export function OnboardingPlanStep({
  onBack,
  onClose,
}: {
  onBack: () => void;
  onClose: () => void;
}) {
  const [interval, setIntervalState] = useState<Interval>("annual");
  const [recommended, setRecommended] = useState<PlanTier>("investor");
  const [currentPlan, setCurrentPlan] = useState<PlanTier | null>(null);
  const [busy, setBusy] = useState<PlanTier | null>(null);
  const [busyTrial, setBusyTrial] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    void (async () => {
      const res = await getScreeningLimits();
      if (!active || !res.ok) return;
      setCurrentPlan(res.data.plan);
      // More than the Investor agent allowance → recommend Trader.
      setRecommended(res.data.used > 5 ? "trader" : "investor");
    })();
    return () => {
      active = false;
    };
  }, []);

  const alreadyPaid = currentPlan === "investor" || currentPlan === "trader";

  async function choose(plan: PlanTier, trial = false) {
    if (!plan || plan === "observer") {
      onClose();
      return;
    }
    setBusy(plan);
    setBusyTrial(trial);
    setError(null);
    track("upgrade_clicked", {
      from_plan: currentPlan ?? "observer",
      to_plan: plan,
      surface: trial ? "onboarding_trial" : "onboarding",
    });
    try {
      const res = await fetch("/api/stripe/checkout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ plan, interval, trial }),
      });
      const data = (await res.json()) as { url?: string; error?: string };
      if (data.url) {
        window.location.href = data.url;
        return;
      }
      setError(data.error ?? "Could not start checkout. Please try again.");
      setBusy(null);
      setBusyTrial(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not start checkout.");
      setBusy(null);
      setBusyTrial(false);
    }
  }

  const rec = PLANS.find((p) => p.id === recommended) ?? PLANS[1];

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4">
      <div className="min-h-0 flex-1 overflow-y-auto pr-1">
        {/* Recommendation banner */}
        <div className="rounded-lg border border-amber-500/40 bg-amber-500/5 px-4 py-3">
          <p className="text-sm">
            Based on your setup, we recommend the{" "}
            <span className="font-semibold text-foreground">{rec.name}</span> plan.
          </p>
          <p className="mt-1 text-xs text-muted-foreground">{REASON[recommended]}</p>
        </div>

        {/* Billing interval toggle */}
        <div className="mt-4 flex items-center justify-center gap-1 rounded-lg border border-border bg-muted/30 p-1 text-xs">
          {(["monthly", "annual"] as Interval[]).map((opt) => (
            <button
              key={opt}
              type="button"
              onClick={() => setIntervalState(opt)}
              className={`flex-1 rounded-md px-3 py-1.5 font-medium capitalize transition-colors ${
                interval === opt
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {opt}
              {opt === "annual" && (
                <span className="ml-1 text-emerald-600 dark:text-emerald-400">
                  save ~10%
                </span>
              )}
            </button>
          ))}
        </div>

        {/* Plan cards */}
        <div className="mt-4 grid gap-3 sm:grid-cols-3">
          {PLANS.map((plan) => {
            const isRec = plan.id === recommended;
            const isCurrent = plan.id === currentPlan;
            const price = interval === "annual" ? plan.priceAnnual : plan.priceMonthly;
            const unit = interval === "annual" ? "/yr" : "/mo";
            return (
              <div
                key={plan.id}
                className={`flex flex-col rounded-xl border bg-card/60 p-4 ${
                  isRec
                    ? "border-amber-500/60 ring-1 ring-amber-500/40"
                    : "border-border"
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <p className="text-sm font-bold">{plan.name}</p>
                  {isRec && (
                    <span className="rounded-full bg-amber-500/20 px-2 py-0.5 text-[10px] font-semibold text-amber-600 dark:text-amber-300">
                      Recommended
                    </span>
                  )}
                </div>
                <p className="mt-0.5 text-[11px] text-muted-foreground">{plan.tagline}</p>

                <div className="mt-2 flex items-baseline gap-1">
                  <span className="text-2xl font-bold">${price}</span>
                  <span className="text-xs text-muted-foreground">
                    {plan.paid ? unit : ""}
                  </span>
                </div>

                <ul className="mt-3 flex flex-1 flex-col gap-1.5">
                  {plan.features.map((f) => (
                    <li key={f} className="flex items-start gap-1.5 text-xs text-muted-foreground">
                      <Check className="mt-0.5 h-3 w-3 shrink-0 text-emerald-500" />
                      <span>{f}</span>
                    </li>
                  ))}
                </ul>

                <Button
                  type="button"
                  size="sm"
                  variant={isRec ? "default" : "outline"}
                  className="mt-4"
                  disabled={busy !== null || isCurrent}
                  onClick={() => void choose(plan.id)}
                >
                  {busy === plan.id && !busyTrial ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : isCurrent ? (
                    "Current plan"
                  ) : plan.paid ? (
                    "Set up billing"
                  ) : (
                    "Continue free"
                  )}
                </Button>
              </div>
            );
          })}
        </div>

        {alreadyPaid ? (
          <p className="mt-3 text-center text-xs text-muted-foreground">
            You&apos;re already on a paid plan — you&apos;re all set.
          </p>
        ) : (
          <p className="mt-3 text-center text-[11px] text-muted-foreground">
            Your 14-day trial starts on {rec.name} — no charge until it ends,
            cancel anytime.
          </p>
        )}
        {error && (
          <p className="mt-3 text-center text-xs text-red-500">{error}</p>
        )}
      </div>

      <div className="flex shrink-0 items-center justify-between">
        <Button type="button" variant="ghost" size="sm" onClick={onBack}>
          <ArrowLeft className="mr-1 h-3.5 w-3.5" />
          Back
        </Button>
        <Button
          type="button"
          size="sm"
          disabled={busy !== null || alreadyPaid}
          onClick={() => void choose(recommended, true)}
        >
          {busyTrial ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            "Start 14-day trial"
          )}
        </Button>
      </div>
    </div>
  );
}
