import { Suspense } from "react";
import { redirect } from "next/navigation";
import Link from "next/link";
import { createClient } from "@/lib/supabase/server";
import { OpsCenterUI, type UserTradeRow } from "./ops-center-ui";

async function OpsCenterData() {
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
    return (
      <div className="rounded-lg border border-border bg-card p-6 text-sm text-muted-foreground">
        <p className="font-medium text-foreground">Could not load portfolio</p>
        <p className="mt-2">{error.message}</p>
      </div>
    );
  }

  return <OpsCenterUI initialTrades={(rows ?? []) as UserTradeRow[]} />;
}

export default function ProtectedPage() {
  return (
    <div className="flex-1 w-full flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h1 className="text-sm font-semibold uppercase tracking-widest text-muted-foreground/50">Portfolio</h1>
        <Link href="/protected/trades" className="text-xs text-muted-foreground hover:text-foreground transition-colors">
          Manage trades →
        </Link>
      </div>

      <Suspense
        fallback={
          <div className="text-sm text-muted-foreground animate-pulse rounded-lg border border-border p-6">
            Loading portfolio…
          </div>
        }
      >
        <OpsCenterData />
      </Suspense>
    </div>
  );
}