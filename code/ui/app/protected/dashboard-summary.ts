import "server-only";

import { createClient } from "@/lib/supabase/server";

/**
 * The three numbers each surface of the product owes the dashboard.
 *
 * /protected used to be the portfolio and a row of links, which meant the only
 * way to learn that an agent had fired overnight, or that a screening still had
 * forty untriaged names in it, was to go and look. Each block below is a
 * summary of one surface, and every one is written to degrade to a "nothing
 * here yet" state rather than an error — a new account has no runs, no agents
 * and no trades, and that is the normal case, not a fault.
 */

export type WorkspaceSummary = {
  runCount: number;
  latest: { id: number; source: string; createdAt: string; rowCount: number } | null;
  /** Names the user has actively triaged into a list, across every active run. */
  watchlisted: number;
  pipeline: number;
};

export type AgentsSummary = {
  total: number;
  active: number;
  lastRun: {
    name: string;
    runAt: string;
    triggered: boolean;
    summary: string | null;
  } | null;
  /** Agents that fired their condition in the last 24 hours. */
  triggeredToday: number;
};

export async function fetchWorkspaceSummary(
  userId: string,
): Promise<WorkspaceSummary> {
  const empty: WorkspaceSummary = {
    runCount: 0,
    latest: null,
    watchlisted: 0,
    pipeline: 0,
  };
  const supabase = await createClient();

  const { data: runs, error } = await supabase
    .schema("swingtrader")
    .from("user_scan_runs")
    .select("id, created_at, source")
    .eq("user_id", userId)
    .or("status.eq.active,status.is.null")
    .order("created_at", { ascending: false })
    .limit(50);

  if (error) {
    console.error("[dashboard] scan runs failed:", error.message);
    return empty;
  }
  if (!runs || runs.length === 0) return empty;

  const top = runs[0];
  const [rowsRes, watchRes, pipeRes] = await Promise.all([
    supabase
      .schema("swingtrader")
      .from("user_scan_rows")
      .select("id", { count: "exact", head: true })
      .eq("run_id", top.id),
    supabase
      .schema("swingtrader")
      .from("user_scan_row_notes")
      .select("scan_row_id", { count: "exact", head: true })
      .eq("user_id", userId)
      .eq("status", "watchlist"),
    supabase
      .schema("swingtrader")
      .from("user_scan_row_notes")
      .select("scan_row_id", { count: "exact", head: true })
      .eq("user_id", userId)
      .eq("status", "pipeline"),
  ]);

  return {
    runCount: runs.length,
    latest: {
      id: Number(top.id),
      source: String(top.source ?? "screening"),
      createdAt: String(top.created_at),
      rowCount: rowsRes.count ?? 0,
    },
    watchlisted: watchRes.count ?? 0,
    pipeline: pipeRes.count ?? 0,
  };
}

export async function fetchAgentsSummary(
  userId: string,
): Promise<AgentsSummary> {
  const empty: AgentsSummary = {
    total: 0,
    active: 0,
    lastRun: null,
    triggeredToday: 0,
  };
  const supabase = await createClient();

  const { data: agents, error } = await supabase
    .schema("swingtrader")
    .from("user_scheduled_screenings")
    .select("id, name, is_active, last_run_at")
    .eq("user_id", userId);

  if (error) {
    console.error("[dashboard] agents failed:", error.message);
    return empty;
  }
  if (!agents || agents.length === 0) return empty;

  const nameById = new Map(agents.map((a) => [String(a.id), String(a.name)]));
  const since = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();

  // Real runs only — a test run is the user poking the agent, not the agent
  // reporting something.
  const [lastRes, firedRes] = await Promise.all([
    supabase
      .schema("swingtrader")
      .from("user_screening_results")
      .select("screening_id, run_at, triggered, summary")
      .eq("user_id", userId)
      .eq("is_test", false)
      .order("run_at", { ascending: false })
      .limit(1)
      .maybeSingle(),
    supabase
      .schema("swingtrader")
      .from("user_screening_results")
      .select("id", { count: "exact", head: true })
      .eq("user_id", userId)
      .eq("is_test", false)
      .eq("triggered", true)
      .gte("run_at", since),
  ]);

  const last = lastRes.data;
  return {
    total: agents.length,
    active: agents.filter((a) => a.is_active).length,
    lastRun: last
      ? {
          name: nameById.get(String(last.screening_id)) ?? "Agent",
          runAt: String(last.run_at),
          triggered: Boolean(last.triggered),
          summary: last.summary ? String(last.summary) : null,
        }
      : null,
    triggeredToday: firedRes.count ?? 0,
  };
}
