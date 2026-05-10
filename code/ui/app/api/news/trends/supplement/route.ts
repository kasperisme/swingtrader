import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import {
  loadNewsTrendsDailySupplement,
  loadNewsTrendsDimensionDaily,
  loadNewsTrendsDimensionHourly,
  loadNewsTrendsHourlySupplement,
} from "@/lib/news-trends/load-news-trends";
import {
  getUserSubscriptionTier,
} from "@/lib/subscription";
import { computeNewsTrendsGate } from "@/lib/gate";
import { captureServer } from "@/lib/analytics/server";
import { PRELAUNCH_OPEN_ACCESS } from "@/lib/launch";

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
        error:
          "`part` must be `daily`, `hourly`, `dimension-daily`, or `dimension-hourly`",
      },
      { status: 400 },
    );
  }

  const tier = await getUserSubscriptionTier(supabase);
  const intendedGate = computeNewsTrendsGate(tier);

  if (intendedGate.enabled) {
    captureServer(
      user.id,
      PRELAUNCH_OPEN_ACCESS
        ? "would_news_trends_gate_applied"
        : "news_trends_gate_applied",
      {
        user_plan: tier,
        upgrade_plan: intendedGate.upgradePlan,
        restriction_days: intendedGate.restrictionDays,
        part,
      },
    );
  }

  const gate = PRELAUNCH_OPEN_ACCESS
    ? { ...intendedGate, enabled: false, fromGte: null }
    : intendedGate;
  const fromGte = gate.enabled ? gate.fromGte : null;

  const body =
    part === "hourly"
      ? await loadNewsTrendsHourlySupplement(supabase, fromGte)
      : part === "dimension-daily"
        ? await loadNewsTrendsDimensionDaily(supabase, fromGte)
        : part === "dimension-hourly"
          ? await loadNewsTrendsDimensionHourly(supabase, fromGte)
          : await loadNewsTrendsDailySupplement(supabase, fromGte);
  return NextResponse.json({ ...body, gate });
}
