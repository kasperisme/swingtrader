import type { Metadata } from "next";
import { Check } from "lucide-react";
import { PricingCheckoutButton } from "@/components/pricing-checkout-button";
import {
  annualLabel,
  annualSavingPct,
  monthlyPrice,
} from "@/lib/pricing";

export const metadata: Metadata = {
  title: "Pricing",
  description:
    "Three plans: a free Observer tier, Investor at $29/mo and Trader at $49/mo. Every paid plan is month-to-month — cancel any time.",
  alternates: { canonical: "/pricing" },
  openGraph: { url: "/pricing" },
};

// ── Data ──────────────────────────────────────────────────────────────────────

const TIERS = [
  {
    id: "observer" as const,
    name: "Observer",
    badge: "Free",
    features: [
      "Daily top-5 news-impacted stocks",
      "Basic impact score",
      "1-day delay on results",
    ],
    highlighted: false,
  },
  {
    id: "investor" as const,
    name: "Investor",
    badge: "Most popular",
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
    id: "trader" as const,
    name: "Trader",
    badge: null,
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

// ── Sub-components ────────────────────────────────────────────────────────────

const badgeStyles: Record<string, string> = {
  free: "bg-card border border-border text-foreground",
  paid: "bg-amber-500/20 border border-amber-500/30 text-amber-300",
};

/**
 * One tier, one price.
 *
 * This replaced a three-row launch-phase timeline in which every tier was
 * rendered three times — once at its phase-1 rate struck through, once live,
 * once as a future rise. The ladder was a promise to raise prices that the
 * product stopped intending to keep, and a page that shows a reader two prices
 * they cannot buy costs more attention than the one they can.
 */
function PriceCard({ tier }: { tier: (typeof TIERS)[number] }) {
  const monthly = monthlyPrice(tier.id);
  const isFree = monthly === 0;
  const saving = annualSavingPct(tier.id);

  return (
    <div
      className={`flex flex-col rounded-2xl border p-6 transition-all ${
        tier.highlighted
          ? "border-amber-500/50 bg-card/80 shadow-lg shadow-amber-500/10"
          : "border-border bg-card/60"
      }`}
    >
      {/* A badge on every card is a badge on none, so only the free tier and
          the one recommended plan wear one; Trader carries none. */}
      {tier.badge ? (
        <span
          className={`self-start rounded-full px-2.5 py-0.5 text-xs font-semibold ${
            badgeStyles[isFree ? "free" : "paid"]
          }`}
        >
          {tier.badge}
        </span>
      ) : (
        <span aria-hidden className="h-[22px]" />
      )}

      <p className="mt-3 text-base font-bold">{tier.name}</p>

      <div className="mt-2">
        <div className="flex items-baseline gap-2">
          <span className="text-4xl font-bold">${monthly}</span>
          {!isFree && <span className="text-sm text-muted-foreground">/mo</span>}
        </div>
        <p className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
          {annualLabel(tier.id)}
          {saving > 0 && (
            <span className="inline-flex items-center rounded-full bg-emerald-500/15 px-2 py-0.5 text-xs font-semibold text-emerald-400">
              save {saving}% annually
            </span>
          )}
        </p>
      </div>

      <ul className="mt-5 space-y-2 border-t border-border/50 pt-5">
        {tier.features.map((f) => (
          <li key={f} className="flex gap-2 text-sm text-muted-foreground">
            <Check
              className={`mt-0.5 h-4 w-4 shrink-0 ${
                tier.highlighted ? "text-amber-400" : "text-emerald-400"
              }`}
            />
            <span>{f}</span>
          </li>
        ))}
      </ul>
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
            One price, no countdown
          </h1>
          <p className="mt-4 max-w-xl mx-auto text-sm leading-6 text-muted-foreground">
            Start free and stay free, or take a paid plan month-to-month.
            No tiered launch ladder, no seat counter, no rate expiring on you
            at the end of the week.
          </p>
        </div>
      </section>

      {/* Plans */}
      <section className="py-16 md:py-20">
        <div className="mx-auto max-w-5xl px-4 sm:px-6 lg:px-8">
          <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
            {TIERS.map((tier) => (
              <PriceCard key={tier.id} tier={tier} />
            ))}
          </div>
          <p className="mt-6 text-xs text-muted-foreground/70">
            Prices are per account in USD. Annual billing is charged once up
            front. Subscribers already on an earlier rate keep it.
          </p>
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
                    <p className="mt-0.5 text-xs text-amber-400/60">
                      ${monthlyPrice("investor")}/mo
                    </p>
                  </th>
                  <th className="pb-4 text-center">
                    <span className="text-sm font-semibold text-muted-foreground">Trader</span>
                    <p className="mt-0.5 text-xs text-muted-foreground/50">
                      ${monthlyPrice("trader")}/mo
                    </p>
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
                    investor: "30 days",
                    trader: "400 days",
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
                    investor: true,
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
          <h2 className="text-2xl font-bold tracking-tight sm:text-3xl">
            Start screening the news that moves your stocks
          </h2>
          <p className="mt-3 text-sm text-muted-foreground">
            Month-to-month. Change tier or cancel from your profile whenever you
            like — no call, no retention flow.
          </p>
          <PricingCheckoutButton
            investorMonthly={monthlyPrice("investor")}
            traderMonthly={monthlyPrice("trader")}
          />
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
