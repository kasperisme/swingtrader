"use client";

import { useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import { CheckCircle, XCircle, Search, SlidersHorizontal, ChevronDown, ChevronUp } from "lucide-react";

export interface ScanRun {
  id: number;
  created_at: string;
  scan_date: string;
  source: string;
}

export interface ScreeningRow {
  symbol: string;
  sector: string;
  subSector: string;
  // Technical
  RS_Rank: number | null;
  Passed: boolean;
  PASSED_FUNDAMENTALS: boolean;
  PriceOverSMA150And200: boolean;
  SMA150AboveSMA200: boolean;
  SMA50AboveSMA150And200: boolean;
  SMA200Slope: boolean;
  PriceAbove25Percent52WeekLow: boolean;
  PriceWithin25Percent52WeekHigh: boolean;
  RSOver70: boolean;
  // Volume / price action
  adr_pct: number | null;
  vol_ratio_today: number | null;
  up_down_vol_ratio: number | null;
  accumulation: boolean | null;
  rs_line_new_high: boolean | null;
  within_buy_range: boolean | null;
  extended: boolean | null;
  // Fundamentals
  increasing_eps: boolean;
  beat_estimate: boolean;
  eps_growth_yoy: number | null;
  rev_growth_yoy: number | null;
  eps_accelerating: boolean | null;
  three_yr_annual_eps_25pct: boolean | null;
  roe: number | null;
  roe_above_17pct: boolean | null;
  passes_oneil_fundamentals: boolean | null;
  // Sector
  sector_is_leader: boolean | null;
  sector_rank: number | null;
  total_sectors: number | null;
  // Institutional
  inst_shares_increasing: boolean | null;
  inst_pct_accumulating: number | null;
}

// ─── small display helpers ───────────────────────────────────────────────────

function Check({ value }: { value: boolean | null | undefined }) {
  if (value == null) return <span className="text-muted-foreground/40 text-xs">—</span>;
  return value ? (
    <CheckCircle className="w-4 h-4 text-emerald-500 shrink-0" />
  ) : (
    <XCircle className="w-4 h-4 text-rose-400 shrink-0" />
  );
}

function Num({
  value,
  suffix = "",
  decimals = 1,
  colorize = false,
}: {
  value: number | null | undefined;
  suffix?: string;
  decimals?: number;
  colorize?: boolean;
}) {
  if (value == null) return <span className="text-muted-foreground/40">—</span>;
  const formatted = `${value >= 0 ? "+" : ""}${value.toFixed(decimals)}${suffix}`;
  const color = colorize
    ? value >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-rose-500"
    : "";
  return <span className={`tabular-nums ${color}`}>{formatted}</span>;
}

function RsBadge({ rank }: { rank: number | null }) {
  if (rank == null) return <span className="text-muted-foreground">—</span>;
  const color =
    rank >= 90 ? "bg-emerald-500/20 text-emerald-600 dark:text-emerald-400" :
    rank >= 70 ? "bg-amber-500/20 text-amber-600 dark:text-amber-400" :
    "bg-muted text-muted-foreground";
  return (
    <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium tabular-nums ${color}`}>
      {rank}
    </span>
  );
}

// ─── filter state ────────────────────────────────────────────────────────────

interface Filters {
  passedOnly: boolean;
  // Technical
  minRsRank: string;
  rsLineNewHigh: boolean;
  withinBuyRange: boolean;
  accumulation: boolean;
  // Fundamentals
  minEpsGrowth: string;
  minRevGrowth: string;
  epsAccelerating: boolean;
  roe17pct: boolean;
  beatEstimate: boolean;
  increasingEps: boolean;
  threeYrEps25pct: boolean;
  passesOneil: boolean;
  // Sector / Inst
  sectorLeader: boolean;
  instSharesIncreasing: boolean;
  // Sector text
  sector: string;
}

const DEFAULT_FILTERS: Filters = {
  passedOnly: true,
  minRsRank: "",
  rsLineNewHigh: false,
  withinBuyRange: false,
  accumulation: false,
  minEpsGrowth: "",
  minRevGrowth: "",
  epsAccelerating: false,
  roe17pct: false,
  beatEstimate: false,
  increasingEps: false,
  threeYrEps25pct: false,
  passesOneil: false,
  sectorLeader: false,
  instSharesIncreasing: false,
  sector: "",
};

type SortKey = "symbol" | "RS_Rank" | "sector" | "eps_growth_yoy" | "rev_growth_yoy" | "roe" | "adr_pct";
type SortDir = "asc" | "desc";

// ─── FilterPanel ─────────────────────────────────────────────────────────────

function FilterPanel({
  filters,
  setFilters,
  sectors,
  hasRichData,
}: {
  filters: Filters;
  setFilters: (f: Filters) => void;
  sectors: string[];
  hasRichData: boolean;
}) {
  const [open, setOpen] = useState(false);

  function set<K extends keyof Filters>(key: K, value: Filters[K]) {
    setFilters({ ...filters, [key]: value });
  }

  function CheckFilter({
    label,
    field,
    disabled,
    title,
  }: {
    label: string;
    field: keyof Filters;
    disabled?: boolean;
    title?: string;
  }) {
    return (
      <label
        className={`flex items-center gap-2 text-sm cursor-pointer select-none ${disabled ? "opacity-40 cursor-not-allowed" : ""}`}
        title={title}
      >
        <input
          type="checkbox"
          checked={filters[field] as boolean}
          onChange={e => !disabled && set(field, e.target.checked as Filters[typeof field])}
          disabled={disabled}
          className="rounded"
        />
        {label}
      </label>
    );
  }

  function NumFilter({
    label,
    field,
    placeholder,
    disabled,
    title,
  }: {
    label: string;
    field: keyof Filters;
    placeholder: string;
    disabled?: boolean;
    title?: string;
  }) {
    return (
      <label className={`flex flex-col gap-0.5 ${disabled ? "opacity-40" : ""}`} title={title}>
        <span className="text-xs text-muted-foreground">{label}</span>
        <input
          type="number"
          value={filters[field] as string}
          onChange={e => !disabled && set(field, e.target.value as Filters[typeof field])}
          disabled={disabled}
          placeholder={placeholder}
          className="w-20 px-2 py-1 text-sm rounded border border-input bg-background focus:outline-none focus:ring-1 focus:ring-ring"
        />
      </label>
    );
  }

  const richDisabledTitle = hasRichData ? undefined : "Not available for this scan type";

  return (
    <div className="border border-border rounded-lg">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-4 py-2.5 text-sm font-medium hover:bg-muted/30 transition-colors rounded-lg"
      >
        <span className="flex items-center gap-2">
          <SlidersHorizontal className="w-4 h-4" />
          Filters
          {countActiveFilters(filters) > 0 && (
            <span className="bg-foreground text-background text-xs px-1.5 py-0.5 rounded-full">
              {countActiveFilters(filters)}
            </span>
          )}
        </span>
        {open ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
      </button>

      {open && (
        <div className="px-4 pb-4 pt-1 border-t border-border flex flex-col gap-4">
          {/* Top-level */}
          <div className="flex flex-wrap gap-x-8 gap-y-2 pt-2">
            <CheckFilter label="Passed technical only" field="passedOnly" />
            {sectors.length > 1 && (
              <label className="flex flex-col gap-0.5">
                <span className="text-xs text-muted-foreground">Sector</span>
                <select
                  value={filters.sector}
                  onChange={e => set("sector", e.target.value)}
                  className="px-2 py-1 text-sm rounded border border-input bg-background focus:outline-none focus:ring-1 focus:ring-ring"
                >
                  <option value="">All sectors</option>
                  {sectors.map(s => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </select>
              </label>
            )}
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            {/* Technical */}
            <div className="flex flex-col gap-2">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Technical</p>
              <NumFilter label="Min RS Rank" field="minRsRank" placeholder="e.g. 80" />
              <CheckFilter label="RS line new high" field="rsLineNewHigh" disabled={!hasRichData} title={richDisabledTitle} />
              <CheckFilter label="Within buy range" field="withinBuyRange" disabled={!hasRichData} title={richDisabledTitle} />
              <CheckFilter label="Accumulation days" field="accumulation" disabled={!hasRichData} title={richDisabledTitle} />
            </div>

            {/* Fundamentals */}
            <div className="flex flex-col gap-2">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Fundamentals</p>
              <NumFilter label="Min EPS YoY %" field="minEpsGrowth" placeholder="e.g. 25" disabled={!hasRichData} title={richDisabledTitle} />
              <NumFilter label="Min Rev YoY %" field="minRevGrowth" placeholder="e.g. 20" disabled={!hasRichData} title={richDisabledTitle} />
              <CheckFilter label="EPS accelerating" field="epsAccelerating" disabled={!hasRichData} title={richDisabledTitle} />
              <CheckFilter label="ROE ≥ 17%" field="roe17pct" disabled={!hasRichData} title={richDisabledTitle} />
              <CheckFilter label="Beat estimates (3Q)" field="beatEstimate" />
              <CheckFilter label="Increasing EPS" field="increasingEps" />
              <CheckFilter label="3yr EPS ≥ 25% p.a." field="threeYrEps25pct" disabled={!hasRichData} title={richDisabledTitle} />
              <CheckFilter label="Passes O'Neil criteria" field="passesOneil" disabled={!hasRichData} title={richDisabledTitle} />
            </div>

            {/* Sector & Institutional */}
            <div className="flex flex-col gap-2">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Sector &amp; Institutional</p>
              <CheckFilter label="Sector leader (top 40%)" field="sectorLeader" disabled={!hasRichData} title={richDisabledTitle} />
              <CheckFilter label="Inst. shares increasing" field="instSharesIncreasing" disabled={!hasRichData} title={richDisabledTitle} />
            </div>
          </div>

          <button
            onClick={() => setFilters(DEFAULT_FILTERS)}
            className="self-start text-xs text-muted-foreground hover:text-foreground underline underline-offset-2"
          >
            Reset filters
          </button>
        </div>
      )}
    </div>
  );
}

function countActiveFilters(f: Filters): number {
  let n = 0;
  if (!f.passedOnly) n++; // passedOnly=true is the "default active" state — don't count it
  if (f.minRsRank) n++;
  if (f.rsLineNewHigh) n++;
  if (f.withinBuyRange) n++;
  if (f.accumulation) n++;
  if (f.minEpsGrowth) n++;
  if (f.minRevGrowth) n++;
  if (f.epsAccelerating) n++;
  if (f.roe17pct) n++;
  if (f.beatEstimate) n++;
  if (f.increasingEps) n++;
  if (f.threeYrEps25pct) n++;
  if (f.passesOneil) n++;
  if (f.sectorLeader) n++;
  if (f.instSharesIncreasing) n++;
  if (f.sector) n++;
  return n;
}

// ─── main component ──────────────────────────────────────────────────────────

const TECH_CRITERIA: { key: keyof ScreeningRow; short: string; label: string }[] = [
  { key: "PriceOverSMA150And200", short: "P>SMA", label: "Price > SMA150 & SMA200" },
  { key: "SMA150AboveSMA200", short: "150>200", label: "SMA150 > SMA200" },
  { key: "SMA50AboveSMA150And200", short: "50>150", label: "SMA50 > SMA150 & SMA200" },
  { key: "SMA200Slope", short: "200↗", label: "SMA200 Uptrending" },
  { key: "PriceAbove25Percent52WeekLow", short: ">Low", label: "Price > 52wk Low +25%" },
  { key: "PriceWithin25Percent52WeekHigh", short: "<High", label: "Price within 25% of 52wk High" },
  { key: "RSOver70", short: "RS>70", label: "RS > 70" },
];

export function ScreeningsUI({
  runs,
  rows,
  selectedRunId,
  vectorTickers,
}: {
  runs: ScanRun[];
  rows: ScreeningRow[];
  selectedRunId: number | null;
  vectorTickers: Set<string>;
}) {
  const router = useRouter();
  const [search, setSearch] = useState("");
  const [filters, setFilters] = useState<Filters>(DEFAULT_FILTERS);
  const [sortKey, setSortKey] = useState<SortKey>("RS_Rank");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  const hasRichData = rows.some(r => r.eps_growth_yoy != null || r.rs_line_new_high != null);

  const sectors = useMemo(() => {
    const set = new Set(rows.map(r => r.sector).filter(Boolean));
    return Array.from(set).sort();
  }, [rows]);

  function selectRun(id: number) {
    router.push(`/protected/screenings?run=${id}`);
  }

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir(d => d === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortDir(key === "symbol" || key === "sector" ? "asc" : "desc");
    }
  }

  const filtered = useMemo(() => {
    const minRs = filters.minRsRank ? parseFloat(filters.minRsRank) : null;
    const minEps = filters.minEpsGrowth ? parseFloat(filters.minEpsGrowth) : null;
    const minRev = filters.minRevGrowth ? parseFloat(filters.minRevGrowth) : null;

    let result = rows.filter(r => {
      if (filters.passedOnly && !r.Passed) return false;
      if (filters.sector && r.sector !== filters.sector) return false;
      if (minRs != null && (r.RS_Rank == null || r.RS_Rank < minRs)) return false;
      if (filters.rsLineNewHigh && !r.rs_line_new_high) return false;
      if (filters.withinBuyRange && !r.within_buy_range) return false;
      if (filters.accumulation && !r.accumulation) return false;
      if (minEps != null && (r.eps_growth_yoy == null || r.eps_growth_yoy < minEps)) return false;
      if (minRev != null && (r.rev_growth_yoy == null || r.rev_growth_yoy < minRev)) return false;
      if (filters.epsAccelerating && !r.eps_accelerating) return false;
      if (filters.roe17pct && !r.roe_above_17pct) return false;
      if (filters.beatEstimate && !r.beat_estimate) return false;
      if (filters.increasingEps && !r.increasing_eps) return false;
      if (filters.threeYrEps25pct && !r.three_yr_annual_eps_25pct) return false;
      if (filters.passesOneil && !r.passes_oneil_fundamentals) return false;
      if (filters.sectorLeader && !r.sector_is_leader) return false;
      if (filters.instSharesIncreasing && !r.inst_shares_increasing) return false;
      return true;
    });

    if (search.trim()) {
      const q = search.trim().toLowerCase();
      result = result.filter(r =>
        r.symbol?.toLowerCase().includes(q) ||
        r.sector?.toLowerCase().includes(q) ||
        r.subSector?.toLowerCase().includes(q)
      );
    }

    result = [...result].sort((a, b) => {
      let cmp = 0;
      if (sortKey === "symbol") cmp = (a.symbol ?? "").localeCompare(b.symbol ?? "");
      else if (sortKey === "sector") cmp = (a.sector ?? "").localeCompare(b.sector ?? "");
      else if (sortKey === "RS_Rank") cmp = (a.RS_Rank ?? -1) - (b.RS_Rank ?? -1);
      else if (sortKey === "eps_growth_yoy") cmp = (a.eps_growth_yoy ?? -9999) - (b.eps_growth_yoy ?? -9999);
      else if (sortKey === "rev_growth_yoy") cmp = (a.rev_growth_yoy ?? -9999) - (b.rev_growth_yoy ?? -9999);
      else if (sortKey === "roe") cmp = (a.roe ?? -9999) - (b.roe ?? -9999);
      else if (sortKey === "adr_pct") cmp = (a.adr_pct ?? -9999) - (b.adr_pct ?? -9999);
      return sortDir === "asc" ? cmp : -cmp;
    });

    return result;
  }, [rows, filters, search, sortKey, sortDir]);

  const selectedRun = runs.find(r => r.id === selectedRunId) ?? runs[0] ?? null;

  function SortIcon({ col }: { col: SortKey }) {
    if (sortKey !== col) return null;
    return sortDir === "asc"
      ? <ChevronUp className="w-3 h-3 inline ml-0.5" />
      : <ChevronDown className="w-3 h-3 inline ml-0.5" />;
  }

  function Th({ col, children, center }: { col: SortKey; children: React.ReactNode; center?: boolean }) {
    return (
      <th
        className={`px-3 py-2 text-xs font-medium text-muted-foreground uppercase tracking-wide cursor-pointer select-none hover:text-foreground whitespace-nowrap ${center ? "text-center" : "text-left"}`}
        onClick={() => toggleSort(col)}
      >
        {children}<SortIcon col={col} />
      </th>
    );
  }

  return (
    <div className="flex gap-6 min-h-0">
      {/* Run selector sidebar */}
      <aside className="w-48 shrink-0 flex flex-col gap-1">
        <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">Scan Runs</p>
        {runs.length === 0 && (
          <p className="text-sm text-muted-foreground">No runs yet.</p>
        )}
        {runs.map(run => {
          const active = run.id === (selectedRun?.id ?? null);
          return (
            <button
              key={run.id}
              onClick={() => selectRun(run.id)}
              className={`text-left px-3 py-2 rounded-lg text-sm transition-colors ${
                active
                  ? "bg-foreground text-background font-medium"
                  : "hover:bg-muted text-muted-foreground hover:text-foreground"
              }`}
            >
              <div className="font-medium">{run.scan_date}</div>
              <div className="text-xs opacity-70 truncate">{run.source}</div>
            </button>
          );
        })}
      </aside>

      {/* Results panel */}
      <div className="flex-1 min-w-0 flex flex-col gap-4">
        {/* Search + count */}
        <div className="flex items-center gap-3">
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <input
              type="text"
              placeholder="Search symbol, sector…"
              value={search}
              onChange={e => setSearch(e.target.value)}
              className="pl-8 pr-3 py-1.5 text-sm rounded-md border border-input bg-background focus:outline-none focus:ring-1 focus:ring-ring w-52"
            />
          </div>
          <span className="text-sm text-muted-foreground ml-auto">
            {filtered.length} shown
            {rows.length > 0 && ` / ${rows.length} screened`}
          </span>
        </div>

        {/* Filter panel */}
        <FilterPanel
          filters={filters}
          setFilters={setFilters}
          sectors={sectors}
          hasRichData={hasRichData}
        />

        {/* Table */}
        {rows.length === 0 ? (
          <div className="text-sm text-muted-foreground py-8 text-center">
            {selectedRun ? "No results for this run." : "Select a scan run to view results."}
          </div>
        ) : filtered.length === 0 ? (
          <div className="text-sm text-muted-foreground py-8 text-center">
            No stocks match the current filters.
          </div>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-border">
            <table className="w-full text-sm">
              <thead className="bg-muted/40 border-b border-border">
                <tr>
                  <Th col="symbol">Symbol</Th>
                  <Th col="sector">Sector</Th>
                  <Th col="RS_Rank" center>RS Rank</Th>
                  {/* Tech criteria */}
                  {TECH_CRITERIA.map(c => (
                    <th
                      key={c.key}
                      title={c.label}
                      className="px-2 py-2 text-center text-xs font-medium text-muted-foreground uppercase tracking-wide whitespace-nowrap"
                    >
                      {c.short}
                    </th>
                  ))}
                  <th title="All technical criteria passed" className="px-3 py-2 text-center text-xs font-medium text-muted-foreground uppercase tracking-wide">Tech</th>
                  <th title="Company sensitivity vector in database" className="px-3 py-2 text-center text-xs font-medium text-muted-foreground uppercase tracking-wide">Vec</th>

                  {/* Fundamentals — always show beat/eps */}
                  <th title="Beat estimates (last 3Q)" className="px-2 py-2 text-center text-xs font-medium text-muted-foreground uppercase tracking-wide">Beat</th>
                  <th title="Increasing EPS (SMA direction)" className="px-2 py-2 text-center text-xs font-medium text-muted-foreground uppercase tracking-wide">EPS↗</th>

                  {/* Rich-data columns */}
                  {hasRichData && <>
                    <Th col="eps_growth_yoy" center>EPS YoY</Th>
                    <Th col="rev_growth_yoy" center>Rev YoY</Th>
                    <Th col="roe" center>ROE</Th>
                    <th title="EPS accelerating QoQ" className="px-2 py-2 text-center text-xs font-medium text-muted-foreground uppercase tracking-wide">Accel</th>
                    <th title="Passes all O'Neil criteria" className="px-2 py-2 text-center text-xs font-medium text-muted-foreground uppercase tracking-wide">O'Neil</th>
                    <th title="RS line at 52-week high" className="px-2 py-2 text-center text-xs font-medium text-muted-foreground uppercase tracking-wide">RS Hi</th>
                    <th title="Within buy range of pivot" className="px-2 py-2 text-center text-xs font-medium text-muted-foreground uppercase tracking-wide">Buy Pt</th>
                    <th title="Sector in top 40% today" className="px-2 py-2 text-center text-xs font-medium text-muted-foreground uppercase tracking-wide">Sect↑</th>
                    <th title="Institutional shares increasing QoQ" className="px-2 py-2 text-center text-xs font-medium text-muted-foreground uppercase tracking-wide">Inst↑</th>
                    <Th col="adr_pct" center>ADR%</Th>
                  </>}
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {filtered.map((row, i) => (
                  <tr key={row.symbol ?? i} className="hover:bg-muted/30 transition-colors">
                    <td className="px-3 py-2 font-mono font-semibold whitespace-nowrap">
                      {row.symbol ?? "—"}
                    </td>
                    <td className="px-3 py-2 text-xs text-muted-foreground whitespace-nowrap max-w-[140px] truncate" title={row.subSector || undefined}>
                      {row.sector || "—"}
                    </td>
                    <td className="px-3 py-2 text-center">
                      <RsBadge rank={row.RS_Rank} />
                    </td>
                    {TECH_CRITERIA.map(c => (
                      <td key={c.key} className="px-2 py-2 text-center">
                        <div className="flex justify-center">
                          <Check value={row[c.key] as boolean} />
                        </div>
                      </td>
                    ))}
                    <td className="px-3 py-2 text-center">
                      <div className="flex justify-center">
                        <Check value={row.Passed} />
                      </div>
                    </td>
                    <td className="px-3 py-2 text-center">
                      <div className="flex justify-center">
                        <Check value={vectorTickers.has(row.symbol ?? "")} />
                      </div>
                    </td>
                    <td className="px-2 py-2 text-center"><div className="flex justify-center"><Check value={row.beat_estimate} /></div></td>
                    <td className="px-2 py-2 text-center"><div className="flex justify-center"><Check value={row.increasing_eps} /></div></td>
                    {hasRichData && <>
                      <td className="px-3 py-2 text-center text-xs"><Num value={row.eps_growth_yoy} suffix="%" colorize /></td>
                      <td className="px-3 py-2 text-center text-xs"><Num value={row.rev_growth_yoy} suffix="%" colorize /></td>
                      <td className="px-3 py-2 text-center text-xs"><Num value={row.roe} suffix="%" /></td>
                      <td className="px-2 py-2 text-center"><div className="flex justify-center"><Check value={row.eps_accelerating} /></div></td>
                      <td className="px-2 py-2 text-center"><div className="flex justify-center"><Check value={row.passes_oneil_fundamentals} /></div></td>
                      <td className="px-2 py-2 text-center"><div className="flex justify-center"><Check value={row.rs_line_new_high} /></div></td>
                      <td className="px-2 py-2 text-center"><div className="flex justify-center"><Check value={row.within_buy_range} /></div></td>
                      <td className="px-2 py-2 text-center"><div className="flex justify-center"><Check value={row.sector_is_leader} /></div></td>
                      <td className="px-2 py-2 text-center"><div className="flex justify-center"><Check value={row.inst_shares_increasing} /></div></td>
                      <td className="px-3 py-2 text-center text-xs"><Num value={row.adr_pct} suffix="%" decimals={1} /></td>
                    </>}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Column legend */}
        {filtered.length > 0 && (
          <details className="text-xs text-muted-foreground">
            <summary className="cursor-pointer hover:text-foreground">Column key</summary>
            <div className="mt-2 grid grid-cols-2 gap-x-6 gap-y-0.5 pl-2">
              {TECH_CRITERIA.map(c => (
                <div key={c.key}><span className="font-mono font-medium">{c.short}</span> — {c.label}</div>
              ))}
              <div><span className="font-mono font-medium">Tech</span> — All 7 technical criteria passed</div>
              <div><span className="font-mono font-medium">Vec</span> — Company sensitivity vector in database</div>
              <div><span className="font-mono font-medium">Beat</span> — Beat EPS estimate last 3 quarters</div>
              <div><span className="font-mono font-medium">EPS↗</span> — EPS SMA trending up</div>
              {hasRichData && <>
                <div><span className="font-mono font-medium">EPS YoY</span> — EPS year-over-year growth %</div>
                <div><span className="font-mono font-medium">Rev YoY</span> — Revenue year-over-year growth %</div>
                <div><span className="font-mono font-medium">ROE</span> — Return on equity %</div>
                <div><span className="font-mono font-medium">Accel</span> — EPS growth accelerating QoQ</div>
                <div><span className="font-mono font-medium">O'Neil</span> — Passes EPS≥25%, Rev≥20%, Beat, ROE≥17%</div>
                <div><span className="font-mono font-medium">RS Hi</span> — RS line at 52-week high</div>
                <div><span className="font-mono font-medium">Buy Pt</span> — Within 5% of pivot buy point</div>
                <div><span className="font-mono font-medium">Sect↑</span> — Sector in top 40% today</div>
                <div><span className="font-mono font-medium">Inst↑</span> — Institutional shares increasing QoQ</div>
                <div><span className="font-mono font-medium">ADR%</span> — Average daily range %</div>
              </>}
            </div>
          </details>
        )}
      </div>
    </div>
  );
}
