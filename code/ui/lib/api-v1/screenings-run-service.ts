import { createServiceClient } from "@/lib/supabase/service";
import type { ValidatedKey } from "@/lib/api-auth";
import {
  parseAppendRowsBody,
  parseCreateRunBody,
  screeningRowsToDbRecords,
} from "@/lib/api-v1/screenings-api";

export type ScreeningServiceFailure = { ok: false; status: number; message: string };

export type CreateRunSuccess = {
  ok: true;
  data: {
    id: number;
    created_at: string;
    scan_date: string;
    source: string;
    market_json: unknown;
    result_json: unknown;
  };
};

export type CreateRunResult = CreateRunSuccess | ScreeningServiceFailure;

export async function createScreeningRunService(
  key: ValidatedKey,
  body: unknown,
): Promise<CreateRunResult> {
  const parsed = parseCreateRunBody(body);
  if (!parsed.ok) return { ok: false, status: 400, message: parsed.message };

  const { scan_date, source, market_json, result_json } = parsed.value;

  const supabase = createServiceClient();
  const { data, error } = await supabase
    .schema("swingtrader")
    .from("user_scan_runs")
    .insert({
      scan_date,
      source,
      market_json: market_json ?? null,
      result_json: result_json ?? null,
      user_id: key.userId,
    })
    .select("id, created_at, scan_date, source, market_json, result_json")
    .single();

  if (error) {
    return { ok: false, status: 500, message: "Failed to create screening run" };
  }

  return { ok: true, data: data as CreateRunSuccess["data"] };
}

export type AppendRowsSuccess = { ok: true; data: { inserted: number; ids: number[] } };

export type AppendRowsResult = AppendRowsSuccess | ScreeningServiceFailure;

export async function appendScreeningRowsService(
  key: ValidatedKey,
  runId: number,
  body: unknown,
): Promise<AppendRowsResult> {
  if (!Number.isFinite(runId) || runId < 1) {
    return { ok: false, status: 400, message: "'runId' must be a positive integer" };
  }

  const parsed = parseAppendRowsBody(body);
  if (!parsed.ok) return { ok: false, status: 400, message: parsed.message };

  const supabase = createServiceClient();

  const { data: run, error: runErr } = await supabase
    .schema("swingtrader")
    .from("user_scan_runs")
    .select("id, scan_date, user_id")
    .eq("id", runId)
    .maybeSingle();

  if (runErr) return { ok: false, status: 500, message: "Internal error" };
  if (run === null) return { ok: false, status: 404, message: "Screening run not found" };
  if (run.user_id !== key.userId) {
    return { ok: false, status: 403, message: "Forbidden: this run belongs to another user" };
  }

  const scanDate = String(run.scan_date).slice(0, 10);
  const records = screeningRowsToDbRecords(runId, scanDate, parsed.value, key);

  const { data: inserted, error: insErr } = await supabase
    .schema("swingtrader")
    .from("user_scan_rows")
    .insert(records)
    .select("id");

  if (insErr) {
    return { ok: false, status: 500, message: "Failed to insert screening rows" };
  }

  const ids = (inserted ?? []).map((r) => Number((r as { id: number }).id));

  return { ok: true, data: { inserted: ids.length, ids } };
}
