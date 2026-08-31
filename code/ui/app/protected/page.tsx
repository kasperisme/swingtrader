import { Suspense } from "react";
import { redirect } from "next/navigation";
import Link from "next/link";
import { createClient } from "@/lib/supabase/server";
import { OpsCenterUI, type UserTradeRow } from "./ops-center-ui";
import { AskAiReminder } from "./_components/ask-ai-reminder";
import { DashboardSummaryCards } from "./dashboard-summary-cards";
import {
  fetchAgentsSummary,
  fetchWorkspaceSummary,
} from "./dashboard-summary";
import { buildPortfolioFromTrades } from "@/app/protected/trades/portfolio-from-trades";

async function OpsCenterData() {
  const supabase = await createClient();
  const { data: claims, error: claimsError } = await supabase.auth.getClaims();

  if (claimsError || !claims?.claims) {
    redirect("/auth/login");
  }
  const userId = String(claims.claims.sub);

  // Every block is independent, so one slow or broken surface should not hold
  // the other two. The summaries already swallow their own errors; only the
  // trades read can fail loudly, because without it there is no page.
  const [tradesRes, workspace, agents] = await Promise.all([
    supabase
      .schema("swingtrader")
      .from("user_trades")
      .select("*")
      .order("executed_at", { ascending: false })
      .limit(500),
    fetchWorkspaceSummary(userId),
    fetchAgentsSummary(userId),
  ]);

  if (tradesRes.error) {
    return (
      <div className="rounded-lg border border-border bg-card p-6 text-sm text-muted-foreground">
        <p className="font-medium text-foreground">Could not load portfolio</p>
        <p className="mt-2">{tradesRes.error.message}</p>
      </div>
    );
  }

  const trades = (tradesRes.data ?? []) as UserTradeRow[];

  return (
    <div className="flex flex-col gap-6">
      <DashboardSummaryCards
        workspace={workspace}
        agents={agents}
        positions={buildPortfolioFromTrades(trades)}
      />

      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-widest text-muted-foreground/50">
          Portfolio
        </h2>
        <Link
          href="/protected/trades"
          className="text-xs text-muted-foreground transition-colors hover:text-foreground"
        >
          Manage trades →
        </Link>
      </div>

      <OpsCenterUI initialTrades={trades} />
    </div>
  );
}

function SummarySkeleton() {
  return (
    <div className="flex flex-col gap-6" aria-busy="true">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {[0, 1, 2].map((i) => (
          <div
            key={i}
            className="h-[7.5rem] animate-pulse rounded-xl border border-border bg-card"
          />
        ))}
      </div>
      <div className="h-40 animate-pulse rounded-lg border border-border" />
      <span className="sr-only">Loading your dashboard…</span>
    </div>
  );
}

export default function ProtectedPage() {
  return (
    <div className="flex w-full flex-1 flex-col gap-4">
      <AskAiReminder />

      <h1 className="text-sm font-semibold uppercase tracking-widest text-muted-foreground/50">
        Overview
      </h1>

      <Suspense fallback={<SummarySkeleton />}>
        <OpsCenterData />
      </Suspense>
    </div>
  );
}
