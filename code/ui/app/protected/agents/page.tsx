import { Suspense } from "react";
import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { AgentsUI } from "./agents-ui";
import {
  listScheduledScreenings,
  getScreeningLimits,
} from "@/app/actions/screenings-agent";

async function AgentsData() {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) redirect("/auth/login");

  const [screeningsRes, limitsRes] = await Promise.all([
    listScheduledScreenings(),
    getScreeningLimits(),
  ]);

  return (
    <AgentsUI
      screenings={screeningsRes.ok ? screeningsRes.data : []}
      limits={limitsRes.ok ? limitsRes.data : null}
      error={screeningsRes.ok ? null : screeningsRes.error}
    />
  );
}

export default function AgentsPage() {
  return (
    <div className="mx-auto max-w-4xl px-4 py-8">
      <div className="mb-8">
        <p className="text-xs font-semibold uppercase tracking-widest text-amber-500 mb-1">Agents</p>
        <h1 className="text-2xl font-bold text-foreground">Scheduled Agents</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Write a prompt describing what to watch for. The AI agent runs it on
          schedule and alerts you when conditions are met.
        </p>
      </div>
      <Suspense fallback={<div className="text-muted-foreground/40 text-sm">Loading…</div>}>
        <AgentsData />
      </Suspense>
    </div>
  );
}
