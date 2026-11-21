"use client";

import { useMemo, useState } from "react";
import { NarrativeCard } from "@/components/correction/narrative-card";
import {
  type Exposure,
  type NarrativeGroup,
  type NarrativeRow,
  GROUP_LABEL,
  GROUP_RULE,
} from "@/lib/drawdown/narrative-format";

/**
 * Every scored name, one group at a time, filterable by correction exposure
 * and sector. Filtering is client-side: the whole board is a few hundred small
 * rows and already cached on the server, so a round-trip per click buys nothing.
 */

const GROUPS: NarrativeGroup[] = ["on_top", "holds", "fragile", "drowns"];
const TONE: Record<NarrativeGroup, string> = {
  on_top: "text-emerald-500 border-emerald-500/50",
  holds: "text-foreground border-foreground/40",
  fragile: "text-amber-500 border-amber-500/50",
  drowns: "text-red-500 border-red-500/50",
  not_cash_flow: "text-muted-foreground border-border",
  refused: "text-muted-foreground border-border",
};
const EXPOSURE: { value: string; label: string; keep: Exposure[] }[] = [
  { value: "all", label: "All exposure", keep: ["low", "medium", "high"] },
  { value: "lowmed", label: "Low and medium", keep: ["low", "medium"] },
  { value: "low", label: "Low only", keep: ["low"] },
];
const PAGE = 24;

const SELECT =
  "rounded-lg border border-border bg-background px-3 py-1.5 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-amber-500/40";

export function CorrectionBoard({ rows }: { rows: NarrativeRow[] }) {
  const [group, setGroup] = useState<NarrativeGroup>("on_top");
  const [exposure, setExposure] = useState("all");
  const [sector, setSector] = useState("");
  const [limit, setLimit] = useState(PAGE);

  const sectors = useMemo(
    () => [...new Set(rows.map((r) => r.sector).filter((x): x is string => Boolean(x)))].sort(),
    [rows],
  );
  const keep = EXPOSURE.find((e) => e.value === exposure)!.keep;
  const filtered = useMemo(
    () => rows.filter((r) => keep.includes(r.exposure) && (!sector || r.sector === sector)),
    [rows, keep, sector],
  );
  const counts = useMemo(() => {
    const c: Partial<Record<NarrativeGroup, number>> = {};
    for (const r of filtered) c[r.group] = (c[r.group] ?? 0) + 1;
    return c;
  }, [filtered]);
  const shown = useMemo(
    () =>
      filtered
        .filter((r) => r.group === group)
        .sort((a, b) =>
          group === "drowns"
            ? (a.breakevenCut ?? 0) - (b.breakevenCut ?? 0)
            : (b.breakevenCut ?? 0) - (a.breakevenCut ?? 0),
        ),
    [filtered, group],
  );

  return (
    <div>
      <div role="tablist" aria-label="Stress-test group" className="flex flex-wrap gap-2">
        {GROUPS.map((g) => (
          <button
            key={g}
            type="button"
            role="tab"
            aria-selected={group === g}
            onClick={() => {
              setGroup(g);
              setLimit(PAGE);
            }}
            className={`rounded-full border px-4 py-1.5 text-sm font-medium transition ${
              group === g ? `${TONE[g]} bg-card` : "border-border text-muted-foreground hover:text-foreground"
            }`}
          >
            {GROUP_LABEL[g]} <span className="tabular-nums opacity-70">{counts[g] ?? 0}</span>
          </button>
        ))}
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <select aria-label="Correction exposure" className={SELECT} value={exposure} onChange={(e) => setExposure(e.target.value)}>
          {EXPOSURE.map((e) => (
            <option key={e.value} value={e.value}>
              {e.label}
            </option>
          ))}
        </select>
        <select aria-label="Sector" className={SELECT} value={sector} onChange={(e) => setSector(e.target.value)}>
          <option value="">All sectors</option>
          {sectors.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <p className="text-xs text-muted-foreground">{GROUP_RULE[group]}</p>
      </div>

      <div className="mt-6 grid gap-3 md:grid-cols-2">
        {shown.slice(0, limit).map((r) => (
          <NarrativeCard key={r.ticker} row={r} />
        ))}
      </div>
      {shown.length === 0 && <p className="mt-6 text-sm text-muted-foreground">No names match these filters.</p>}
      {shown.length > limit && (
        <button
          type="button"
          onClick={() => setLimit((l) => l + PAGE)}
          className="mt-6 rounded-full border border-border px-4 py-2 text-sm font-medium text-muted-foreground hover:text-foreground"
        >
          Show {Math.min(PAGE, shown.length - limit)} more of {shown.length - limit}
        </button>
      )}
    </div>
  );
}
