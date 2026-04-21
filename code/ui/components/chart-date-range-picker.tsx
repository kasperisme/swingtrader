"use client";

import { useEffect, useMemo, useState } from "react";

export type QuickRange = "7d" | "30d" | "90d" | "1y" | "3y" | "custom";

const pad2 = (n: number) => String(n).padStart(2, "0");
function localDateStr(d: Date) {
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
}

interface ChartDateRangePickerProps {
  onChange: (range: { from: string; to: string }) => void;
  defaultRange?: QuickRange;
}

export function ChartDateRangePicker({ onChange, defaultRange = "1y" }: ChartDateRangePickerProps) {
  const todayStr = useMemo(() => localDateStr(new Date()), []);
  const [quickRange, setQuickRange] = useState<QuickRange>(defaultRange);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  function applyQuickRange(range: QuickRange) {
    setQuickRange(range);
    if (range === "custom") return;
    const days =
      range === "7d" ? 7 : range === "30d" ? 30 : range === "90d" ? 90 : range === "1y" ? 365 : 365 * 3;
    const end = new Date();
    const start = new Date(end);
    start.setDate(start.getDate() - days);
    const from = localDateStr(start);
    const to = localDateStr(end);
    setDateFrom(from);
    setDateTo(to);
    onChange({ from, to });
  }

  useEffect(() => {
    applyQuickRange(defaultRange);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="flex items-stretch rounded-xl border border-border bg-card overflow-x-auto overflow-y-visible">
      <div className="flex items-center px-3 py-2 border-r border-border shrink-0">
        <span className="text-[10px] font-medium text-muted-foreground/60 uppercase tracking-wide">Range</span>
      </div>
      {(["7d", "30d", "90d", "1y", "3y"] as QuickRange[]).map((r) => (
        <button
          key={r}
          onClick={() => applyQuickRange(r)}
          className={`text-[11px] px-3 py-2 transition-colors cursor-pointer border-r border-border ${
            quickRange === r ? "bg-foreground text-background" : "text-muted-foreground hover:text-foreground"
          }`}
        >
          {r}
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
    </div>
  );
}
