"use server";

import { createClient } from "@/lib/supabase/server";
import { getUserPlanTier } from "./plan-gate";
import { type PlanTier } from "@/lib/plans";
import type { ScreeningsFilters } from "@/app/protected/screenings/screenings-filters-model";
import { captureServer } from "@/lib/analytics/server";
import { PRELAUNCH_OPEN_ACCESS } from "@/lib/launch";
import { getTelegramStatus } from "@/lib/telegram/link";
import { sendTelegramMessage, escapeTelegramHtml } from "@/lib/telegram/send";
import { humanizeCron } from "@/lib/cron-format";

type ActionResult<T> = Promise<{ ok: true; data: T } | { ok: false; error: string }>;

const SCHEMA = "swingtrader";

const SCREENING_LIMITS: Record<PlanTier, number> = {
  observer: 0,
  investor: 5,
  trader: 25,
};

const SCHEDULE_GATES: Record<PlanTier, string> = {
  observer: "0 7 * * 1-5",
  investor: "0 */4 * * *",
  trader: "*/15 * * * *",
};

export type TradingSession = "none" | "nyse";

export type ScheduledScreening = {
  id: string;
  name: string;
  prompt: string;
  schedule: string;
  timezone: string;
  tickers: string[];
  linked_scan_run_ids: number[];
  linked_scan_sources: string[];
  scan_filters: ScreeningsFilters | null;
  trading_session: TradingSession | null;
  condition_enabled: boolean;
  trigger_condition: string | null;
  is_active: boolean;
  run_requested_at: string | null;
  last_run_at: string | null;
  last_triggered: boolean | null;
  created_at: string;
  updated_at: string;
};

export type ScreeningResultStatus = "running" | "done" | "error" | "skipped";

export type ScreeningResult = {
  id: string;
  screening_id: string;
  run_at: string;
  triggered: boolean;
  summary: string | null;
  data_used: Record<string, unknown> | null;
  is_test: boolean;
  delivered: boolean;
  status: ScreeningResultStatus | null;
  created_at: string;
};

export async function listScheduledScreenings(): ActionResult<
  ScheduledScreening[]
> {
  const supabase = await createClient();
  const { data: claims } = await supabase.auth.getClaims();
  const userId = claims?.claims?.sub;
  if (!userId) return { ok: false, error: "Not authenticated" };

  const { data, error } = await supabase
    .schema(SCHEMA)
    .from("user_scheduled_screenings")
    .select("*")
    .eq("user_id", userId)
    .order("created_at", { ascending: false });

  if (error) return { ok: false, error: error.message };
  return { ok: true, data: (data ?? []) as ScheduledScreening[] };
}

/** "market_screening:foo-bar" → "Foo Bar"; raw string for user-named sources. */
function formatSourceLabel(source: string): string {
  if (source.startsWith("market_screening:")) {
    return source
      .slice("market_screening:".length)
      .replace(/[-_]+/g, " ")
      .replace(/\b\w/g, (c) => c.toUpperCase())
      .trim();
  }
  return source;
}

/** HTML Telegram message describing a freshly-created agent. */
function buildAgentCreatedMessage(s: ScheduledScreening): string {
  const lines: string[] = [
    `🤖 <b>Agent created: ${escapeTelegramHtml(s.name)}</b>`,
    "",
    `🗓 ${escapeTelegramHtml(humanizeCron(s.schedule, s.timezone))}`,
  ];
  if (s.trading_session === "nyse") lines.push("🕘 Runs during NYSE hours only");
  if (s.tickers?.length) {
    lines.push(`📈 Tickers: ${s.tickers.map(escapeTelegramHtml).join(", ")}`);
  }
  if (s.linked_scan_sources?.length) {
    const labels = s.linked_scan_sources.map((src) => escapeTelegramHtml(formatSourceLabel(src)));
    lines.push(`🔗 Follows latest: ${labels.join(", ")}`);
  }
  if (s.linked_scan_run_ids?.length) {
    const n = s.linked_scan_run_ids.length;
    lines.push(`📌 ${n} pinned screening run${n === 1 ? "" : "s"}`);
  }
  if (s.condition_enabled && s.trigger_condition) {
    lines.push(`🎯 Only alerts when: <i>${escapeTelegramHtml(s.trigger_condition)}</i>`);
  } else {
    lines.push("🔔 Sends you an update on every run.");
  }
  lines.push("");
  lines.push("I'll watch this for you and message you here. Manage it anytime under Agents in the app.");
  return lines.join("\n");
}

/** Best-effort Telegram confirmation. Never throws — agent creation must not
 * depend on it. No-op when the user hasn't connected Telegram. */
async function sendAgentCreatedConfirmation(
  supabase: Awaited<ReturnType<typeof createClient>>,
  userId: string,
  screening: ScheduledScreening,
): Promise<void> {
  try {
    const tg = await getTelegramStatus(supabase, userId);
    if (tg.connected && tg.chat_id) {
      await sendTelegramMessage(tg.chat_id, buildAgentCreatedMessage(screening));
    }
  } catch (e) {
    console.error("[screenings-agent] agent-created Telegram confirmation failed", e);
  }
}

export async function createScheduledScreening(input: {
  name: string;
  prompt: string;
  schedule: string;
  timezone: string;
  tickers?: string[];
  linked_scan_run_ids?: number[];
  linked_scan_sources?: string[];
  scan_filters?: ScreeningsFilters | null;
  trading_session?: TradingSession | null;
  condition_enabled?: boolean;
  trigger_condition?: string | null;
}): ActionResult<ScheduledScreening> {
  const supabase = await createClient();
  const { data: claims } = await supabase.auth.getClaims();
  const userId = claims?.claims?.sub;
  if (!userId) return { ok: false, error: "Not authenticated" };

  const plan = await getUserPlanTier();
  const limit = SCREENING_LIMITS[plan];

  const { count, error: countErr } = await supabase
    .schema(SCHEMA)
    .from("user_scheduled_screenings")
    .select("*", { count: "exact", head: true })
    .eq("user_id", userId)
    .eq("is_active", true);

  if (countErr) return { ok: false, error: countErr.message };
  if ((count ?? 0) >= limit) {
    if (PRELAUNCH_OPEN_ACCESS) {
      captureServer(userId, "would_plan_limit_reached", {
        limit_type: "screenings_active",
        user_plan: plan,
        used: count ?? 0,
        limit,
      });
      captureServer(userId, "would_paywall_hit", {
        surface: "screenings_create",
        user_plan: plan,
        reason: "screenings_active_limit",
      });
    } else {
      captureServer(userId, "plan_limit_reached", {
        limit_type: "screenings_active",
        user_plan: plan,
        used: count ?? 0,
        limit,
      });
      captureServer(userId, "paywall_hit", {
        surface: "screenings_create",
        user_plan: plan,
        reason: "screenings_active_limit",
      });
      return {
        ok: false,
        error: `${plan} plan allows ${limit} active screenings. Upgrade for more.`,
      };
    }
  }

  const { data, error } = await supabase
    .schema(SCHEMA)
    .from("user_scheduled_screenings")
    .insert({
      user_id: userId,
      name: input.name,
      prompt: input.prompt,
      schedule: input.schedule,
      timezone: input.timezone,
      tickers: input.tickers ?? [],
      linked_scan_run_ids: input.linked_scan_run_ids ?? [],
      linked_scan_sources: input.linked_scan_sources ?? [],
      scan_filters: input.scan_filters ?? null,
      trading_session: input.trading_session ?? "none",
      condition_enabled: input.condition_enabled ?? false,
      trigger_condition: input.condition_enabled
        ? (input.trigger_condition ?? "").trim() || null
        : null,
    })
    .select("*")
    .single();

  if (error) return { ok: false, error: error.message };

  const created = data as ScheduledScreening;
  await sendAgentCreatedConfirmation(supabase, userId, created);
  return { ok: true, data: created };
}

export async function updateScheduledScreening(
  id: string,
  input: {
    name?: string;
    prompt?: string;
    schedule?: string;
    timezone?: string;
    tickers?: string[];
    linked_scan_run_ids?: number[];
    linked_scan_sources?: string[];
    scan_filters?: ScreeningsFilters | null;
    trading_session?: TradingSession | null;
    condition_enabled?: boolean;
    trigger_condition?: string | null;
    is_active?: boolean;
  }
): ActionResult<ScheduledScreening> {
  const supabase = await createClient();
  const { data: claims } = await supabase.auth.getClaims();
  const userId = claims?.claims?.sub;
  if (!userId) return { ok: false, error: "Not authenticated" };

  const patch: Record<string, unknown> = { ...input };
  if (input.condition_enabled !== undefined) {
    if (input.condition_enabled) {
      const cond = (input.trigger_condition ?? "").trim();
      patch.condition_enabled = true;
      patch.trigger_condition = cond.length > 0 ? cond : null;
    } else {
      patch.condition_enabled = false;
      patch.trigger_condition = null;
    }
  }

  const { data, error } = await supabase
    .schema(SCHEMA)
    .from("user_scheduled_screenings")
    .update(patch)
    .eq("id", id)
    .eq("user_id", userId)
    .select("*")
    .single();

  if (error) return { ok: false, error: error.message };
  return { ok: true, data: data as ScheduledScreening };
}

export async function toggleScreening(
  id: string,
  active: boolean
): ActionResult<ScheduledScreening> {
  return updateScheduledScreening(id, { is_active: active });
}

export async function deleteScheduledScreening(
  id: string
): ActionResult<{ deleted: true }> {
  const supabase = await createClient();
  const { data: claims } = await supabase.auth.getClaims();
  const userId = claims?.claims?.sub;
  if (!userId) return { ok: false, error: "Not authenticated" };

  const { error } = await supabase
    .schema(SCHEMA)
    .from("user_scheduled_screenings")
    .delete()
    .eq("id", id)
    .eq("user_id", userId);

  if (error) return { ok: false, error: error.message };
  return { ok: true, data: { deleted: true } };
}

export async function getScreeningResults(
  screeningId: string,
  limit = 20
): ActionResult<ScreeningResult[]> {
  const supabase = await createClient();
  const { data: claims } = await supabase.auth.getClaims();
  const userId = claims?.claims?.sub;
  if (!userId) return { ok: false, error: "Not authenticated" };

  const { data, error } = await supabase
    .schema(SCHEMA)
    .from("user_screening_results")
    .select("*")
    .eq("screening_id", screeningId)
    .eq("user_id", userId)
    .order("run_at", { ascending: false })
    .limit(limit);

  if (error) return { ok: false, error: error.message };
  return { ok: true, data: (data ?? []) as ScreeningResult[] };
}

export async function getScreeningLimits(): ActionResult<{
  limit: number;
  used: number;
  plan: PlanTier;
  minSchedule: string;
}> {
  const supabase = await createClient();
  const { data: claims } = await supabase.auth.getClaims();
  const userId = claims?.claims?.sub;
  if (!userId) return { ok: false, error: "Not authenticated" };

  const plan = await getUserPlanTier();
  const { count } = await supabase
    .schema(SCHEMA)
    .from("user_scheduled_screenings")
    .select("*", { count: "exact", head: true })
    .eq("user_id", userId)
    .eq("is_active", true);

  return {
    ok: true,
    data: {
      limit: PRELAUNCH_OPEN_ACCESS ? 999 : SCREENING_LIMITS[plan],
      used: count ?? 0,
      plan,
      minSchedule: PRELAUNCH_OPEN_ACCESS
        ? SCHEDULE_GATES.trader
        : SCHEDULE_GATES[plan],
    },
  };
}

export async function testRunScreening(
  screeningId: string
): Promise<{ ok: true; data: { requested: true } } | { ok: false; error: string }> {
  const supabase = await createClient();
  const { data: claims } = await supabase.auth.getClaims();
  const userId = claims?.claims?.sub;
  if (!userId) return { ok: false, error: "Not authenticated" };

  const { error } = await supabase
    .schema(SCHEMA)
    .from("user_scheduled_screenings")
    .update({ run_requested_at: new Date().toISOString() })
    .eq("id", screeningId)
    .eq("user_id", userId);

  if (error) return { ok: false, error: error.message };
  return { ok: true, data: { requested: true } };
}

export async function pollTestResult(
  screeningId: string
): Promise<
  { ok: true; data: ScreeningResult | null } | { ok: false; error: string }
> {
  const supabase = await createClient();
  const { data: claims } = await supabase.auth.getClaims();
  const userId = claims?.claims?.sub;
  if (!userId) return { ok: false, error: "Not authenticated" };

  const { data, error } = await supabase
    .schema(SCHEMA)
    .from("user_screening_results")
    .select("*")
    .eq("screening_id", screeningId)
    .eq("user_id", userId)
    .eq("is_test", true)
    .order("run_at", { ascending: false })
    .limit(1)
    .maybeSingle();

  if (error) return { ok: false, error: error.message };
  return { ok: true, data: (data as ScreeningResult) ?? null };
}

export type ScanRunSummary = {
  id: number;
  scan_date: string;
  source: string | null;
};

export async function listScanRuns(): Promise<
  { ok: true; data: ScanRunSummary[] } | { ok: false; error: string }
> {
  const supabase = await createClient();
  const { data: claims } = await supabase.auth.getClaims();
  const userId = claims?.claims?.sub;
  if (!userId) return { ok: false, error: "Not authenticated" };

  const { data, error } = await supabase
    .schema(SCHEMA)
    .from("user_scan_runs")
    .select("id, scan_date, source")
    .eq("user_id", userId)
    .eq("status", "active")
    .order("scan_date", { ascending: false })
    .limit(50);

  if (error) return { ok: false, error: error.message };
  return {
    ok: true,
    data: (data ?? []).map((r) => ({
      id: Number(r.id),
      scan_date: String(r.scan_date ?? ""),
      source: r.source != null ? String(r.source) : null,
    })),
  };
}

export type AgentScanRow = {
  symbol: string;
  rowData: Record<string, unknown>;
};

export async function listScanRowsForRuns(
  runIds: number[]
): Promise<{ ok: true; data: AgentScanRow[] } | { ok: false; error: string }> {
  if (runIds.length === 0) return { ok: true, data: [] };

  const supabase = await createClient();
  const { data: claims } = await supabase.auth.getClaims();
  const userId = claims?.claims?.sub;
  if (!userId) return { ok: false, error: "Not authenticated" };

  const [rowsResult, notesResult] = await Promise.all([
    supabase
      .schema(SCHEMA)
      .from("user_scan_rows")
      .select("id, symbol, row_data")
      .in("run_id", runIds)
      .eq("user_id", userId),
    supabase
      .schema(SCHEMA)
      .from("user_scan_row_notes")
      .select("scan_row_id, status, highlighted, comment, stage, priority, tags, metadata_json")
      .in("run_id", runIds)
      .eq("user_id", userId),
  ]);

  if (rowsResult.error) return { ok: false, error: rowsResult.error.message };

  const notesMap = new Map<number, NonNullable<typeof notesResult.data>[number]>();
  for (const n of notesResult.data ?? []) {
    notesMap.set(n.scan_row_id, n);
  }

  return {
    ok: true,
    data: (rowsResult.data ?? []).map((r) => {
      const note = notesMap.get(r.id as number);
      const rd: Record<string, unknown> = {
        ...((r.row_data as Record<string, unknown>) ?? {}),
      };
      if (note) {
        rd.__note_status = note.status ?? null;
        rd.__note_highlighted = !!note.highlighted;
        rd.__note_hasRowNote = !!note;
        rd.__note_comment = note.comment ?? null;
        rd.__note_stage = note.stage ?? null;
        rd.__note_priority = note.priority ?? null;
        rd.__note_tags = note.tags ?? [];
        const meta = note.metadata_json as Record<string, unknown> | null;
        rd.__note_activePosition = !!(meta?.activePosition);
      } else {
        rd.__note_status = null;
        rd.__note_highlighted = false;
        rd.__note_hasRowNote = false;
        rd.__note_comment = null;
        rd.__note_stage = null;
        rd.__note_priority = null;
        rd.__note_tags = [];
        rd.__note_activePosition = false;
      }
      return {
        symbol: String(r.symbol ?? ""),
        rowData: rd,
      };
    }),
  };
}
