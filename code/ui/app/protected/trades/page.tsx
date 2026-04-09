import { Suspense } from "react";
import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { TradesUI, type UserTradeRow } from "./trades-ui";

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
      <div className="rounded-lg border border-border bg-card p-6 text-sm text-muted-foreground">
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
      <div>
        <h1 className="text-2xl font-bold">Trades</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Log buy and sell executions for long or short positions. Stored in{" "}
          <code className="font-mono text-xs">swingtrader.user_trades</code>.
        </p>
      </div>

      <Suspense
        fallback={
          <div className="text-sm text-muted-foreground animate-pulse rounded-lg border border-border p-6">
            Loading trades…
          </div>
        }
      >
        <TradesData />
      </Suspense>
    </div>
  );
}
