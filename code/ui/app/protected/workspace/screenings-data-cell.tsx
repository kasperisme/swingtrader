"use client";

import { CheckCircle, XCircle } from "lucide-react";

export function Check({ value }: { value: boolean | null | undefined }) {
  if (value == null)
    return <span className="text-muted-foreground/40 text-xs">—</span>;
  return value ? (
    <CheckCircle className="w-4 h-4 text-emerald-500 shrink-0" />
  ) : (
    <XCircle className="w-4 h-4 text-rose-400 shrink-0" />
  );
}

export function Num({
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
    ? value >= 0
      ? "text-emerald-600 dark:text-emerald-400"
      : "text-rose-500"
    : "";
  return <span className={`tabular-nums ${color}`}>{formatted}</span>;
}

export function RsBadge({ rank }: { rank: number | null }) {
  if (rank == null) return <span className="text-muted-foreground">—</span>;
  const color =
    rank >= 90
      ? "bg-emerald-500/20 text-emerald-600 dark:text-emerald-400"
      : rank >= 70
        ? "bg-amber-500/20 text-amber-600 dark:text-amber-400"
        : "bg-muted text-muted-foreground";
  return (
    <span
      className={`inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium tabular-nums ${color}`}
    >
      {rank}
    </span>
  );
}

export function DataCell({ colKey, value }: { colKey: string; value: unknown }) {
  if (value === undefined || value === null) {
    return <span className="text-muted-foreground/40 text-xs">—</span>;
  }
  if (colKey === "RS_Rank" || colKey === "rs_rank") {
    const n = typeof value === "number" ? value : parseFloat(String(value));
    return <RsBadge rank={Number.isFinite(n) ? n : null} />;
  }
  if (typeof value === "boolean") {
    return (
      <div className="flex justify-center">
        <Check value={value} />
      </div>
    );
  }
  if (typeof value === "number") {
    if (Number.isInteger(value)) {
      return <span className="tabular-nums text-xs">{value}</span>;
    }
    return <span className="tabular-nums text-xs">{value.toFixed(3)}</span>;
  }
  if (typeof value === "string") {
    const t = value.trim();
    if (!t) return <span className="text-muted-foreground/40 text-xs">—</span>;
    return (
      <span
        className="text-xs max-w-[140px] truncate inline-block align-bottom"
        title={t}
      >
        {t}
      </span>
    );
  }
  if (typeof value === "object") {
    let s: string;
    try {
      s = JSON.stringify(value);
    } catch {
      s = "[object]";
    }
    return (
      <span
        className="text-[10px] font-mono text-muted-foreground max-w-[120px] truncate inline-block align-bottom"
        title={s}
      >
        {s.length > 56 ? `${s.slice(0, 56)}…` : s}
      </span>
    );
  }
  return <span className="text-xs">{String(value)}</span>;
}