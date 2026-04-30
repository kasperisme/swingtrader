"use client";

import { type ReactNode, useEffect, useMemo, useState } from "react";
import { ChevronDown } from "lucide-react";

export type QuickRange = "7d" | "30d" | "90d" | "180d" | "1y" | "3y" | "5y" | "custom";

export type ChartGranularity = "1hour" | "4hour" | "1day" | "1week";

const GRANULARITY_OPTIONS: { value: ChartGranularity; label: string }[] = [
  { value: "1week", label: "1W" },
  { value: "1day", label: "1D" },
  { value: "4hour", label: "4H" },
  { value: "1hour", label: "1H" },
];

const RANGE_BY_GRANULARITY: Record<ChartGranularity, { ranges: QuickRange[]; default: QuickRange }> = {
  "1hour": { ranges: ["7d", "30d", "90d", "180d"], default: "30d" },
  "4hour": { ranges: ["7d", "30d", "90d", "180d", "1y"], default: "90d" },
  "1day": { ranges: ["7d", "30d", "90d", "1y", "3y"], default: "1y" },
  "1week": { ranges: ["30d", "90d", "1y", "3y", "5y"], default: "3y" },
};

const RANGE_DAYS: Record<Exclude<QuickRange, "custom">, number> = {
  "7d": 7,
  "30d": 30,
  "90d": 90,
  "180d": 180,
  "1y": 365,
  "3y": 365 * 3,
  "5y": 365 * 5,
};

const RANGE_LABELS: Record<QuickRange, string> = {
  "7d": "7d",
  "30d": "30d",
  "90d": "90d",
  "180d": "6m",
  "1y": "1y",
  "3y": "3y",
  "5y": "5y",
  custom: "custom",
};

const pad2 = (n: number) => String(n).padStart(2, "0");
function localDateStr(d: Date) {
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
}

interface ChartDateRangePickerProps {
  onChange: (range: { from: string; to: string }) => void;
  onGranularityChange?: (granularity: ChartGranularity) => void;
  defaultRange?: QuickRange;
  defaultGranularity?: ChartGranularity;
  minDate?: string;
  maxDate?: string;
  autoApplyDefaultRange?: boolean;
  settingsContent?: ReactNode;
}

export function ChartDateRangePicker({
  onChange,
  onGranularityChange,
  defaultRange = "1y",
  defaultGranularity = "1day",
  minDate,
  maxDate,
  autoApplyDefaultRange = true,
  settingsContent,
}: ChartDateRangePickerProps) {
  const todayStr = useMemo(() => localDateStr(new Date()), []);
  const maxDateStr = maxDate || todayStr;
  const [granularity, setGranularity] = useState<ChartGranularity>(defaultGranularity);
  const [quickRange, setQuickRange] = useState<QuickRange>(defaultRange);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [mobileSettingsOpen, setMobileSettingsOpen] = useState(false);

  const availableRanges = RANGE_BY_GRANULARITY[granularity].ranges;

  function applyQuickRange(range: QuickRange, emit = true) {
    setQuickRange(range);
    if (range === "custom") return;
    const days = RANGE_DAYS[range];
    const [y, m, d] = maxDateStr.split("-").map(Number);
    const end = new Date(y, m - 1, d);
    const start = new Date(end);
    start.setDate(start.getDate() - days);
    const minBound = minDate ? new Date(`${minDate}T00:00:00`) : null;
    if (minBound && start < minBound) start.setTime(minBound.getTime());
    const from = localDateStr(start);
    const to = localDateStr(end);
    setDateFrom(from);
    setDateTo(to);
    if (emit) onChange({ from, to });
  }

  useEffect(() => {
    if (!autoApplyDefaultRange) return;
    applyQuickRange(defaultRange);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoApplyDefaultRange]);

  useEffect(() => {
    onGranularityChange?.(granularity);
  }, [granularity, onGranularityChange]);

  const handleGranularityChange = (g: ChartGranularity) => {
    const prev = granularity;
    setGranularity(g);

    const config = RANGE_BY_GRANULARITY[g];
    if (quickRange === "custom") {
      if (prev !== g) onChange({ from: dateFrom, to: dateTo });
      return;
    }

    const stillAvailable = config.ranges.includes(quickRange as QuickRange);
    if (stillAvailable) {
      applyQuickRange(quickRange as QuickRange);
    } else {
      applyQuickRange(config.default);
    }
  };

  const renderRangeButtons = (mobile = false) =>
    availableRanges.map((r) => (
      <button
        key={r}
        type="button"
        onClick={() => applyQuickRange(r)}
        className={
          mobile
            ? `min-h-11 shrink-0 rounded-md border px-3 text-[11px] font-mono tracking-[0.05em] transition-colors ${
                quickRange === r
                  ? "border-foreground bg-foreground text-background"
                  : "border-border text-muted-foreground hover:text-foreground"
              }`
            : `text-[11px] px-3 py-2 transition-colors cursor-pointer border-r border-border ${
                quickRange === r
                  ? "bg-foreground text-background"
                  : "text-muted-foreground hover:text-foreground"
              }`
        }
      >
        {RANGE_LABELS[r]}
      </button>
    ));

  const renderGranularityButtons = (mobile = false) =>
    GRANULARITY_OPTIONS.map(({ value, label }) => (
      <button
        key={value}
        type="button"
        onClick={() => handleGranularityChange(value)}
        className={
          mobile
            ? `min-h-11 rounded-md border text-[11px] font-mono tracking-[0.05em] transition-colors ${
                granularity === value
                  ? "border-foreground bg-foreground text-background"
                  : "border-border text-muted-foreground hover:text-foreground"
              }`
            : `text-[11px] px-2.5 py-1 rounded transition-colors cursor-pointer ${
                granularity === value
                  ? "bg-foreground text-background"
                  : "text-muted-foreground hover:text-foreground"
              }`
        }
      >
        {label}
      </button>
    ));

  return (
    <div className="rounded-xl md:border md:border-border md:bg-card">
      {/* AESTHETIC DIRECTION: dark terminal tone; mono data labels; token-only signal contrast; thumb-first mobile controls. */}
      <div className="md:hidden px-1 py-1">
        <button
          type="button"
          onClick={() => setMobileSettingsOpen((open) => !open)}
          className="w-full min-h-11 rounded-md px-2.5 py-2 text-left transition-colors hover:bg-muted/30"
          aria-expanded={mobileSettingsOpen}
          aria-label="Toggle date settings"
        >
          <span className="flex items-center justify-between">
            <span className="text-[10px] font-mono uppercase tracking-[0.08em] text-muted-foreground">
              Settings
            </span>
            <ChevronDown
              className={`h-4 w-4 text-muted-foreground transition-transform ${mobileSettingsOpen ? "rotate-180" : ""}`}
            />
          </span>
          <span className="mt-1 block text-[11px] font-mono text-foreground/80">
            {dateFrom && dateTo ? `${dateFrom} - ${dateTo}` : "Tap to configure range and granularity"}
          </span>
        </button>
        {mobileSettingsOpen && (
          <div className="mt-2 space-y-2 border-t border-border pt-2">
            <div className="grid grid-cols-4 gap-1.5">
              {renderGranularityButtons(true)}
            </div>
            <div className="overflow-x-auto overflow-y-hidden">
              <div className="flex items-center gap-1.5 w-max pr-1">
                {renderRangeButtons(true)}
              </div>
            </div>
            <div className="grid grid-cols-2 gap-1.5">
              <label className="rounded-md border border-border px-2.5 py-2">
                <span className="block text-[9px] font-mono uppercase tracking-[0.08em] text-muted-foreground/70">
                  From
                </span>
                <input
                  type="date"
                  value={dateFrom}
                  min={minDate}
                  max={dateTo || maxDateStr}
                  onChange={(e) => {
                    setDateFrom(e.target.value);
                    setQuickRange("custom");
                    if (dateTo) onChange({ from: e.target.value, to: dateTo });
                  }}
                  className="mt-1 min-h-7 w-full bg-transparent text-[12px] font-mono text-foreground focus:outline-none"
                />
              </label>
              <label className="rounded-md border border-border px-2.5 py-2">
                <span className="block text-[9px] font-mono uppercase tracking-[0.08em] text-muted-foreground/70">
                  To
                </span>
                <input
                  type="date"
                  value={dateTo}
                  min={dateFrom}
                  max={maxDateStr}
                  onChange={(e) => {
                    setDateTo(e.target.value);
                    setQuickRange("custom");
                    if (dateFrom) onChange({ from: dateFrom, to: e.target.value });
                  }}
                  className="mt-1 min-h-7 w-full bg-transparent text-[12px] font-mono text-foreground focus:outline-none"
                />
              </label>
            </div>
            {settingsContent ? <div className="pt-1">{settingsContent}</div> : null}
          </div>
        )}
      </div>

      <div className="hidden md:flex md:items-stretch md:overflow-x-auto md:overflow-y-visible">
        <div className="flex items-center px-3 py-2 border-r border-border shrink-0">
          <span className="text-[10px] font-medium text-muted-foreground/60 uppercase tracking-wide">
            Range
          </span>
        </div>
        {renderRangeButtons()}
        <div className="flex items-center gap-1.5 px-3 py-2 border-r border-border shrink-0">
          <input
            type="date"
            value={dateFrom}
            min={minDate}
            max={dateTo || maxDateStr}
            onChange={(e) => {
              setDateFrom(e.target.value);
              setQuickRange("custom");
              if (dateTo) onChange({ from: e.target.value, to: dateTo });
            }}
            className="text-[11px] bg-transparent text-foreground focus:outline-none cursor-pointer"
          />
          <span className="text-[10px] text-muted-foreground/40">—</span>
          <input
            type="date"
            value={dateTo}
            min={dateFrom}
            max={maxDateStr}
            onChange={(e) => {
              setDateTo(e.target.value);
              setQuickRange("custom");
              if (dateFrom) onChange({ from: dateFrom, to: e.target.value });
            }}
            className="text-[11px] bg-transparent text-foreground focus:outline-none cursor-pointer"
          />
        </div>
        <div className="flex items-center px-3 py-2 shrink-0">
          <span className="text-[10px] font-medium text-muted-foreground/60 uppercase tracking-wide mr-2">
            Gran
          </span>
          {renderGranularityButtons()}
        </div>
      </div>
      {settingsContent ? (
        <div className="hidden md:block border-t border-border p-2">{settingsContent}</div>
      ) : null}
    </div>
  );
}