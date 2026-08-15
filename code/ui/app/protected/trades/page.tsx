import { Suspense } from "react";
import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { TradesUI, type UserTradeRow } from "./trades-ui";
import { getOnboardingTours } from "@/app/actions/onboarding";
import { PageTour } from "@/app/protected/_components/page-tour";

async function TradesTourMount() {
  const tours = await getOnboardingTours();
  return <PageTour tourKey="trade" autoStart={!tours.trade} />;
}

async function TradesData() {
  const supabase = await createClient();
  const { data: claims, error: claimsError } = await supabase.auth.getClaims();

  if (claimsError || !claims?.claims) {
    redirect("/auth/login");
  }

  const { data: rows, error } = await supabase
    .schema("swingtrader")
    .from("user_trades")
    .select("*")
    .order("executed_at", { ascending: false })
    .limit(500);

  if (error) {
    console.error("user_trades fetch failed:", error);
    return (
      <div
        role="alert"
        className="rounded-lg border border-destructive/40 bg-destructive/5 p-6 text-sm text-muted-foreground"
      >
        <p className="font-medium text-foreground">Could not load trades</p>
        <p className="mt-2">{error.message}</p>
        <p className="mt-2 text-xs">
          If the table is missing, apply the migration{" "}
          <code className="rounded bg-muted px-1 py-0.5 font-mono text-[11px]">
            20260409150000_user_trades.sql
          </code>{" "}
          and ensure <code className="rounded bg-muted px-1 py-0.5 font-mono text-[11px]">swingtrader</code> is in the API
          search path.
        </p>
      </div>
    );
  }

  return <TradesUI initialTrades={(rows ?? []) as UserTradeRow[]} />;
}

export default function TradesPage() {
  return (
    <div className="flex-1 w-full flex flex-col gap-6">
      {/* Same header system as /profile, /quote and /topics: rule + eyebrow,
          tracking-tighter title, a rule under it. amber-700 in light because
          amber-500 on the near-white ground measures ~2.1:1 — well under AA. */}
      <header className="border-b border-border/60 pb-6">
        <p className="mb-3 inline-flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.2em] text-amber-700 dark:text-amber-500/90">
          <span className="h-px w-6 bg-amber-500/60" />
          Portfolio
        </p>
        <h1 className="text-3xl font-bold leading-[1.05] tracking-tighter sm:text-4xl">
          Trades
        </h1>
        <p className="mt-3 max-w-[65ch] text-sm leading-relaxed text-muted-foreground">
          Log buy and sell executions for long or short positions. Your portfolio
          is replayed from this ledger — size and average entry are derived, not
          entered.
        </p>
      </header>

      {/* Skeleton mirrors the real layout (form card → filter row → sections) so
          the page doesn't reflow when the data lands. */}
      <Suspense
        fallback={
          <div className="flex flex-col gap-8" aria-hidden>
            <div className="h-64 animate-pulse rounded-xl border border-border bg-card" />
            <div className="h-11 w-64 animate-pulse rounded-lg border border-border bg-card" />
            <div className="h-40 animate-pulse rounded-lg border border-border" />
            <span className="sr-only">Loading trades…</span>
          </div>
        }
      >
        <TradesData />
      </Suspense>
      <Suspense fallback={null}>
        <TradesTourMount />
      </Suspense>
    </div>
  );
}
