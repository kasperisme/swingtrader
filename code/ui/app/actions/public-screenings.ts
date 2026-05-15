"use server";

import { headers } from "next/headers";
import { revalidatePath } from "next/cache";
import { createServiceClient } from "@/lib/supabase/service";
import { createClient } from "@/lib/supabase/server";
import { captureServer } from "@/lib/analytics/server";

const SCHEMA = "swingtrader";

export type PublicScreening = {
  id: string;
  slug: string;
  name: string;
  description: string | null;
  category: string | null;
  schedule: string;
  timezone: string;
  last_run_at: string | null;
  last_triggered: boolean | null;
  created_at: string;
  download_count: number;
  llm_prompt: string | null;
};

export type PublicScreeningResult = {
  id: string;
  run_at: string;
  triggered: boolean;
  summary: string | null;
  status: string;
};

export type PublicScreeningResultRow = {
  id: number;
  symbol: string | null;
  dataset: string;
  rowData: Record<string, unknown>;
  run_at: string;
  scan_date: string;
};

type ActionResult<T> = Promise<{ ok: true; data: T } | { ok: false; error: string }>;

// Fields known to exist after every migration is applied. download_count was
// added in 20260513010000 and we degrade gracefully if a deployment is ahead
// of the DB (column-missing error code 42703).
const PUBLIC_FIELDS_FULL =
  "id, slug, name, description, category, schedule, timezone, last_run_at, last_triggered, created_at, download_count, llm_prompt";
const PUBLIC_FIELDS_LEGACY =
  "id, slug, name, description, category, schedule, timezone, last_run_at, last_triggered, created_at";

// supabase-js puts error fields on a class instance whose own props aren't
// enumerable, so `console.error(error)` prints `{}`. Project to a plain object.
function describePgError(error: unknown): Record<string, unknown> {
  if (!error || typeof error !== "object") return { value: String(error) };
  const e = error as Record<string, unknown>;
  return {
    code: e.code,
    message: e.message,
    details: e.details,
    hint: e.hint,
  };
}

function isMissingColumnError(error: unknown): boolean {
  const e = error as { code?: string; message?: string } | null | undefined;
  return (
    e?.code === "42703" || /column .* does not exist/i.test(e?.message ?? "")
  );
}

const validEmail = (raw: string): boolean =>
  /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(raw.trim().toLowerCase());

// ── Reads (server-side, public) ─────────────────────────────────────────────

async function selectPublicScreeningsWithFallback(
  builder: (fields: string) => Promise<{ data: unknown; error: unknown }>,
): Promise<{ data: unknown; error: unknown }> {
  const first = await builder(PUBLIC_FIELDS_FULL);
  if (first.error && isMissingColumnError(first.error)) {
    console.warn(
      "[public-screenings] download_count missing — falling back. Apply migration 20260513010000.",
    );
    return builder(PUBLIC_FIELDS_LEGACY);
  }
  return first;
}

export async function listPublicScreenings(): Promise<PublicScreening[]> {
  const client = createServiceClient();
  const { data, error } = await selectPublicScreeningsWithFallback(
    (fields) =>
      client
        .schema(SCHEMA)
        .from("public_screenings")
        .select(fields)
        .eq("is_published", true)
        .order("created_at", { ascending: false }) as unknown as Promise<{
        data: unknown;
        error: unknown;
      }>,
  );

  if (error) {
    console.error("[public-screenings] list failed", describePgError(error));
    return [];
  }
  return ((data ?? []) as Partial<PublicScreening>[]).map((r) => ({
    download_count: 0,
    llm_prompt: null,
    ...r,
  })) as PublicScreening[];
}

export async function getPublicScreeningBySlug(
  slug: string,
): Promise<PublicScreening | null> {
  const client = createServiceClient();
  const { data, error } = await selectPublicScreeningsWithFallback(
    (fields) =>
      client
        .schema(SCHEMA)
        .from("public_screenings")
        .select(fields)
        .eq("slug", slug)
        .eq("is_published", true)
        .limit(1)
        .maybeSingle() as unknown as Promise<{
        data: unknown;
        error: unknown;
      }>,
  );

  if (error) {
    console.error("[public-screenings] getBySlug failed", describePgError(error));
    return null;
  }
  if (!data) return null;
  return {
    download_count: 0,
    llm_prompt: null,
    ...(data as Partial<PublicScreening>),
  } as PublicScreening;
}

function normalizeRowDataForTable(raw: unknown): Record<string, unknown> {
  if (raw && typeof raw === "object" && !Array.isArray(raw)) {
    return raw as Record<string, unknown>;
  }
  if (typeof raw === "string") {
    try {
      const p = JSON.parse(raw);
      if (p && typeof p === "object" && !Array.isArray(p)) {
        return p as Record<string, unknown>;
      }
    } catch {
      /* ignore */
    }
  }
  return {};
}

export async function getLatestPublicScreeningResultRows(
  screeningId: string,
): Promise<{
  resultId: string | null;
  runAt: string | null;
  rows: PublicScreeningResultRow[];
}> {
  const client = createServiceClient();

  // Latest done result for this screening.
  const { data: latestResult } = await client
    .schema(SCHEMA)
    .from("public_screening_results")
    .select("id, run_at, data_used")
    .eq("public_screening_id", screeningId)
    .eq("status", "done")
    .order("run_at", { ascending: false })
    .limit(1)
    .maybeSingle();

  if (!latestResult) {
    return { resultId: null, runAt: null, rows: [] };
  }

  // Primary path: read from public_screening_result_rows (the canonical
  // per-ticker table). May not exist yet for runs that pre-date that
  // migration — we fall back to data_used.symbols below.
  let parsed: PublicScreeningResultRow[] = [];
  try {
    const { data: rows, error } = await client
      .schema(SCHEMA)
      .from("public_screening_result_rows")
      .select("id, symbol, dataset, row_data, run_at, scan_date")
      .eq("result_id", latestResult.id)
      .order("id", { ascending: true });

    if (error) throw error;

    parsed = (rows ?? []).map((r) => ({
      id: Number((r as { id: number }).id),
      symbol: (r as { symbol: string | null }).symbol,
      dataset: String((r as { dataset: string }).dataset ?? ""),
      rowData: normalizeRowDataForTable((r as { row_data: unknown }).row_data),
      run_at: String((r as { run_at: string }).run_at ?? ""),
      scan_date: String((r as { scan_date: string }).scan_date ?? ""),
    }));
  } catch (e) {
    console.warn(
      "[public-screenings] public_screening_result_rows read failed, falling back",
      e,
    );
  }

  // Fallback: legacy runs stored the symbols list inside data_used. Project
  // those into the same shape so the UI doesn't have to special-case.
  if (parsed.length === 0) {
    const du = (latestResult as { data_used: unknown }).data_used;
    const duObj = normalizeRowDataForTable(du);
    const sym = duObj.symbols;
    if (Array.isArray(sym)) {
      parsed = sym.map((s, i) => {
        const obj = normalizeRowDataForTable(s);
        return {
          id: i + 1,
          symbol:
            (typeof obj.symbol === "string" && obj.symbol) ||
            (typeof obj.ticker === "string" && obj.ticker) ||
            null,
          dataset: "trend_template",
          rowData: obj,
          run_at: String(latestResult.run_at ?? ""),
          scan_date: String(latestResult.run_at ?? "").slice(0, 10),
        };
      });
    }
  }

  return {
    resultId: latestResult.id,
    runAt: latestResult.run_at,
    rows: parsed,
  };
}

export async function getPublicScreeningResults(
  screeningId: string,
  limit = 10,
): Promise<PublicScreeningResult[]> {
  const client = createServiceClient();
  const { data, error } = await client
    .schema(SCHEMA)
    .from("public_screening_results")
    .select("id, run_at, triggered, summary, status")
    .eq("public_screening_id", screeningId)
    .eq("status", "done")
    .order("run_at", { ascending: false })
    .limit(limit);
  if (error) {
    console.error("[public-screenings] getResults failed", error);
    return [];
  }
  return (data ?? []) as PublicScreeningResult[];
}

// ── Early access signup ─────────────────────────────────────────────────────

export async function submitEarlyAccessSignup(input: {
  email: string;
  screeningSlug: string;
  source?: string;
}): ActionResult<{ alreadySignedUp: boolean }> {
  const email = (input.email ?? "").trim().toLowerCase();
  if (!validEmail(email)) {
    return { ok: false, error: "Please enter a valid email address." };
  }

  const service = createServiceClient();

  // Resolve the screening (must exist and be published).
  const { data: screening } = await service
    .schema(SCHEMA)
    .from("public_screenings")
    .select("id, name")
    .eq("slug", input.screeningSlug)
    .eq("is_published", true)
    .limit(1)
    .maybeSingle();

  if (!screening) {
    return { ok: false, error: "Screening not found." };
  }

  // Best-effort: attach the current auth user if they have a session.
  let userId: string | null = null;
  try {
    const supabase = await createClient();
    const {
      data: { user },
    } = await supabase.auth.getUser();
    userId = user?.id ?? null;
  } catch {
    userId = null;
  }

  const headerList = await headers();
  const referrer = headerList.get("referer");
  const userAgent = headerList.get("user-agent");

  const insertRes = await service
    .schema(SCHEMA)
    .from("early_access_signups")
    .insert({
      email,
      public_screening_id: screening.id,
      user_id: userId,
      source: input.source || "gallery_subscribe",
      referrer,
      user_agent: userAgent,
    });

  // Duplicate is a success path from the user's perspective.
  if (insertRes.error) {
    const isDup =
      insertRes.error.code === "23505" ||
      /duplicate key/i.test(insertRes.error.message);
    if (!isDup) {
      console.error("[public-screenings] signup insert failed", insertRes.error);
      return { ok: false, error: "Could not record signup. Please try again." };
    }
    captureServer(userId ?? email, "early_access_signup_duplicate", {
      screening_id: screening.id,
      screening_slug: input.screeningSlug,
      source: input.source || "gallery_subscribe",
    });
    return { ok: true, data: { alreadySignedUp: true } };
  }

  captureServer(userId ?? email, "early_access_signup", {
    screening_id: screening.id,
    screening_slug: input.screeningSlug,
    screening_name: screening.name,
    source: input.source || "gallery_subscribe",
    authenticated: Boolean(userId),
  });

  return { ok: true, data: { alreadySignedUp: false } };
}

// ── Download metric ─────────────────────────────────────────────────────────

/**
 * Atomically bumps `download_count` for the screening and emits a PostHog
 * event. Called from the CSV export route. Best-effort: any failure is logged
 * but never blocks the download response.
 */
export async function recordPublicScreeningDownload(input: {
  screeningId: string;
  screeningSlug: string;
  screeningName: string;
}): Promise<void> {
  // Identify the caller (anonymous downloads are fine — we still want the
  // count + an anonymous PH event keyed by slug).
  let userId: string | null = null;
  try {
    const supabase = await createClient();
    const {
      data: { user },
    } = await supabase.auth.getUser();
    userId = user?.id ?? null;
  } catch {
    userId = null;
  }

  const service = createServiceClient();
  try {
    const { error } = await service
      .schema(SCHEMA)
      .rpc("increment_public_screening_download", {
        p_id: input.screeningId,
      });
    if (error) {
      console.error("[public-screenings] increment download failed", error);
    }
  } catch (e) {
    console.error("[public-screenings] increment download threw", e);
  }

  let referrer: string | null = null;
  try {
    const headerList = await headers();
    referrer = headerList.get("referer");
  } catch {
    referrer = null;
  }

  captureServer(userId ?? `anon:${input.screeningSlug}`, "public_screening_downloaded", {
    screening_id: input.screeningId,
    screening_slug: input.screeningSlug,
    screening_name: input.screeningName,
    format: "csv",
    authenticated: Boolean(userId),
    referrer,
  });
}

// ── Real subscriptions (authed users) ───────────────────────────────────────

export async function getMySubscriptionIds(): Promise<string[]> {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return [];

  const { data, error } = await supabase
    .schema(SCHEMA)
    .from("public_screening_subscriptions")
    .select("public_screening_id")
    .eq("user_id", user.id);

  if (error) {
    console.error(
      "[public-screenings] getMySubscriptionIds failed",
      describePgError(error),
    );
    return [];
  }
  return (data ?? []).map(
    (r: { public_screening_id: string }) => r.public_screening_id,
  );
}

export async function getMySubscription(
  screeningId: string,
): Promise<{ isSubscribed: boolean; notificationsEnabled: boolean }> {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return { isSubscribed: false, notificationsEnabled: false };

  const { data } = await supabase
    .schema(SCHEMA)
    .from("public_screening_subscriptions")
    .select("notifications_enabled")
    .eq("user_id", user.id)
    .eq("public_screening_id", screeningId)
    .limit(1)
    .maybeSingle();

  if (!data) return { isSubscribed: false, notificationsEnabled: false };
  return {
    isSubscribed: true,
    notificationsEnabled: Boolean(data.notifications_enabled),
  };
}

export async function subscribeToPublicScreening(
  screeningSlug: string,
): ActionResult<{ alreadySubscribed: boolean }> {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    return { ok: false, error: "You must be signed in to subscribe." };
  }

  const service = createServiceClient();
  const { data: screening } = await service
    .schema(SCHEMA)
    .from("public_screenings")
    .select("id, name")
    .eq("slug", screeningSlug)
    .eq("is_published", true)
    .limit(1)
    .maybeSingle();

  if (!screening) {
    return { ok: false, error: "Screening not found." };
  }

  // public_screening_subscriptions is the only subscription record we keep.
  // Public screenings are platform-managed; results land in user_scan_runs +
  // user_scan_rows + user_screening_results at execution time, not as a
  // user_scheduled_screenings row.
  const subRes = await supabase
    .schema(SCHEMA)
    .from("public_screening_subscriptions")
    .insert({
      user_id: user.id,
      public_screening_id: screening.id,
    });

  if (subRes.error) {
    const isDup =
      subRes.error.code === "23505" ||
      /duplicate key/i.test(subRes.error.message);
    if (!isDup) {
      console.error("[public-screenings] subscribe failed", subRes.error);
      return { ok: false, error: "Could not subscribe. Please try again." };
    }
    revalidatePath(`/screenings/${screeningSlug}`);
    return { ok: true, data: { alreadySubscribed: true } };
  }

  captureServer(user.id, "public_screening_subscribed", {
    screening_id: screening.id,
    screening_slug: screeningSlug,
    screening_name: screening.name,
  });

  revalidatePath(`/screenings/${screeningSlug}`);
  return { ok: true, data: { alreadySubscribed: false } };
}

/**
 * Mirror the Python public-screening fan-out for a single user. Used by the
 * post-subscribe "import latest results" prompt so a brand-new subscriber can
 * see the current state of the screening immediately instead of waiting for
 * the next scheduled run.
 *
 * Writes: user_scan_jobs + user_scan_runs + user_scan_rows. For every ticker
 * whose row_data has llm_analysis.analysis_markdown, also read-modify-write
 * upserts user_ticker_chart_workspace with a user+assistant pair tagged
 * source: "public_screening" (matches services/public_screenings/runner.py).
 */
export async function importLatestPublicScreeningResultForMe(
  screeningSlug: string,
): ActionResult<{
  imported: boolean;
  reason?: "no_results";
  runId: number | null;
  rowCount: number;
  chatTurns: number;
  runAt: string | null;
}> {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    return { ok: false, error: "You must be signed in." };
  }

  const service = createServiceClient();
  const { data: screening } = await service
    .schema(SCHEMA)
    .from("public_screenings")
    .select("id, name, slug, script_key, llm_prompt")
    .eq("slug", screeningSlug)
    .eq("is_published", true)
    .limit(1)
    .maybeSingle();

  if (!screening) {
    return { ok: false, error: "Screening not found." };
  }

  const screeningId = (screening as { id: string }).id;
  const scriptKey =
    (screening as { script_key: string | null }).script_key || "public_screening";
  const llmPrompt = (
    (screening as { llm_prompt: string | null }).llm_prompt || ""
  ).trim();

  // Latest done result for this screening.
  const { data: latestResult } = await service
    .schema(SCHEMA)
    .from("public_screening_results")
    .select("id, run_at, data_used, summary, triggered, status, is_test")
    .eq("public_screening_id", screeningId)
    .eq("status", "done")
    .order("run_at", { ascending: false })
    .limit(1)
    .maybeSingle();

  if (!latestResult) {
    return {
      ok: true,
      data: {
        imported: false,
        reason: "no_results",
        runId: null,
        rowCount: 0,
        chatTurns: 0,
        runAt: null,
      },
    };
  }

  const resultId = (latestResult as { id: string }).id;
  const runAt = (latestResult as { run_at: string | null }).run_at;
  const dataUsedRaw = (latestResult as { data_used: unknown }).data_used;
  const dataUsed = normalizeRowDataForTable(dataUsedRaw);

  // Per-ticker rows. Canonical source is public_screening_result_rows; we
  // fall back to data_used.symbols for legacy result rows that pre-date
  // that table.
  type RowPayload = { symbol: string | null; rowData: Record<string, unknown> };
  let rowPayloads: RowPayload[] = [];

  const { data: dbRows, error: dbRowsErr } = await service
    .schema(SCHEMA)
    .from("public_screening_result_rows")
    .select("symbol, row_data")
    .eq("result_id", resultId)
    .order("id", { ascending: true });

  if (dbRowsErr) {
    console.warn(
      "[public-screenings] import: result_rows read failed, falling back",
      describePgError(dbRowsErr),
    );
  } else if (dbRows && dbRows.length > 0) {
    rowPayloads = dbRows.map((r) => ({
      symbol: (r as { symbol: string | null }).symbol,
      rowData: normalizeRowDataForTable((r as { row_data: unknown }).row_data),
    }));
  }

  if (rowPayloads.length === 0) {
    const sym = dataUsed.symbols;
    if (Array.isArray(sym)) {
      rowPayloads = sym
        .map((s) => normalizeRowDataForTable(s))
        .map((obj) => ({
          symbol:
            (typeof obj.symbol === "string" && obj.symbol) ||
            (typeof obj.ticker === "string" && obj.ticker) ||
            null,
          rowData: obj,
        }));
    }
  }

  const nowIso = new Date().toISOString();
  const scanDateStr = nowIso.slice(0, 10);
  const sourceLabel = `public_screening:${screeningSlug}`;
  const scriptRel = `services/public_screenings/scripts/${scriptKey}.py`;

  // 1. user_scan_jobs — job metadata. RLS expects auth.uid() = user_id.
  await supabase
    .schema(SCHEMA)
    .from("user_scan_jobs")
    .insert({
      started_at: nowIso,
      finished_at: nowIso,
      status: "completed",
      scan_source: scriptKey,
      script_rel: scriptRel,
      args_json: JSON.stringify([]),
      stdout_log: "",
      stderr_log: "",
      exit_code: 0,
      error_message: null,
      user_id: user.id,
    });

  // 2. user_scan_runs — scan instance. Surfaces in /protected/screenings.
  const dataUsedWithSymbols: Record<string, unknown> = { ...dataUsed };
  if (!Array.isArray(dataUsedWithSymbols.symbols)) {
    dataUsedWithSymbols.symbols = rowPayloads.map((p) => p.rowData);
  }
  const { data: runIns, error: runErr } = await supabase
    .schema(SCHEMA)
    .from("user_scan_runs")
    .insert({
      scan_date: scanDateStr,
      source: sourceLabel,
      status: "active",
      market_json: null,
      result_json: JSON.stringify(dataUsedWithSymbols),
      user_id: user.id,
    })
    .select("id")
    .limit(1)
    .maybeSingle();

  if (runErr || !runIns) {
    console.error(
      "[public-screenings] import: user_scan_runs insert failed",
      describePgError(runErr),
    );
    return { ok: false, error: "Could not import results. Please try again." };
  }

  const runId = (runIns as { id: number }).id;

  // 3. user_scan_rows — per-ticker payload (dataset = script_key matches the
  // /protected/screenings filter).
  let rowCount = 0;
  if (rowPayloads.length > 0) {
    const rowsToInsert = rowPayloads.map((p) => ({
      run_id: runId,
      scan_date: scanDateStr,
      dataset: scriptKey,
      symbol: p.symbol,
      row_data: p.rowData,
      user_id: user.id,
    }));
    const { error: rowsErr } = await supabase
      .schema(SCHEMA)
      .from("user_scan_rows")
      .insert(rowsToInsert);
    if (rowsErr) {
      console.error(
        "[public-screenings] import: user_scan_rows insert failed",
        describePgError(rowsErr),
      );
    } else {
      rowCount = rowsToInsert.length;
    }
  }

  // 4. Chart workspace chat turns. Per ticker, append one user+assistant pair
  // tagged source: "public_screening", mirroring runner.py's fan-out.
  let chatTurns = 0;
  if (llmPrompt) {
    const userMessage = llmPrompt || "Run a technical analysis.";
    for (const { symbol, rowData } of rowPayloads) {
      const sym = (symbol || "").trim().toUpperCase();
      if (!sym) continue;
      const llm = rowData.llm_analysis;
      const analysisMarkdown =
        llm && typeof llm === "object" && !Array.isArray(llm)
          ? (llm as Record<string, unknown>).analysis_markdown
          : null;
      if (typeof analysisMarkdown !== "string" || !analysisMarkdown.trim()) {
        continue;
      }

      try {
        const { data: existing } = await supabase
          .schema(SCHEMA)
          .from("user_ticker_chart_workspace")
          .select("ai_chat_messages, annotations")
          .eq("user_id", user.id)
          .eq("ticker", sym)
          .limit(1)
          .maybeSingle();

        const messages: unknown[] = Array.isArray(
          (existing as { ai_chat_messages?: unknown })?.ai_chat_messages,
        )
          ? [
              ...((existing as { ai_chat_messages: unknown[] }).ai_chat_messages),
            ]
          : [];
        const annotations: unknown[] = Array.isArray(
          (existing as { annotations?: unknown })?.annotations,
        )
          ? [...((existing as { annotations: unknown[] }).annotations)]
          : [];

        messages.push({
          role: "user",
          content: userMessage,
          source: "public_screening",
        });
        messages.push({
          role: "assistant",
          content: analysisMarkdown,
          chartAnnotations: [],
          personaReports: [],
          source: "public_screening",
        });

        const { error: wsErr } = await supabase
          .schema(SCHEMA)
          .from("user_ticker_chart_workspace")
          .upsert(
            {
              user_id: user.id,
              ticker: sym,
              annotations,
              ai_chat_messages: messages,
              updated_at: nowIso,
            },
            { onConflict: "user_id,ticker" },
          );
        if (wsErr) {
          console.warn(
            "[public-screenings] import: chart workspace upsert failed",
            sym,
            describePgError(wsErr),
          );
        } else {
          chatTurns += 1;
        }
      } catch (e) {
        console.warn(
          "[public-screenings] import: chart workspace threw",
          sym,
          e,
        );
      }
    }
  }

  captureServer(user.id, "public_screening_imported_latest", {
    screening_id: screeningId,
    screening_slug: screeningSlug,
    screening_name: (screening as { name: string }).name,
    result_id: resultId,
    row_count: rowCount,
    chat_turns: chatTurns,
  });

  revalidatePath(`/screenings/${screeningSlug}`);
  revalidatePath("/protected/screenings");

  return {
    ok: true,
    data: {
      imported: true,
      runId,
      rowCount,
      chatTurns,
      runAt,
    },
  };
}

export async function unsubscribeFromPublicScreening(
  screeningSlug: string,
): ActionResult<{ removed: boolean }> {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    return { ok: false, error: "You must be signed in." };
  }

  const service = createServiceClient();
  const { data: screening } = await service
    .schema(SCHEMA)
    .from("public_screenings")
    .select("id")
    .eq("slug", screeningSlug)
    .limit(1)
    .maybeSingle();

  if (!screening) {
    return { ok: false, error: "Screening not found." };
  }

  const del = await supabase
    .schema(SCHEMA)
    .from("public_screening_subscriptions")
    .delete()
    .eq("user_id", user.id)
    .eq("public_screening_id", screening.id);

  if (del.error) {
    console.error("[public-screenings] unsubscribe failed", del.error);
    return { ok: false, error: "Could not unsubscribe. Please try again." };
  }

  captureServer(user.id, "public_screening_unsubscribed", {
    screening_id: screening.id,
    screening_slug: screeningSlug,
  });

  revalidatePath(`/screenings/${screeningSlug}`);
  return { ok: true, data: { removed: true } };
}
