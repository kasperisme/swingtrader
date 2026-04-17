import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import {
  loadNewsTrendsDailySupplement,
  loadNewsTrendsDimensionDaily,
  loadNewsTrendsDimensionHourly,
  loadNewsTrendsHourlySupplement,
} from "@/lib/news-trends/load-news-trends";

const PART_VALUES = [
  "daily",
  "hourly",
  "dimension-daily",
  "dimension-hourly",
] as const;

export async function GET(request: NextRequest) {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const part = request.nextUrl.searchParams.get("part") ?? "daily";
  if (!PART_VALUES.includes(part as (typeof PART_VALUES)[number])) {
    return NextResponse.json(
      {
        error: "`part` must be `daily`, `hourly`, `dimension-daily`, or `dimension-hourly`",
      },
      { status: 400 },
    );
  }

  const body =
    part === "hourly"
      ? await loadNewsTrendsHourlySupplement(supabase)
      : part === "dimension-daily"
        ? await loadNewsTrendsDimensionDaily(supabase)
        : part === "dimension-hourly"
          ? await loadNewsTrendsDimensionHourly(supabase)
          : await loadNewsTrendsDailySupplement(supabase);
  return NextResponse.json(body);
}
