import { NextRequest, NextResponse } from "next/server";
import { createServiceClient } from "@/lib/supabase/service";
import { requireBearerApiKey, v1JsonError, v1OptionsResponse } from "@/lib/api-v1/bearer-auth";
import {
  parseCreateRunBody,
  SCREENINGS_V1_CORS,
  SCREENINGS_WRITE_SCOPE,
} from "@/lib/api-v1/screenings-api";

export async function OPTIONS() {
  return v1OptionsResponse(SCREENINGS_V1_CORS);
}

export async function POST(req: NextRequest) {
  const auth = await requireBearerApiKey(req, SCREENINGS_V1_CORS, [SCREENINGS_WRITE_SCOPE]);
  if (!auth.ok) return auth.response;

  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return v1JsonError(SCREENINGS_V1_CORS, "Invalid JSON body", 400);
  }

  const parsed = parseCreateRunBody(body);
  if (!parsed.ok) return v1JsonError(SCREENINGS_V1_CORS, parsed.message, 400);

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
      user_id: auth.key.userId,
    })
    .select("id, created_at, scan_date, source, market_json, result_json")
    .single();

  if (error) {
    return v1JsonError(SCREENINGS_V1_CORS, "Failed to create screening run", 500);
  }

  return NextResponse.json({ data }, { status: 201, headers: SCREENINGS_V1_CORS });
}
