import { Suspense } from "react";
import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { AgentsUI } from "./agents-ui";
import {
  listScheduledScreenings,
  getScreeningLimits,
} from "@/app/actions/screenings-agent";
import { getOnboardingTours } from "@/app/actions/onboarding";
import { PageTour } from "@/app/protected/_components/page-tour";

async function AgentsTourMount() {
  const tours = await getOnboardingTours();
  return <PageTour tourKey="agent" autoStart={!tours.agent} />;
}

async function fetchVectorTickers(): Promise<string[]> {
  const supabase = await createClient();
  const { data, error } = await supabase
    .schema("swingtrader")
    .from("company_vectors")
    .select("ticker")
    .order("ticker", { ascending: true });

  if (error) return [];

  const seen = new Set<string>();
  const out: string[] = [];
  for (const row of data ?? []) {
    const t = String(row.ticker ?? "").trim().toUpperCase();
    if (t && !seen.has(t)) { seen.add(t); out.push(t); }
  }
  return out;
}

async function fetchTelegramConnected(userId: string): Promise<boolean> {
  const supabase = await createClient();
  const { data } = await supabase
    .schema("swingtrader")
    .from("user_telegram_connections")
    .select("chat_id")
    .eq("user_id", userId)
    .limit(1)
    .maybeSingle();
  return Boolean(data?.chat_id);
}

async function AgentsData() {
  const supabase = await createClient();
  const { data: claims } = await supabase.auth.getClaims();
  const userId = claims?.claims?.sub;
  if (!userId) redirect("/auth/login");

  const [screeningsRes, limitsRes, suggestionTickers, telegramConnected] = await Promise.all([
    listScheduledScreenings(),
    getScreeningLimits(),
    fetchVectorTickers(),
    fetchTelegramConnected(userId),
  ]);

  return (
    <AgentsUI
      screenings={screeningsRes.ok ? screeningsRes.data : []}
      limits={limitsRes.ok ? limitsRes.data : null}
      error={screeningsRes.ok ? null : screeningsRes.error}
      suggestionTickers={suggestionTickers}
      telegramConnected={telegramConnected}
    />
  );
}

export default function AgentsPage() {
  return (
    <div className="mx-auto w-full min-w-0 max-w-4xl px-4 py-8 sm:py-10">
      <header className="mb-8 border-b border-border/60 pb-6">
        <div className="mb-2 flex items-center gap-2">
          <span className="inline-block h-1.5 w-1.5 rounded-full bg-amber-500" />
          <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-amber-500">Agents</p>
        </div>
        <h1 className="text-3xl font-bold leading-none tracking-tighter text-foreground sm:text-4xl">
          Scheduled Agents
        </h1>
        <p className="mt-3 max-w-[58ch] text-sm leading-relaxed text-muted-foreground">
          Write a prompt describing what to watch for. The agent runs it on
          schedule and pings you the moment your conditions are met.
        </p>
      </header>
      <Suspense fallback={<div className="text-muted-foreground/40 text-sm">Loading…</div>}>
        <AgentsData />
      </Suspense>
      <Suspense fallback={null}>
        <AgentsTourMount />
      </Suspense>
    </div>
  );
}
