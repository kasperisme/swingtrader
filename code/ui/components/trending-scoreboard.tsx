import { getTrendingBoard } from "@/lib/trends";
import { TrendingScoreboardView } from "./trending-scoreboard-view";

export function TrendingScoreboardSkeleton() {
  return (
    <section className="rounded-2xl border border-border/60 bg-card/30 p-5 sm:p-6">
      <div className="mb-5 flex items-center justify-between">
        <div className="h-3 w-32 animate-pulse rounded bg-muted/60" />
        <div className="h-6 w-48 animate-pulse rounded-lg bg-muted/50" />
      </div>
      <div className="grid gap-8 md:grid-cols-2">
        {[0, 1].map((c) => (
          <div key={c} className="space-y-3">
            {[0, 1, 2, 3, 4, 5].map((r) => (
              <div key={r} className="h-6 w-full animate-pulse rounded bg-muted/40" />
            ))}
          </div>
        ))}
      </div>
    </section>
  );
}

/**
 * "Trending now" scoreboard — top tickers + theme tags over a rolling window,
 * filterable by Most mentions / Most growth / New. Fetches the (cached) board
 * server-side and hands it to a client view that switches filters with no
 * refetch. Renders nothing when there's no data.
 */
export async function TrendingScoreboard({
  windowDays = 7,
  limit = 20,
  collapsed = 6,
}: {
  windowDays?: number;
  /** How many rows to fetch per column/mode (the expanded ceiling). */
  limit?: number;
  /** How many rows to show before the user expands. */
  collapsed?: number;
}) {
  const board = await getTrendingBoard({ windowDays, limit });
  const total =
    board.tickers.mentions.length +
    board.tickers.growth.length +
    board.tickers.new.length +
    board.tags.mentions.length +
    board.tags.growth.length +
    board.tags.new.length;
  if (total === 0) return null;

  return (
    <TrendingScoreboardView board={board} windowDays={windowDays} collapsed={collapsed} />
  );
}
