"use client";

import { ArrowRight } from "lucide-react";
import { useStripeCheckout } from "@/components/upgrade-button";

export function PricingCheckoutButton() {
  const { start, busy } = useStripeCheckout("pricing_page");
  return (
    <div className="mt-8 flex flex-col items-center gap-3 sm:flex-row sm:justify-center">
      <button
        onClick={() => start("investor")}
        disabled={busy !== null}
        className="inline-flex items-center justify-center gap-2 rounded-xl bg-violet-600 px-6 py-3 text-sm font-semibold text-white shadow-lg shadow-violet-500/20 transition-all hover:bg-violet-500 disabled:opacity-60"
      >
        {busy === "investor" ? "Redirecting…" : "Lock in $9/mo"}
        <ArrowRight className="h-4 w-4" />
      </button>
      <button
        onClick={() => start("trader")}
        disabled={busy !== null}
        className="inline-flex items-center justify-center gap-2 rounded-xl border border-border bg-background px-6 py-3 text-sm font-semibold transition-all hover:bg-muted disabled:opacity-60"
      >
        {busy === "trader" ? "Redirecting…" : "Lock in $19/mo"}
        <ArrowRight className="h-4 w-4" />
      </button>
    </div>
  );
}
