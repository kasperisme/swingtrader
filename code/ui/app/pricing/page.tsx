import type { Metadata } from "next";
import Link from "next/link";
import { Check } from "lucide-react";
import { EarlyAccessSignupForm } from "@/components/early-access-signup-form";
import { PricingCheckoutButton } from "@/components/pricing-checkout-button";

export const metadata: Metadata = {
  title: "Pricing — newsimpactscreener",
  description:
    "Simple phase-based pricing. Lock in the lowest rate during early access — your price is grandfathered for life.",
};

// ── Data ──────────────────────────────────────────────────────────────────────

const TIERS = [
  {
    id: "observer",
    name: "Observer",
    badge: "Free",
    badgeStyle: "free" as const,
    monthlyByPhase: [0, 0, 0],
    annualByPhase: [0, 0, 0],
    annualLabelByPhase: ["Always free", "Always free", "Always free"],
    features: [
      "Daily top-5 news-impacted stocks",
      "Basic impact score",
      "1-day delay on results",
    ],
    highlighted: false,
  },
  {
    id: "investor",
    name: "Investor",
    badge: null,
    badgeStyle: null,
    monthlyByPhase: [9, 29, 39],
    annualByPhase: [99, 299, 399],
    annualLabelByPhase: [
      "$99/yr · lock in forever",
      "$299/yr",
      "$399/yr",
    ],
    features: [
      "Real-time news impact screener",
      "Full impact score breakdown",
      "Sector & theme filters",
      "Watchlist alerts",
      "7-day history",
    ],
    highlighted: true,
  },
  {
    id: "trader",
    name: "Trader",
    badge: null,
    badgeStyle: null,
    monthlyByPhase: [19, 49, 69],
    annualByPhase: [199, 499, 699],
    annualLabelByPhase: [
      "$199/yr · lock in forever",
      "$499/yr",
      "$699/yr",
    ],
    features: [
      "Everything in Investor",
      "Extended 30-day history",
      "AI-generated stock summaries",
      "Portfolio impact view",
      "Priority support",
    ],
    highlighted: false,
  },
];

const PHASES = [
  {
    label: "Phase 1",
    userRange: "Now → ~100 users",
    description: "Founder's early access — closes when seats fill",
    badgeLabel: "Early access",
    badgeStyle: "founder" as const,
    isCurrent: true,
    notes: null,
    bullets: null,
  },
  {
    label: "Phase 2",
    userRange: "100–500 users",
    description: "Growth pricing — social proof established, brand building",
    badgeLabel: "Standard",
    badgeStyle: "standard" as const,
    isCurrent: false,
    notes: null,
    bullets: [
      "Trigger: 100 paying users + 3 documented wins published as case studies",
      "Phase 1 subscribers grandfathered at their rate permanently",
    ],
  },
  {
    label: "Phase 3",
    userRange: "500+ users",
    description: "Full pricing — established product, proven track record",
    badgeLabel: "Full price",
    badgeStyle: "full" as const,
    isCurrent: false,
    notes: null,
    bullets: [
      "Trader at $69/mo exceeds StockGeist Pro ($100) only when brand is proven",
      "Phase 1 + Phase 2 annual subscribers grandfathered",
    ],
  },
];

// ── Sub-components ────────────────────────────────────────────────────────────

const phaseLabelColor: Record<string, string> = {
  Phase1: "text-amber-400",
  Phase2: "text-blue-400",
  Phase3: "text-violet-400",
};

const badgeStyles: Record<string, string> = {
  free: "bg-card border border-border text-foreground",
  founder: "bg-amber-500/20 border border-amber-500/30 text-amber-300",
  standard: "bg-blue-500/20 border border-blue-500/30 text-blue-300",
  full: "bg-violet-500/20 border border-violet-500/30 text-violet-300",
};

const cardHighlightStyle: Record<string, string> = {
  founder: "border-amber-500/50 shadow-lg shadow-amber-500/10",
  standard: "border-blue-500/50 shadow-lg shadow-blue-500/10",
  full: "border-violet-500/50 shadow-lg shadow-violet-500/10",
};

const FINAL_PHASE_INDEX = PHASES.length - 1;

function PriceCard({
  tier,
  phaseIndex,
  phaseBadge,
}: {
  tier: (typeof TIERS)[number];
  phaseIndex: number;
  phaseBadge: string;
}) {
  const monthly = tier.monthlyByPhase[phaseIndex];
  const annualLabel = tier.annualLabelByPhase[phaseIndex];
  const isHighlighted = tier.highlighted;
  const isFree = monthly === 0;
  const badgeStyle = isFree ? "free" : phaseBadge;

  const finalMonthly = tier.monthlyByPhase[FINAL_PHASE_INDEX];
  const savingPct =
    !isFree && phaseIndex < FINAL_PHASE_INDEX && finalMonthly > monthly
      ? Math.round(((finalMonthly - monthly) / finalMonthly) * 100)
      : 0;

  return (
    <div
      className={`flex flex-col rounded-2xl border bg-card/60 p-5 transition-all ${
        isHighlighted
          ? `${cardHighlightStyle[phaseBadge]} bg-card/80`
          : "border-border"
      }`}
    >
      {/* Badge */}
      <span
        className={`self-start rounded-full px-2.5 py-0.5 text-xs font-semibold ${badgeStyles[badgeStyle]}`}
      >
        {isFree ? "Free" : PHASES.find((_, i) => i === phaseIndex)?.badgeLabel ?? ""}
      </span>

      {/* Name */}
      <p className="mt-3 text-base font-bold">{tier.name}</p>

      {/* Price */}
      <div className="mt-2">
        {isFree ? (
          <>
            <span className="text-3xl font-bold">$0</span>
            <p className="mt-0.5 text-xs text-muted-foreground">Always free</p>
          </>
        ) : (
          <>
            <div className="flex items-baseline gap-2">
              <span className="text-3xl font-bold">${monthly}</span>
              <span className="text-sm text-muted-foreground">/mo</span>
              {savingPct > 0 && (
                <span className="inline-flex items-center rounded-full bg-emerald-500/15 px-2 py-0.5 text-xs font-semibold text-emerald-400">
                  -{savingPct}%
                </span>
              )}
            </div>
            <p className="mt-0.5 text-xs text-muted-foreground">{annualLabel}</p>
          </>
        )}
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function PricingPage() {
  return (
    <main className="min-h-screen">
      {/* Header */}
      <section className="border-b border-border py-16 md:py-20">
        <div className="mx-auto max-w-3xl px-4 sm:px-6 lg:px-8 text-center">
          <p className="text-xs font-semibold uppercase tracking-widest text-amber-500">
            Pricing
          </p>
          <h1 className="mt-3 text-3xl font-bold tracking-tight sm:text-4xl">
            Lock in the lowest rate before it's gone
          </h1>
          <p className="mt-4 max-w-xl mx-auto text-sm leading-6 text-muted-foreground">
            We raise prices as we grow. Early subscribers keep their rate forever — even as we add features and increase prices for new users.
          </p>
        </div>
      </section>

      {/* Phase timeline */}
      <section className="py-16 md:py-20">
        <div className="mx-auto max-w-4xl px-4 sm:px-6 lg:px-8">
          {/* Section label */}
          <p className="mb-10 text-xs font-semibold uppercase tracking-widest text-muted-foreground/60">
            Launch Phases
          </p>

          <div className="relative">
            {/* Vertical timeline line */}
            <div className="absolute left-[88px] top-3 hidden h-[calc(100%-24px)] w-px bg-gradient-to-b from-amber-500/60 via-blue-500/30 to-violet-500/20 sm:block" />

            <div className="flex flex-col gap-14">
              {PHASES.map((phase, phaseIndex) => {
                const colorKey = phase.label.replace(" ", "");
                const labelColor = phaseLabelColor[colorKey] ?? "text-muted-foreground";

                return (
                  <div key={phase.label} className="flex gap-6 sm:gap-10">
                    {/* Left: phase label */}
                    <div className="hidden sm:flex w-[88px] shrink-0 flex-col items-end pt-1 pr-6">
                      <div className="flex items-center gap-1.5">
                        <span className={`text-sm font-bold ${labelColor}`}>
                          {phase.label}
                        </span>
                        {phase.isCurrent && (
                          <span className="rounded-full bg-amber-500/20 px-1.5 py-0.5 text-[10px] font-semibold text-amber-400">
                            Now
                          </span>
                        )}
                      </div>
                      <span className="mt-0.5 text-right text-[11px] leading-tight text-muted-foreground/60">
                        {phase.userRange}
                      </span>
                    </div>

                    {/* Timeline dot */}
                    <div className="hidden sm:flex absolute left-[82px] mt-2 h-3 w-3 items-center justify-center">
                      <div
                        className={`h-2.5 w-2.5 rounded-full border-2 ${
                          phase.isCurrent
                            ? "border-amber-400 bg-amber-400/30"
                            : phaseIndex === 1
                            ? "border-blue-400 bg-blue-400/20"
                            : "border-violet-400 bg-violet-400/20"
                        }`}
                      />
                    </div>

                    {/* Right: content */}
                    <div className="flex-1 min-w-0">
                      {/* Mobile phase label */}
                      <div className="mb-3 flex items-baseline gap-2 sm:hidden">
                        <span className={`text-sm font-bold ${labelColor}`}>
                          {phase.label}
                        </span>
                        {phase.isCurrent && (
                          <span className="rounded-full bg-amber-500/20 px-1.5 py-0.5 text-[10px] font-semibold text-amber-400">
                            Now
                          </span>
                        )}
                        <span className="text-xs text-muted-foreground/60">
                          {phase.userRange}
                        </span>
                      </div>

                      {/* Price cards */}
                      <div className="grid grid-cols-3 gap-3">
                        {TIERS.map((tier) => (
                          <PriceCard
                            key={tier.id}
                            tier={tier}
                            phaseIndex={phaseIndex}
                            phaseBadge={phase.badgeStyle}
                          />
                        ))}
                      </div>


                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </section>

      {/* Feature gates */}
      <section className="border-t border-border py-16 md:py-20">
        <div className="mx-auto max-w-4xl px-4 sm:px-6 lg:px-8">
          <p className="mb-8 text-xs font-semibold uppercase tracking-widest text-muted-foreground/60">
            What&apos;s included
          </p>

          <div className="overflow-x-auto">
            <table className="w-full">
              {/* Sticky header */}
              <thead>
                <tr>
                  <th className="w-2/5 pb-4 text-left text-xs font-medium text-muted-foreground" />
                  <th className="pb-4 text-center">
                    <span className="text-sm font-semibold text-muted-foreground">Observer</span>
                    <p className="mt-0.5 text-xs text-muted-foreground/50">Free</p>
                  </th>
                  <th className="pb-4 text-center">
                    <span className="text-sm font-semibold text-amber-400">Investor</span>
                    <p className="mt-0.5 text-xs text-amber-400/60">$9/mo</p>
                  </th>
                  <th className="pb-4 text-center">
                    <span className="text-sm font-semibold text-muted-foreground">Trader</span>
                    <p className="mt-0.5 text-xs text-muted-foreground/50">$19/mo</p>
                  </th>
                </tr>
              </thead>

              <tbody>
                {/* ── Screener ── */}
                <SectionHeader label="Screener" />
                {[
                  {
                    feature: "News impact screener",
                    gate: "The ticker list is visible but blurred — you can see there are 7 stocks, can almost read the names. Upgrade CTA sits on top.",
                    observer: false,
                    investor: true,
                    trader: true,
                  },
                  {
                    feature: "Real-time results",
                    gate: "Free tier shows yesterday's data. The timestamp is visible and grayed.",
                    observer: "1-day delay",
                    investor: true,
                    trader: true,
                  },
                  {
                    feature: "Full impact score breakdown",
                    gate: "Score visible, factor bars blurred below.",
                    observer: false,
                    investor: true,
                    trader: true,
                  },
                  {
                    feature: "Sector & theme filters",
                    gate: "Filter panel visible but locked.",
                    observer: false,
                    investor: true,
                    trader: true,
                  },
                  {
                    feature: "Watchlist alerts",
                    observer: false,
                    investor: true,
                    trader: true,
                  },
                  {
                    feature: "Result history",
                    observer: "24h",
                    investor: "7 days",
                    trader: "30 days",
                  },
                ].map((row) => (
                  <GateRow key={row.feature} {...row} />
                ))}

                {/* ── Advanced ── */}
                <SectionHeader label="Advanced tools" />
                {[
                  {
                    feature: "AI stock summaries",
                    gate: "Summary card visible, content replaced with placeholder lines.",
                    observer: false,
                    investor: false,
                    trader: true,
                  },
                  {
                    feature: "Portfolio impact view",
                    observer: false,
                    investor: false,
                    trader: true,
                  },
                  {
                    feature: "Factor breakdown",
                    gate: "Trader-only. Shows which signals drove the score.",
                    observer: false,
                    investor: false,
                    trader: true,
                  },
                  {
                    feature: "Priority support",
                    observer: false,
                    investor: false,
                    trader: true,
                  },
                ].map((row) => (
                  <GateRow key={row.feature} {...row} />
                ))}

                {/* ── API ── */}
                <SectionHeader label="API access" />
                {[
                  {
                    feature: "API key",
                    gate: "Requires account creation + email verification. Low friction, stops abuse.",
                    observer: true,
                    investor: true,
                    trader: true,
                  },
                  {
                    feature: "Requests / day",
                    gate: "50 req/day is enough to explore, not enough to run a workflow — the upgrade trigger is natural.",
                    observer: "50",
                    investor: "500",
                    trader: "Unlimited",
                  },
                  {
                    feature: "Historical depth",
                    observer: "24h",
                    investor: "30 days",
                    trader: "Full archive",
                  },
                  {
                    feature: "Endpoints",
                    observer: "Articles + sector",
                    investor: "+ tickers + watchlist",
                    trader: "All",
                  },
                  {
                    feature: "Factor breakdown via API",
                    observer: false,
                    investor: false,
                    trader: true,
                  },
                ].map((row) => (
                  <GateRow key={row.feature} {...row} />
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="border-t border-border py-16 md:py-20">
        <div className="mx-auto max-w-2xl px-4 text-center">
          <span className="inline-flex items-center rounded-full bg-amber-500/10 border border-amber-500/20 px-3 py-1 text-xs font-semibold text-amber-400 mb-4">
            Phase 1 — {100} founder spots
          </span>
          <h2 className="text-2xl font-bold tracking-tight sm:text-3xl">
            Lock in founder pricing before Phase 1 fills
          </h2>
          <p className="mt-3 text-sm text-muted-foreground">
            Your rate is locked for life. Cancel any time — but once you cancel, the founder rate is gone.
          </p>
          <PricingCheckoutButton />
          <p className="mt-4 text-xs text-muted-foreground">Cancel any time. No lock-in beyond your current period.</p>
        </div>
      </section>
    </main>
  );
}

function SectionHeader({ label }: { label: string }) {
  return (
    <tr>
      <td colSpan={4} className="pb-2 pt-8 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground/50">
        {label}
      </td>
    </tr>
  );
}

function Cell({ value, col }: { value: string | boolean; col: "observer" | "investor" | "trader" }) {
  const isInvestor = col === "investor";
  if (value === false) {
    return <td className="py-2.5 text-center"><span className="text-muted-foreground/25">—</span></td>;
  }
  if (value === true) {
    return (
      <td className="py-2.5 text-center">
        <Check className={`mx-auto h-4 w-4 ${isInvestor ? "text-amber-400" : "text-emerald-400"}`} />
      </td>
    );
  }
  return (
    <td className="py-2.5 text-center">
      <span className={`text-xs font-medium ${isInvestor ? "text-amber-300" : "text-muted-foreground"}`}>
        {value}
      </span>
    </td>
  );
}

function GateRow({
  feature,
  gate,
  observer,
  investor,
  trader,
}: {
  feature: string;
  gate?: string;
  observer: string | boolean;
  investor: string | boolean;
  trader: string | boolean;
}) {
  return (
    <tr className="border-t border-border/40 hover:bg-muted/20 transition-colors">
      <td className="py-2.5 pr-4">
        <p className="text-sm">{feature}</p>
      </td>
      <Cell value={observer} col="observer" />
      <Cell value={investor} col="investor" />
      <Cell value={trader} col="trader" />
    </tr>
  );
}
