"use client";

/* AESTHETIC DIRECTION
 * Tone:        Dark terminal — sits inside the existing screenings shell.
 * Detail:      A 3px left-border signal strip per row, color-coded by group
 *              (amber = multi-symbol, sky = deep dive, emerald = monitoring).
 *              The trigger button echoes the active group via a single dot.
 * Type:        Plus Jakarta Sans for chrome (loaded globally) + `font-mono`
 *              for tickers, view labels, and small-caps section headers.
 *              Tracking widens from -0.01em (label) → 0.14em (group header).
 * Color:       Theme tokens (border / muted / popover) for surfaces,
 *              amber-500 / sky-500 / emerald-500 as semantic group accents.
 */

import { useEffect, useRef, useState } from "react";
import { Activity, ChevronDown } from "lucide-react";
import {
  SCREENINGS_DEEP_DIVE_TABS,
  SCREENINGS_MULTI_SYMBOL_TABS,
} from "./screenings-view-tab-presets";
import type { ScreeningsPrimaryTabDef, ViewTab } from "./screenings-types";

type GroupKey = "multi" | "deep" | "trades";

const GROUP_DOT: Record<GroupKey, string> = {
  multi: "bg-amber-500",
  deep: "bg-sky-500",
  trades: "bg-emerald-500",
};

const GROUP_BORDER: Record<GroupKey, string> = {
  multi: "border-amber-500",
  deep: "border-sky-500",
  trades: "border-emerald-500",
};

const GROUP_TEXT: Record<GroupKey, string> = {
  multi: "text-amber-500",
  deep: "text-sky-500",
  trades: "text-emerald-500",
};

interface Props {
  activeView: ViewTab;
  onSelect: (v: ViewTab) => void;
  tradeMonitoringDisabled: boolean;
  tradeMonitoringTitle?: string;
}

function resolveActive(view: ViewTab): {
  label: string;
  icon: React.ReactNode;
  group: GroupKey;
} | null {
  const multi = SCREENINGS_MULTI_SYMBOL_TABS.find((t) => t.id === view);
  if (multi) return { label: multi.label, icon: multi.icon, group: "multi" };
  const deep = SCREENINGS_DEEP_DIVE_TABS.find((t) => t.id === view);
  if (deep) return { label: deep.label, icon: deep.icon, group: "deep" };
  if (view === "tradeMonitoring") {
    return {
      label: "Trades",
      icon: <Activity className="w-3.5 h-3.5" />,
      group: "trades",
    };
  }
  return null;
}

export function ScreeningsMobileViewPicker({
  activeView,
  onSelect,
  tradeMonitoringDisabled,
  tradeMonitoringTitle,
}: Props) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!wrapRef.current) return;
      if (!wrapRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("mousedown", onDown);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("mousedown", onDown);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const active = resolveActive(activeView);

  const choose = (v: ViewTab) => {
    onSelect(v);
    setOpen(false);
  };

  return (
    <div ref={wrapRef} className="relative flex-1 min-w-0">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
        className="w-full min-h-[44px] flex items-center gap-2.5 px-3 rounded-md border border-border bg-muted/40 hover:bg-muted/60 transition-colors"
      >
        <span
          className={`shrink-0 w-1.5 h-1.5 rounded-full ${
            active ? GROUP_DOT[active.group] : "bg-muted-foreground"
          }`}
          aria-hidden
        />
        <span
          className="shrink-0 font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground"
          aria-hidden
        >
          View
        </span>
        <span className="min-w-0 flex items-center gap-1.5 truncate">
          {active?.icon ? (
            <span className="shrink-0 text-foreground/80">{active.icon}</span>
          ) : null}
          <span className="font-mono text-[13px] tracking-[-0.01em] text-foreground truncate">
            {active?.label ?? "—"}
          </span>
        </span>
        <ChevronDown
          className={`ml-auto w-4 h-4 text-muted-foreground transition-transform ${
            open ? "rotate-180" : ""
          }`}
        />
      </button>

      {open && (
        <div
          role="menu"
          aria-label="Screening view"
          className="absolute left-0 right-0 top-full mt-1.5 z-50 rounded-lg border border-border bg-popover shadow-2xl overflow-hidden"
        >
          <ViewGroup
            label="Multi-symbol"
            hint="from your filter"
            group="multi"
            tabs={SCREENINGS_MULTI_SYMBOL_TABS}
            activeView={activeView}
            onSelect={choose}
          />
          <div className="h-px bg-border" aria-hidden />
          <ViewGroup
            label="Deep dive"
            hint="one ticker at a time"
            group="deep"
            tabs={SCREENINGS_DEEP_DIVE_TABS}
            activeView={activeView}
            onSelect={choose}
          />
          <div className="h-px bg-border" aria-hidden />
          <SectionHeader label="Monitoring" group="trades" />
          <button
            type="button"
            role="menuitemradio"
            aria-checked={activeView === "tradeMonitoring"}
            disabled={tradeMonitoringDisabled}
            title={tradeMonitoringTitle}
            onClick={() => {
              if (tradeMonitoringDisabled) return;
              choose("tradeMonitoring");
            }}
            className={`w-full min-h-[48px] flex items-center gap-3 pl-3 pr-3 text-left transition-colors border-l-[3px] ${
              activeView === "tradeMonitoring"
                ? `${GROUP_BORDER.trades} bg-muted/40`
                : "border-transparent hover:bg-muted/30"
            } ${tradeMonitoringDisabled ? "opacity-40 cursor-not-allowed" : ""}`}
          >
            <Activity
              className={`w-4 h-4 shrink-0 ${
                activeView === "tradeMonitoring"
                  ? GROUP_TEXT.trades
                  : "text-muted-foreground"
              }`}
            />
            <span
              className={`font-mono text-[13px] tracking-[-0.01em] ${
                activeView === "tradeMonitoring"
                  ? "text-foreground"
                  : "text-foreground/80"
              }`}
            >
              Trades
            </span>
            {tradeMonitoringDisabled ? (
              <span className="ml-auto font-mono text-[9px] uppercase tracking-[0.12em] text-muted-foreground">
                Set pivot first
              </span>
            ) : activeView === "tradeMonitoring" ? (
              <span className="ml-auto font-mono text-[9px] uppercase tracking-[0.12em] text-muted-foreground">
                Active
              </span>
            ) : null}
          </button>
        </div>
      )}
    </div>
  );
}

function SectionHeader({
  label,
  hint,
  group,
}: {
  label: string;
  hint?: string;
  group: GroupKey;
}) {
  return (
    <div className="flex items-center gap-2 px-3 pt-2.5 pb-1">
      <span
        className={`w-[3px] h-3 rounded-sm ${GROUP_DOT[group]}`}
        aria-hidden
      />
      <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
        {label}
      </span>
      {hint ? (
        <span className="text-[10px] text-muted-foreground/60 truncate">
          · {hint}
        </span>
      ) : null}
    </div>
  );
}

function ViewGroup({
  label,
  hint,
  group,
  tabs,
  activeView,
  onSelect,
}: {
  label: string;
  hint: string;
  group: GroupKey;
  tabs: ScreeningsPrimaryTabDef[];
  activeView: ViewTab;
  onSelect: (v: ViewTab) => void;
}) {
  return (
    <div className="pb-1">
      <SectionHeader label={label} hint={hint} group={group} />
      {tabs.map((tab) => {
        const isActive = activeView === tab.id;
        return (
          <button
            key={tab.id}
            type="button"
            role="menuitemradio"
            aria-checked={isActive}
            onClick={() => onSelect(tab.id)}
            className={`w-full min-h-[48px] flex items-center gap-3 pl-3 pr-3 text-left transition-colors border-l-[3px] ${
              isActive
                ? `${GROUP_BORDER[group]} bg-muted/40`
                : "border-transparent hover:bg-muted/30"
            }`}
          >
            <span
              className={`shrink-0 ${
                isActive ? GROUP_TEXT[group] : "text-muted-foreground"
              }`}
            >
              {tab.icon}
            </span>
            <span
              className={`font-mono text-[13px] tracking-[-0.01em] ${
                isActive ? "text-foreground" : "text-foreground/80"
              }`}
            >
              {tab.label}
            </span>
            {isActive ? (
              <span className="ml-auto font-mono text-[9px] uppercase tracking-[0.12em] text-muted-foreground">
                Active
              </span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}
