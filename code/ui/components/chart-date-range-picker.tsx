"use client";

import { useEffect, useMemo, useState } from "react";

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
}

export function ChartDateRangePicker({
  onChange,
  onGranularityChange,
  defaultRange = "1y",
  defaultGranularity = "1day",
}: ChartDateRangePickerProps) {
  const todayStr = useMemo(() => localDateStr(new Date()), []);
  const [granularity, setGranularity] = useState<ChartGranularity>(defaultGranularity);
  const [quickRange, setQuickRange] = useState<QuickRange>(defaultRange);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  const availableRanges = RANGE_BY_GRANULARITY[granularity].ranges;

  function applyQuickRange(range: QuickRange, emit = true) {
    setQuickRange(range);
    if (range === "custom") return;
    const days = RANGE_DAYS[range];
    const end = new Date();
    const start = new Date(end);
    start.setDate(start.getDate() - days);
    const from = localDateStr(start);
    const to = localDateStr(end);
    setDateFrom(from);
    setDateTo(to);
    if (emit) onChange({ from, to });
  }

  useEffect(() => {
    applyQuickRange(defaultRange);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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

  return (
    <div className="flex items-stretch rounded-xl border border-border bg-card overflow-x-auto overflow-y-visible">
      <div className="flex items-center px-3 py-2 border-r border-border shrink-0">
        <span className="text-[10px] font-medium text-muted-foreground/60 uppercase tracking-wide">Range</span>
      </div>
      {availableRanges.map((r) => (
        <button
          key={r}
          onClick={() => applyQuickRange(r)}
          className={`text-[11px] px-3 py-2 transition-colors cursor-pointer border-r border-border ${
            quickRange === r ? "bg-foreground text-background" : "text-muted-foreground hover:text-foreground"
          }`}
        >
          {RANGE_LABELS[r]}
        </button>
      ))}
      <div className="flex items-center gap-1.5 px-3 py-2 border-r border-border shrink-0">
        <input
          type="date"
          value={dateFrom}
          max={dateTo || todayStr}
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
          max={todayStr}
          onChange={(e) => {
            setDateTo(e.target.value);
            setQuickRange("custom");
            if (dateFrom) onChange({ from: dateFrom, to: e.target.value });
          }}
          className="text-[11px] bg-transparent text-foreground focus:outline-none cursor-pointer"
        />
      </div>
      <div className="flex items-center px-3 py-2 shrink-0">
        <span className="text-[10px] font-medium text-muted-foreground/60 uppercase tracking-wide mr-2">Gran</span>
        {GRANULARITY_OPTIONS.map(({ value, label }) => (
          <button
            key={value}
            onClick={() => handleGranularityChange(value)}
            className={`text-[11px] px-2.5 py-1 rounded transition-colors cursor-pointer ${
              granularity === value
                ? "bg-foreground text-background"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            {label}
          </button>
        ))}
      </div>
    </div>
  );
}