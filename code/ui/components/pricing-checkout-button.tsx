"use client";

import { useState } from "react";
import { ArrowRight, Loader2 } from "lucide-react";

export function PricingCheckoutButton() {
  const [loading, setLoading] = useState(false);
  const [loadingPlan, setLoadingPlan] = useState<"investor" | "trader" | null>(null);

  async function handleCheckout(plan: "investor" | "trader") {
    setLoading(true);
    setLoadingPlan(plan);
    try {
      const res = await fetch("/api/stripe/checkout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ plan, interval: "monthly" }),
      });
      const data = (await res.json().catch(() => ({}))) as { url?: string; error?: string };
      if (data.url) {
        window.location.href = data.url;
      } else if (data.error === "Unauthorized") {
        window.location.href = "/auth/sign-up";
      } else {
        alert(data.error ?? "Something went wrong. Please try again.");
      }
    } catch {
      alert("Network error. Please try again.");
    } finally {
      setLoading(false);
      setLoadingPlan(null);
    }
  }

  return (
    <div className="mt-8 flex flex-col items-center gap-3 sm:flex-row sm:justify-center">
      <button
        type="button"
        onClick={() => handleCheckout("investor")}
        disabled={loading}
        className="inline-flex items-center justify-center gap-2 rounded-xl bg-violet-600 px-6 py-3 text-sm font-semibold text-white shadow-lg shadow-violet-500/20 transition-all hover:bg-violet-500 disabled:pointer-events-none disabled:opacity-60"
      >
        {loading && loadingPlan === "investor" ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <>
            Lock in $9/mo
            <ArrowRight className="h-4 w-4" />
          </>
        )}
      </button>
      <button
        type="button"
        onClick={() => handleCheckout("trader")}
        disabled={loading}
        className="inline-flex items-center justify-center gap-2 rounded-xl border border-border bg-background px-6 py-3 text-sm font-semibold transition-all hover:bg-muted disabled:pointer-events-none disabled:opacity-60"
      >
        {loading && loadingPlan === "trader" ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <>
            Lock in $19/mo
            <ArrowRight className="h-4 w-4" />
          </>
        )}
      </button>
    </div>
  );
}