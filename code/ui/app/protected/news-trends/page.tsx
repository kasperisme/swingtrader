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
    <div
      className="flex w-full min-w-0 overflow-x-hidden flex-col gap-3"
      style={{
        height: "calc(100dvh - 5rem)",
        marginTop: "-2rem",
        marginBottom: "-2rem",
        paddingTop: "1rem",
        paddingBottom: "1rem",
      }}
    >
      <h1 className="shrink-0 text-sm font-semibold uppercase tracking-widest text-muted-foreground/50">News Trends</h1>

      <NewsTrendsClient
        clusterDaily={clusterDaily}
        gate={gate}
        tier={tier}
      />
    </div>
  );
}
