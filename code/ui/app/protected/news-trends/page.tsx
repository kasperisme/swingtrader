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
    </div>
  );
}
