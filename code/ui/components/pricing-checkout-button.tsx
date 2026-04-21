"use client";

import Link from "next/link";
import { ArrowRight } from "lucide-react";

export function PricingCheckoutButton() {
  return (
    <div className="mt-8 flex flex-col items-center gap-3 sm:flex-row sm:justify-center">
      <Link
        href="/auth/sign-up"
        className="inline-flex items-center justify-center gap-2 rounded-xl bg-violet-600 px-6 py-3 text-sm font-semibold text-white shadow-lg shadow-violet-500/20 transition-all hover:bg-violet-500"
      >
        Lock in $9/mo
        <ArrowRight className="h-4 w-4" />
      </Link>
      <Link
        href="/auth/sign-up"
        className="inline-flex items-center justify-center gap-2 rounded-xl border border-border bg-background px-6 py-3 text-sm font-semibold transition-all hover:bg-muted"
      >
        Lock in $19/mo
        <ArrowRight className="h-4 w-4" />
      </Link>
    </div>
  );
}