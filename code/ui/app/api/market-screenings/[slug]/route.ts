import { NextResponse } from "next/server";
import {
  getLatestMarketScreeningResultRows,
  getMarketScreeningBySlug,
} from "@/app/actions/market-screenings";

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
};

export async function OPTIONS() {
  return new NextResponse(null, { status: 204, headers: CORS_HEADERS });
}

export async function GET(
  _req: Request,
  ctx: { params: Promise<{ slug: string }> },
) {
  const { slug } = await ctx.params;

  const screening = await getMarketScreeningBySlug(slug);
  if (!screening) {
    return NextResponse.json(
      { error: "Screening not found" },
      { status: 404, headers: CORS_HEADERS },
    );
  }

  const { resultId, runAt, rows } =
    await getLatestMarketScreeningResultRows(screening.id);

  return NextResponse.json(
    {
      screening: {
        slug: screening.slug,
        name: screening.name,
        description: screening.description,
        category: screening.category,
        schedule: screening.schedule,
        timezone: screening.timezone,
        last_run_at: screening.last_run_at,
        last_triggered: screening.last_triggered,
      },
      run: {
        result_id: resultId,
        run_at: runAt,
        row_count: rows.length,
      },
      rows: rows.map((r) => ({
        id: r.id,
        symbol: r.symbol,
        dataset: r.dataset,
        scan_date: r.scan_date,
        run_at: r.run_at,
        row_data: r.rowData,
      })),
    },
    {
      status: 200,
      headers: {
        ...CORS_HEADERS,
        "Cache-Control": "public, max-age=60, stale-while-revalidate=300",
      },
    },
  );
}
