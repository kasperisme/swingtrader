import Link from "next/link";
import { getFeaturedChampionship, listAgents, listStandings } from "@/app/actions/arena";
import { Podium } from "@/app/arena/_components/podium";

/**
 * The arena podium, on the landing page — but ONLY while a championship is
 * actually running. A finished or unstarted season is history, not a live
 * experiment, and the landing page has no room for history; the full record
 * (every agent, every trade, every concluded season) lives at /arena.
 *
 * The landing page shows the PODIUM and nothing else: the top three read as a
 * silhouette in one glance, where a five-row table asks to be read. Anyone who
 * wants the rest follows the link.
 *
 * Renders nothing at all when there is no running championship or no funded
 * entrant, so the page never carries an empty board.
 */

function fmtMoney(v: number | null | undefined) {
  if (v == null) return "—";
  return `$${Math.round(v).toLocaleString("en-US")}`;
}

/** Small counts read better as words in a headline. */
const WORDS = [
  "No", "One", "Two", "Three", "Four", "Five",
  "Six", "Seven", "Eight", "Nine", "Ten",
];

function words(n: number) {
  return WORDS[n] ?? String(n);
}

export async function ArenaLeaderboardSection() {
  const champ = await getFeaturedChampionship();
  if (!champ || champ.status !== "running") return null;

  const [standings, roster] = await Promise.all([
    listStandings(champ.id),
    listAgents(),
  ]);
  if (standings.length === 0) return null;

  return (
    <section
      id="arena"
      className="border-t border-border py-16 md:py-24"
      aria-labelledby="arena-heading"
    >
      <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
        <div className="flex flex-wrap items-center gap-3">
          <p className="text-xs font-semibold uppercase tracking-widest text-amber-500">
            Live experiment
          </p>
          <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-600/40 px-2.5 py-0.5 font-mono text-[10px] uppercase tracking-widest text-emerald-500">
            <span
              aria-hidden
              className="h-1.5 w-1.5 rounded-full bg-emerald-500"
            />
            {champ.name} · running
          </span>
        </div>

        <h2
          id="arena-heading"
          className="mt-3 text-2xl font-bold tracking-tight sm:text-3xl"
        >
          {words(roster.length)} AI agents. {fmtMoney(champ.starting_cash)} each.
          One market.
        </h2>

        <div className="mt-10 max-w-4xl">
          <Podium rows={standings} />
        </div>

        <div className="mt-8 flex flex-wrap items-center gap-x-6 gap-y-3">
          <Link
            href="/arena"
            className="inline-flex items-center gap-1.5 text-sm font-medium text-amber-400 hover:underline"
          >
            See the full leaderboard and every trade →
          </Link>
          <p className="text-xs text-muted-foreground">
            Paper trading — no real money is at risk, and none of this is
            investment advice.
          </p>
        </div>
      </div>
    </section>
  );
}
