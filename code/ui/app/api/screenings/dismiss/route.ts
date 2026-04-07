import { NextRequest, NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

// POST /api/screenings/dismiss
// {
//   scanRowId: number,
//   runId: number,
//   ticker: string,
//   status?: "active" | "dismissed" | "watchlist" | "pipeline",
//   highlighted?: boolean,
//   comment?: string | null
// }
export async function POST(req: NextRequest) {
  const { scanRowId, runId, ticker, status, highlighted, comment, metadataJson } = await req.json();
  if (!scanRowId || typeof scanRowId !== "number") {
    return NextResponse.json({ error: "scanRowId required" }, { status: 400 });
  }
  if (!runId || typeof runId !== "number") {
    return NextResponse.json({ error: "runId required" }, { status: 400 });
  }
  if (!ticker || typeof ticker !== "string") {
    return NextResponse.json({ error: "ticker required" }, { status: 400 });
  }

  const supabase = await createClient();
  const { error } = await supabase
    .schema("swingtrader")
    .from("scan_row_notes")
    .upsert({
      scan_row_id: scanRowId,
      run_id: runId,
      ticker,
      status: status ?? "active",
      highlighted: highlighted ?? false,
      comment: comment ?? null,
      metadata_json: metadataJson ?? {},
      updated_at: new Date().toISOString(),
    }, { onConflict: "scan_row_id" });

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ ok: true });
}

// DELETE /api/screenings/dismiss?scanRowId=123
export async function DELETE(req: NextRequest) {
  const scanRowId = req.nextUrl.searchParams.get("scanRowId");
  if (!scanRowId) return NextResponse.json({ error: "scanRowId required" }, { status: 400 });
  const parsedScanRowId = Number(scanRowId);
  if (!Number.isFinite(parsedScanRowId)) {
    return NextResponse.json({ error: "scanRowId must be a number" }, { status: 400 });
  }

  const supabase = await createClient();
  const { error } = await supabase
    .schema("swingtrader")
    .from("scan_row_notes")
    .update({
      status: "active",
      highlighted: false,
      comment: null,
      updated_at: new Date().toISOString(),
    })
    .eq("scan_row_id", parsedScanRowId);

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ ok: true });
}

// GET /api/screenings/dismiss?runId=10  → row annotations for a run
export async function GET(req: NextRequest) {
  const runId = req.nextUrl.searchParams.get("runId");
  if (!runId) return NextResponse.json({ error: "runId required" }, { status: 400 });
  const parsedRunId = Number(runId);
  if (!Number.isFinite(parsedRunId)) {
    return NextResponse.json({ error: "runId must be a number" }, { status: 400 });
  }

  const supabase = await createClient();
  const { data, error } = await supabase
    .schema("swingtrader")
    .from("scan_row_notes")
    .select("scan_row_id, run_id, ticker, status, highlighted, comment, stage, priority, tags, metadata_json, created_at, updated_at")
    .eq("run_id", parsedRunId)
    .order("updated_at", { ascending: false });

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data ?? []);
}
