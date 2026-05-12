"use client";

import { useMemo } from "react";
import { ArrowDown, ArrowUp, Minus } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatDimLabel } from "@/lib/company-fingerprint/dimensions";
import {
  bucketPressure,
  buildDimPressureMap,
  type NewsPressure,
} from "@/lib/company-fingerprint/news-pressure";
import {
  buildOperationalRows,
  buildSectorRows,
  type OperationalRow,
} from "@/lib/company-fingerprint/rows";
import type { HeatmapInputRow } from "@/lib/news-impact-heatmap/aggregate";

const PURPLE = "#7F77DD";
const UP_COLOR = "#639922";
const DOWN_COLOR = "#E24B4A";

export type CompanyFingerprintProps = {
  ticker: string;
  vectorDate: string;
  dimensions: Record<string, number>;
  raw: Record<string, number | null>;
  metadata?: {
    name?: string;
    sector?: string;
    industry?: string;
    market_cap?: number;
  };
  /** 24h news rows (same shape the heatmap uses). When omitted, no news arrows
   *  are rendered — useful for callers that just want the static fingerprint. */
  newsRows?: HeatmapInputRow[];
  className?: string;
};

export function CompanyFingerprint({
  ticker,
  vectorDate,
  dimensions,
  raw,
  metadata,
  newsRows,
  className,
}: CompanyFingerprintProps) {
  const pressureByDim = useMemo(() => {
    if (!newsRows || newsRows.length === 0) return new Map<string, NewsPressure>();
    return buildDimPressureMap(newsRows, ticker);
  }, [newsRows, ticker]);

  const knownCount = useMemo(
    () => Object.values(raw).filter((v) => v !== null).length,
    [raw],
  );
  const totalCount = useMemo(() => Object.keys(raw).length, [raw]);

  const operationalRows = useMemo<OperationalRow[]>(
    () => buildOperationalRows({ dimensions, raw, pressureByDim }),
    [dimensions, raw, pressureByDim],
  );

  const sectorRows = useMemo(
    () => buildSectorRows({ dimensions, pressureByDim }),
    [dimensions, pressureByDim],
  );

  return (
    <div
      className={cn(
        "flex flex-col gap-3 rounded-lg border bg-card px-3 py-3 sm:px-4 sm:py-3.5",
        className,
      )}
    >
      <Header
        ticker={ticker}
        vectorDate={vectorDate}
        metadata={metadata}
        knownCount={knownCount}
        totalCount={totalCount}
      />
      <SectorInset rows={sectorRows} />
      <Fingerprint rows={operationalRows} />
    </div>
  );
}

function Header({
  ticker,
  vectorDate,
  metadata,
  knownCount,
  totalCount,
}: {
  ticker: string;
  vectorDate: string;
  metadata?: CompanyFingerprintProps["metadata"];
  knownCount: number;
  totalCount: number;
}) {
  const sector = metadata?.sector?.trim() || "—";
  const industry = metadata?.industry?.trim() || "";
  const name = metadata?.name?.trim();

  return (
    <div className="min-w-0">
      <div className="flex items-baseline gap-2">
        <h3 className="text-base font-semibold tracking-tight">{ticker}</h3>
        {name && (
          <span className="truncate text-xs text-muted-foreground">{name}</span>
        )}
      </div>
      <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-muted-foreground">
        <span>{sector}</span>
        {industry && <span className="text-muted-foreground/60">·</span>}
        {industry && <span>{industry}</span>}
        <span className="text-muted-foreground/60">·</span>
        <span className="font-mono">{vectorDate || "—"}</span>
        <span className="text-muted-foreground/60">·</span>
        <span className="rounded-md border border-border/60 bg-muted/30 px-1.5 py-0.5 text-[10px] font-medium text-foreground/80">
          {knownCount} of {totalCount || 42} known
        </span>
      </div>
    </div>
  );
}

function SectorInset({
  rows,
}: {
  rows: Array<{ dim: string; value: number; pressure: NewsPressure | null }>;
}) {
  return (
    <div className="grid grid-cols-1 gap-x-4 gap-y-1 sm:grid-cols-2">
      {rows.map((r) => (
        <div key={r.dim} className="flex items-center gap-2 text-[11px]">
          <span className="w-24 truncate text-muted-foreground">
            {formatDimLabel(r.dim).replace(/^Sector\s+/, "")}
          </span>
          <div className="relative h-2 flex-1 overflow-hidden rounded-sm bg-muted/40">
            <div
              className="absolute inset-y-0 left-0 rounded-sm"
              style={{
                width: `${Math.max(0, Math.min(1, r.value)) * 100}%`,
                backgroundColor: PURPLE,
                opacity: 0.88,
              }}
            />
          </div>
          <span className="w-8 text-right font-mono tabular-nums text-foreground/70">
            {r.value.toFixed(2)}
          </span>
          <PressureGlyph pressure={r.pressure} />
        </div>
      ))}
    </div>
  );
}

function Fingerprint({ rows }: { rows: OperationalRow[] }) {
  if (rows.length === 0) {
    return (
      <div className="rounded-md border border-dashed bg-muted/20 px-3 py-6 text-center text-xs text-muted-foreground">
        No dimensions with real signal yet.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-0.5">
      {rows.map((r) => {
        const half = Math.abs(r.value - 0.5);
        const positive = r.value - 0.5 >= 0;
        return (
          <div
            key={r.dim}
            className="grid grid-cols-[minmax(0,9rem)_minmax(0,1fr)_3.25rem_1rem] items-center gap-2 text-[11px] sm:grid-cols-[minmax(0,11rem)_minmax(0,1fr)_3.5rem_1rem]"
          >
            <span
              className="truncate text-foreground/80"
              title={formatDimLabel(r.dim)}
            >
              {formatDimLabel(r.dim)}
            </span>
            <div className="relative h-3.5">
              <div
                className="pointer-events-none absolute inset-y-0 left-1/2 w-px bg-border"
                aria-hidden
              />
              <div
                className="absolute top-1/2 h-2 -translate-y-1/2 rounded-sm"
                style={{
                  left: positive ? "50%" : `${(0.5 - half) * 100}%`,
                  width: `${half * 100}%`,
                  backgroundColor: PURPLE,
                  opacity: 0.88,
                }}
              />
            </div>
            <span className="text-right font-mono tabular-nums text-foreground/80">
              {r.numericLabel}
            </span>
            <PressureGlyph pressure={r.pressure} />
          </div>
        );
      })}
      <p className="mt-2 text-[10px] text-muted-foreground/70">
        Top {rows.length} dimensions by distance from 0.5 (percentile midline).
      </p>
    </div>
  );
}

function PressureGlyph({ pressure }: { pressure: NewsPressure | null }) {
  if (pressure == null) {
    return <span className="inline-block w-3" aria-hidden />;
  }
  const common = "h-3 w-3";
  if (pressure === "up") {
    return (
      <ArrowUp
        className={common}
        style={{ color: UP_COLOR }}
        aria-label="News pressure up"
      />
    );
  }
  if (pressure === "down") {
    return (
      <ArrowDown
        className={common}
        style={{ color: DOWN_COLOR }}
        aria-label="News pressure down"
      />
    );
  }
  return (
    <Minus
      className={common}
      style={{ color: "currentColor", opacity: 0.4 }}
      aria-label="News pressure neutral"
    />
  );
}

export const fingerprintBucketPressure = bucketPressure;
