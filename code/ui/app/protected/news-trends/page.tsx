import { createClient } from "@/lib/supabase/server";
import { getUserSubscriptionTier } from "@/lib/subscription";
import { computeNewsTrendsGate } from "@/lib/gate";
import { loadClusterDailyTrends } from "@/lib/news-trends/load-news-trends";
import { NewsTrendsClient } from "./news-trends-client";
import type { TimeGate } from "@/lib/gate";

export default async function NewsTrendsPage() {
  const supabase = await createClient();

  const tier = await getUserSubscriptionTier(supabase);
  const gate: TimeGate = computeNewsTrendsGate(tier);

  // Pass gate window so only the allowed date range is fetched from the DB.
  const clusterDaily = await loadClusterDailyTrends(supabase, gate.fromGte);

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

      <NewsTrendsClient
        clusterDaily={clusterDaily}
        gate={gate}
        tier={tier}
      />
    </div>
  );
}
