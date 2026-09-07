"use client";

import { ArrowRight } from "lucide-react";
import { useStripeCheckout } from "@/components/upgrade-button";

/**
 * The two checkout buttons under the pricing CTA.
 *
 * Prices are passed in rather than written here: they used to be the literals
 * "$9" and "$19", which stayed on the button after the price changed and quoted
 * a rate Stripe would no longer charge. The caller reads them from lib/pricing.
 *
 * The labels used to say "Lock in $29/mo", which only meant anything while a
 * launch ladder promised the rate would rise. It does not, so the button says
 * what it buys instead of racing a deadline that is not there.
 */
export function PricingCheckoutButton({
  investorMonthly,
  traderMonthly,
}: {
  investorMonthly: number;
  traderMonthly: number;
}) {
  const { start, busy } = useStripeCheckout("pricing_page");
  return (
    <div className="mt-8 flex flex-col items-center gap-3 sm:flex-row sm:justify-center">
      <button
        onClick={() => start("investor")}
        disabled={busy !== null}
        className="inline-flex items-center justify-center gap-2 rounded-xl bg-violet-600 px-6 py-3 text-sm font-semibold text-white shadow-lg shadow-violet-500/20 transition-all hover:bg-violet-500 disabled:opacity-60"
      >
        {busy === "investor" ? "Redirecting…" : `Get Investor — $${investorMonthly}/mo`}
        <ArrowRight className="h-4 w-4" />
      </button>
      <button
        onClick={() => start("trader")}
        disabled={busy !== null}
        className="inline-flex items-center justify-center gap-2 rounded-xl border border-border bg-background px-6 py-3 text-sm font-semibold transition-all hover:bg-muted disabled:opacity-60"
      >
        {busy === "trader" ? "Redirecting…" : `Get Trader — $${traderMonthly}/mo`}
        <ArrowRight className="h-4 w-4" />
      </button>
    </div>
  );
}
