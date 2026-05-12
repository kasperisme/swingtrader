import { Suspense } from "react";
import { getOnboardingTours } from "@/app/actions/onboarding";
import { PageTour } from "@/app/protected/_components/page-tour";
import { NewsTrendsHeatmapClient } from "./news-trends-heatmap-client";

async function NewsTrendsTourMount() {
  const tours = await getOnboardingTours();
  return <PageTour tourKey="news_trends" autoStart={!tours.news_trends} />;
}

export default function NewsTrendsPage() {
  return (
    <div className="flex w-full min-w-0 flex-col gap-3 py-1">
      <div className="shrink-0 flex items-baseline justify-between gap-2 px-1">
        <h1 className="text-[10px] font-medium font-mono uppercase tracking-[0.1em] text-muted-foreground/50">
          News Trends
        </h1>
        <span className="text-[10px] font-mono tabular-nums text-muted-foreground/30">
          IMPACT · HEATMAP
        </span>
      </div>

      <NewsTrendsHeatmapClient />

      <Suspense fallback={null}>
        <NewsTrendsTourMount />
      </Suspense>
    </div>
  );
}
