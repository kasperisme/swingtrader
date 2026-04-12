import { NextRequest, NextResponse } from "next/server";
import { requireBearerApiKey, v1JsonError, v1OptionsResponse } from "@/lib/api-v1/bearer-auth";
import { appendScreeningRowsService } from "@/lib/api-v1/screenings-run-service";
import { SCREENINGS_V1_CORS, SCREENINGS_WRITE_SCOPE } from "@/lib/api-v1/screenings-api";

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

  const result = await appendScreeningRowsService(auth.key, runId, body);
  if (!result.ok) return v1JsonError(SCREENINGS_V1_CORS, result.message, result.status);

  return NextResponse.json(
    { data: result.data },
    { status: 201, headers: SCREENINGS_V1_CORS },
  );
}
