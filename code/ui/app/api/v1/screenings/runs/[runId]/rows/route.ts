import { NextRequest, NextResponse } from "next/server";
import { createServiceClient } from "@/lib/supabase/service";
import { requireBearerApiKey, v1JsonError, v1OptionsResponse } from "@/lib/api-v1/bearer-auth";
import {
  parseAppendRowsBody,
  screeningRowsToDbRecords,
  SCREENINGS_V1_CORS,
  SCREENINGS_WRITE_SCOPE,
} from "@/lib/api-v1/screenings-api";

export async function OPTIONS() {
  return v1OptionsResponse(SCREENINGS_V1_CORS);
}

export async function POST(
  req: NextRequest,
  ctx: { params: Promise<{ runId: string }> },
) {
  const auth = await requireBearerApiKey(req, SCREENINGS_V1_CORS, [SCREENINGS_WRITE_SCOPE]);
  if (!auth.ok) return auth.response;

  const { runId: runIdParam } = await ctx.params;
  if (!/^\d{1,19}$/.test(runIdParam)) {
    return v1JsonError(SCREENINGS_V1_CORS, "'runId' must be a positive integer", 400);
  }
  const runId = parseInt(runIdParam, 10);

  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return v1JsonError(SCREENINGS_V1_CORS, "Invalid JSON body", 400);
  }

  const parsed = parseAppendRowsBody(body);
  if (!parsed.ok) return v1JsonError(SCREENINGS_V1_CORS, parsed.message, 400);

  const supabase = createServiceClient();

  const { data: run, error: runErr } = await supabase
    .schema("swingtrader")
    .from("user_scan_runs")
    .select("id, scan_date, user_id")
    .eq("id", runId)
    .maybeSingle();

  if (runErr) return v1JsonError(SCREENINGS_V1_CORS, "Internal error", 500);
  if (run === null) {
    return v1JsonError(SCREENINGS_V1_CORS, "Screening run not found", 404);
  }
  if (run.user_id !== auth.key.userId) {
    return v1JsonError(SCREENINGS_V1_CORS, "Forbidden: this run belongs to another user", 403);
  }

  const scanDate = String(run.scan_date).slice(0, 10);
  const records = screeningRowsToDbRecords(runId, scanDate, parsed.value, auth.key);

  const { data: inserted, error: insErr } = await supabase
    .schema("swingtrader")
    .from("user_scan_rows")
    .insert(records)
    .select("id");

  if (insErr) {
    return v1JsonError(SCREENINGS_V1_CORS, "Failed to insert screening rows", 500);
  }

  const ids = (inserted ?? []).map((r) => Number((r as { id: number }).id));

  return NextResponse.json(
    { data: { inserted: ids.length, ids } },
    { status: 201, headers: SCREENINGS_V1_CORS },
  );
}
