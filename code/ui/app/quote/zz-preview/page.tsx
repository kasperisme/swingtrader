// TEMPORARY: renders the priced-in panel from a `priced-in/3` fixture so the new
// per-driver deep dive can be looked at without publishing a row. Delete after.
import { PricedInPanel } from "@/app/quote/[symbol]/_components/priced-in-panel";
import { parseDrivers, parseParts } from "@/lib/quote/priced-in-vote";
import fixture from "@/__tests__/fixtures/priced-in-driver-cases.json";

export default function Page() {
  const f = fixture as never as {
    drivers: unknown[];
    cases: unknown[];
    parts: Record<string, unknown>;
    vote: Record<string, number>;
  };
  const vote = {
    ticker: "PLNT",
    asOf: "2026-08-31",
    priceAtAsOf: f.vote.price,
    nTargets: f.vote.n_targets,
    low: f.vote.low,
    high: f.vote.high,
    median: f.vote.median,
    medianGap: f.vote.median_gap,
    nContestedBull: 15,
    nContestedBear: 0,
    nEndorsed: 4,
    ageDays: 0,
    summary: null,
    parts: parseParts({
      position: f.parts.position,
      pays_for: f.parts.pays_for,
      declines: f.parts.declines,
      crux: f.parts.crux,
    }),
    drivers: parseDrivers(f.drivers, f.cases),
    analystCases: [],
  };
  return (
    <div className="mx-auto max-w-5xl p-8">
      <PricedInPanel vote={vote} livePrice={53.33} />
    </div>
  );
}
