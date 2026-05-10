import { Suspense } from "react";
import { createClient } from "@/lib/supabase/server";
import { getUserSubscriptionTier } from "@/lib/subscription";
import { computeNewsTrendsGate } from "@/lib/gate";
import { loadClusterDailyTrends } from "@/lib/news-trends/load-news-trends";
import { NewsTrendsClient } from "./news-trends-client";
import type { TimeGate } from "@/lib/gate";
import { getOnboardingTours } from "@/app/actions/onboarding";
import { PageTour } from "@/app/protected/_components/page-tour";
import { captureServer } from "@/lib/analytics/server";
import { PRELAUNCH_OPEN_ACCESS } from "@/lib/launch";

async function NewsTrendsTourMount() {
  const tours = await getOnboardingTours();
  return <PageTour tourKey="news_trends" autoStart={!tours.news_trends} />;
}

export default async function NewsTrendsPage() {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  const tier = await getUserSubscriptionTier(supabase);
  const intendedGate: TimeGate = computeNewsTrendsGate(tier);

  if (intendedGate.enabled && user) {
    captureServer(
      user.id,
      PRELAUNCH_OPEN_ACCESS
        ? "would_news_trends_gate_applied"
        : "news_trends_gate_applied",
      {
        user_plan: tier,
        upgrade_plan: intendedGate.upgradePlan,
        restriction_days: intendedGate.restrictionDays,
        part: "page_load",
      },
    );
  }

  const gate: TimeGate = PRELAUNCH_OPEN_ACCESS
    ? { ...intendedGate, enabled: false, fromGte: null }
    : intendedGate;

  // Pass gate window so only the allowed date range is fetched from the DB.
  const clusterDaily = await loadClusterDailyTrends(supabase, gate.fromGte);

  return (
    <div className="flex w-full min-w-0 flex-col gap-3 py-1">
      <div className="shrink-0 flex items-baseline justify-between gap-2 px-1">
        <h1 className="text-[10px] font-medium font-mono uppercase tracking-[0.1em] text-muted-foreground/50">News Trends</h1>
        <span className="text-[10px] font-mono tabular-nums text-muted-foreground/30">IMPACT · CLUSTERS</span>
      </div>

      <NewsTrendsClient
        clusterDaily={clusterDaily}
        gate={gate}
        tier={tier}
      />
      <Suspense fallback={null}>
        <NewsTrendsTourMount />
      </Suspense>
    </div>
  );
}
