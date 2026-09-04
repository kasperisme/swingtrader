import Link from "next/link";
import { getFeaturedChampionship, listAgents, listStandings } from "@/app/actions/arena";
import { ARENA_COLOR_INDEX } from "@/lib/arena/colors";

/**
 * The arena standings, on the landing page — but ONLY while a championship is
 * actually running. A finished or unstarted season is history, not a live
 * experiment, and the landing page has no room for history; the full record
 * (including every concluded season) lives at /arena.
 *
 * Renders nothing at all when there is no running championship or no funded
 * entrant, so the page never carries an empty board.
 */

const TOP_N = 5;

function fmtMoney(v: number | null | undefined) {
  if (v == null) return "—";
  return `$${Math.round(v).toLocaleString("en-US")}`;
}

function fmtPct(v: number | null | undefined) {
  if (v == null) return "—";
  return `${v >= 0 ? "+" : ""}${(v * 100).toFixed(2)}%`;
}

function toneFor(v: number | null | undefined) {
  if (v == null) return "text-muted-foreground";
  if (v > 0) return "text-emerald-500";
  if (v < 0) return "text-rose-500";
  return "text-muted-foreground";
}

/** Small counts read better as words in a headline. */
const WORDS = [
  "No", "One", "Two", "Three", "Four", "Five",
  "Six", "Seven", "Eight", "Nine", "Ten",
];

function words(n: number) {
  return WORDS[n] ?? String(n);
}

function fmtDate(iso: string | null) {
  if (!iso) return "—";
  return new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  });
}

export async function ArenaLeaderboardSection() {
  const champ = await getFeaturedChampionship();
  if (!champ || champ.status !== "running") return null;

  const [standings, roster] = await Promise.all([
    listStandings(champ.id),
    listAgents(),
  ]);
  if (standings.length === 0) return null;

  const rows = standings.slice(0, TOP_N);
  const asOf =
    standings.map((s) => s.as_of).filter(Boolean).sort().at(-1) ?? null;
  // Before the first close every agent sits at its funding NAV. Ranking that is
  // theatre, so the board says what it actually is instead.
  const marked = standings.some(
    (s) => (s.nav_days ?? 0) > 0 || (s.filled_orders ?? 0) > 0,
  );

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
        <p className="mt-3 max-w-2xl text-sm leading-6 text-muted-foreground">
          Same model, same broker, same risk limits — the only thing that differs
          is which slice of our data each agent can see. Two of them are dumb
          controls (buy the index, and pick at random) so the leaderboard has
          something to beat. Every trade and every reason is published.
        </p>

        <div className="mt-10 max-w-4xl overflow-x-auto rounded-2xl border border-border bg-background/60">
          <table className="w-full min-w-[520px] border-collapse text-sm">
            <caption className="sr-only">
              Top {TOP_N} agents in {champ.name}, ranked by total return.
            </caption>
            <thead>
              <tr className="border-b border-border text-left font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
                <th scope="col" className="py-3 pl-5 pr-3 text-right font-normal">
                  #
                </th>
                <th scope="col" className="py-3 pr-4 font-normal">
                  Agent
                </th>
                <th scope="col" className="py-3 pr-4 text-right font-normal">
                  NAV
                </th>
                <th scope="col" className="py-3 pr-5 text-right font-normal">
                  Return
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => {
                const colorIndex = ARENA_COLOR_INDEX[r.slug] ?? null;
                const isControl = r.engine === "deterministic";
                return (
                  <tr
                    key={r.slug}
                    className="border-b border-border/60 last:border-b-0 transition-colors hover:bg-amber-500/5"
                  >
                    <td className="py-3 pl-5 pr-3 text-right font-mono text-xs text-muted-foreground">
                      {i + 1}
                    </td>
                    <td className="py-3 pr-4">
                      <Link
                        href={`/arena/${r.slug}`}
                        className="group flex items-center gap-2.5"
                      >
                        <span
                          aria-hidden
                          className="h-2.5 w-2.5 shrink-0 rounded-full"
                          // Hollow ring for the controls — they are the
                          // baseline, not a competing series.
                          style={{
                            backgroundColor: isControl
                              ? "transparent"
                              : `hsl(var(--arena-${colorIndex}))`,
                            boxShadow: isControl
                              ? "inset 0 0 0 1.5px hsl(var(--muted-foreground))"
                              : undefined,
                          }}
                        />
                        <span className="min-w-0">
                          <span className="block font-medium leading-tight transition-colors group-hover:text-amber-400">
                            {r.name}
                          </span>
                          {isControl ? (
                            <span className="mt-0.5 block font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
                              control · no LLM
                            </span>
                          ) : (
                            r.tagline && (
                              <span className="mt-0.5 hidden max-w-[40ch] truncate text-xs leading-snug text-muted-foreground sm:block">
                                {r.tagline}
                              </span>
                            )
                          )}
                        </span>
                      </Link>
                    </td>
                    <td className="py-3 pr-4 text-right font-mono tabular-nums text-muted-foreground">
                      {fmtMoney(r.nav)}
                    </td>
                    <td
                      className={`py-3 pr-5 text-right font-mono font-medium tabular-nums ${toneFor(r.total_return)}`}
                    >
                      {fmtPct(r.total_return)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <p className="mt-4 text-xs leading-6 text-muted-foreground">
          {marked
            ? `${standings.length} ${standings.length === 1 ? "entrant" : "entrants"} · as of ${fmtDate(asOf)}. Paper trading — no real money is at risk, and none of this is investment advice.`
            : `${standings.length} ${standings.length === 1 ? "entrant" : "entrants"} funded on ${fmtDate(champ.starts_on)}, waiting on the first close. Paper trading — no real money is at risk, and none of this is investment advice.`}
        </p>

        <div className="mt-8">
          <Link
            href="/arena"
            className="inline-flex items-center gap-1.5 text-sm font-medium text-amber-400 hover:underline"
          >
            See the full leaderboard and every trade →
          </Link>
        </div>
      </div>
    </section>
  );
}
