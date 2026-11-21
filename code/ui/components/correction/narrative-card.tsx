import Link from "next/link";
import {
  type Exposure,
  type NarrativeRow,
  fmtPct,
  fmtPts,
} from "@/lib/drawdown/narrative-format";

/**
 * One name's stress-test result: the cushion (or shortfall), the two growth
 * rates it compares, the thesis composed from those numbers, and the level that
 * would break it. Shared by the landing section and /correction so the two never
 * describe the same name differently.
 */

const EXPOSURE_TONE: Record<Exposure, string> = {
  low: "border-border text-muted-foreground",
  medium: "border-amber-500/40 text-amber-500",
  high: "border-red-500/40 text-red-500",
};

export function ExposureChip({ exposure }: { exposure: Exposure }) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 font-mono text-[10px] uppercase tracking-widest ${EXPOSURE_TONE[exposure]}`}
      title="Exposure while the correction runs: link to the AI epicenter, and beta"
    >
      {exposure} exposure
    </span>
  );
}

export function NarrativeCard({ row, compact = false }: { row: NarrativeRow; compact?: boolean }) {
  const short = (row.breakevenCut ?? 0) < 0;
  const breaks = (row.breaksIf ?? "").replace(/^already short; it holds only if /, "");
  return (
    <Link
      href={`/correction/${row.ticker}`}
      className="group flex flex-col gap-2 rounded-2xl border border-border bg-card/40 p-4 transition hover:border-amber-500/40 hover:bg-card/70"
    >
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <span className="font-mono text-base font-semibold tracking-tight">{row.ticker}</span>
        <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">
          {[row.company, row.sector].filter(Boolean).join(" · ")}
        </span>
        <ExposureChip exposure={row.exposure} />
      </div>

      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs tabular-nums text-muted-foreground">
        <span>
          {short ? "Shortfall" : "Absorbs a cut of"}{" "}
          <b className={short ? "font-semibold text-red-500" : "font-semibold text-emerald-500"}>
            {fmtPts(row.breakevenCut)}
          </b>
        </span>
        <span>
          Price needs <b className="font-medium text-foreground">{fmtPct(row.requiredCagr)}/yr</b>
        </span>
        <span>
          Analysts <b className="font-medium text-foreground">{fmtPct(row.consensus3y)}/yr</b>
        </span>
        {!compact && (
          <span>
            From peak <b className="font-medium text-foreground">{fmtPct(row.drawdownFromPeak)}</b>
          </span>
        )}
      </div>

      {row.thesis && (
        <p className={`text-sm leading-6 text-foreground/90 ${compact ? "line-clamp-3" : ""}`}>{row.thesis}</p>
      )}
      {breaks && (
        <p className="text-xs">
          <span className={short ? "font-semibold text-red-500" : "font-semibold text-amber-500"}>
            {short ? "Would recover if: " : "Breaks if: "}
          </span>
          <span className="text-muted-foreground">{breaks}</span>
        </p>
      )}
      <span className="mt-auto text-xs font-medium text-amber-500 opacity-80 group-hover:opacity-100">
        Full breakdown →
      </span>
    </Link>
  );
}
