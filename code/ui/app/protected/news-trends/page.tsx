import { Suspense } from "react";
import { createClient } from "@/lib/supabase/server";
import { loadClusterDailyTrends } from "@/lib/news-trends/load-news-trends";
import { NewsTrendsClient } from "./news-trends-client";

async function TrendsData() {
  const supabase = await createClient();
  const clusterDaily = await loadClusterDailyTrends(supabase);
  return <NewsTrendsClient clusterDaily={clusterDaily} />;
}

export default function NewsTrendsPage() {
  return (
    <div className="flex-1 w-full flex flex-col gap-6">
      <div>
        <p className="text-xs font-semibold uppercase tracking-widest text-amber-500">Narrative momentum</p>
        <h1 className="mt-1 text-2xl font-bold tracking-tight">News Dimension Trends</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Moving average of news impact scores across dimension clusters — track
          what narratives are gaining or losing momentum. Series use UTC buckets from
          aggregate views; the chart labels them in your local timezone.
        </p>
      </div>

      <Suspense
        fallback={
          <div className="text-sm text-muted-foreground animate-pulse">
            Loading trends…
          </div>
        }
      >
        <TrendsData />
      </Suspense>
    </div>
  );
}
