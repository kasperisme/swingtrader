"use client";

import { useState } from "react";
import Link from "next/link";
import { Check, ArrowRight } from "lucide-react";
import type { LandingPricingPlan } from "@/lib/sanity/types";

type Props = {
  freePlan: LandingPricingPlan | undefined;
  currentPlans: LandingPricingPlan[];
  finalPhasePlan: LandingPricingPlan | undefined;
  spotsLeft: number | null;
  spotLimit: number | null;
  signupCount: number;
  fillPct: number;
  founderNote: string | null;
};

export function PricingTierSwitcher({
  freePlan,
  currentPlans,
  finalPhasePlan: _finalPhasePlan,
  spotsLeft,
  spotLimit,
  signupCount,
  fillPct,
  founderNote,
}: Props) {
  const allTiers = [
    ...(freePlan ? [freePlan] : []),
    ...currentPlans,
  ];

  const [selected, setSelected] = useState(
    allTiers.find((p) => p.name === "Investor")?.name ??
    currentPlans.find((p) => p.isHighlighted)?.name ??
    allTiers[0]?.name ?? "",
  );

  const plan = allTiers.find((p) => p.name === selected);
  if (!plan) return null;

  const isFree = plan.price === "$0" || !plan.isCurrentPhase;
  const currentPriceNum = parseInt(plan.price?.replace(/[^0-9]/g, "") ?? "0");
  const phase3PriceNum = parseInt(plan.phase3Price?.replace(/[^0-9]/g, "") ?? "0");
  const savingPct =
    !isFree && phase3PriceNum > currentPriceNum
      ? Math.round(((phase3PriceNum - currentPriceNum) / phase3PriceNum) * 100)
      : 0;

  return (
    <div className="relative mt-10 overflow-hidden rounded-2xl border border-violet-500/40 bg-violet-500/5 p-6 shadow-xl shadow-violet-500/10 md:p-8">
      <div aria-hidden className="pointer-events-none absolute -right-20 -top-20 h-64 w-64 rounded-full bg-violet-500/10 blur-3xl" />

      <div className="relative">
        {/* Pill switcher */}
        <div className="inline-flex gap-1 rounded-full border border-border bg-background/60 p-1">
          {allTiers.map((tier) => (
            <button
              key={tier.name}
              type="button"
              onClick={() => setSelected(tier.name)}
              className={`rounded-full px-4 py-1.5 text-xs font-semibold transition-all ${
                selected === tier.name
                  ? "bg-violet-600 text-white shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {tier.name}
            </button>
          ))}
        </div>

        {/* Spots counter */}
        {!isFree && spotsLeft !== null && (
          <div className="mt-6">
            <div className="mb-2 flex items-center justify-between text-xs">
              <span className="font-semibold text-violet-300">
                {spotsLeft === 0
                  ? "Phase full"
                  : `${spotsLeft} founder spot${spotsLeft === 1 ? "" : "s"} remaining`}
              </span>
              <span className="text-muted-foreground">
                {signupCount} / {spotLimit} taken
              </span>
            </div>
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-violet-500/15">
              <div
                className="h-full rounded-full bg-violet-500 transition-all"
                style={{ width: `${fillPct}%` }}
              />
            </div>
          </div>
        )}

        {/* Price */}
        <div className="mt-6 flex flex-wrap items-end gap-3">
          <div className="flex items-end gap-2">
            <span className="text-5xl font-bold tracking-tight">{plan.price}</span>
            {plan.billingNote && (
              <span className="mb-1.5 text-base text-muted-foreground">{plan.billingNote}</span>
            )}
          </div>
          {savingPct > 0 && (
            <span className="mb-1.5 inline-flex items-center rounded-full bg-emerald-500/15 px-2.5 py-0.5 text-xs font-semibold text-emerald-400">
              Save {savingPct}%
            </span>
          )}
        </div>

        {plan.annualLabel && !isFree && (
          <p className="mt-1 text-xs text-muted-foreground">{plan.annualLabel}</p>
        )}

        {plan.description && (
          <p className="mt-2 text-sm text-muted-foreground">{plan.description}</p>
        )}

        {/* Features */}
        {plan.features && plan.features.length > 0 && (
          <ul className="mt-6 grid gap-2 sm:grid-cols-2">
            {plan.features.map((f) => (
              <li key={f} className="flex items-center gap-2.5 text-sm">
                <Check className="h-4 w-4 shrink-0 text-violet-400" />
                <span>{f}</span>
              </li>
            ))}
          </ul>
        )}

        {/* CTA */}
        <div className="mt-8 flex flex-col gap-3 sm:flex-row sm:items-center">
          {isFree ? (
            <Link
              href="/auth/sign-up"
              className="inline-flex items-center justify-center gap-2 rounded-xl border border-border bg-background px-7 py-3 text-sm font-semibold transition-all hover:bg-muted"
            >
              {plan.ctaLabel ?? "Start free"}
              <ArrowRight className="h-4 w-4" />
            </Link>
          ) : (
            <Link
              href="/auth/sign-up"
              className="inline-flex items-center justify-center gap-2 rounded-xl bg-violet-600 px-7 py-3 text-sm font-semibold text-white shadow-lg shadow-violet-500/20 transition-all hover:bg-violet-500"
            >
              {plan.ctaLabel ?? "Lock in this rate"}
              <ArrowRight className="h-4 w-4" />
            </Link>
          )}
          {!isFree && founderNote && (
            <p className="text-xs leading-5 text-muted-foreground sm:max-w-[280px]">
              {founderNote}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}