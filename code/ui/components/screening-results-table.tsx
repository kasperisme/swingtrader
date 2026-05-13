"use client";

import { useEffect, useMemo, useState } from "react";
import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  Check,
  ChevronLeft,
  ChevronRight,
  Search,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import {
  collectAllRowDataKeys,
  compareRowDataValues,
  isBooleanColumn,
  isNumericColumn,
  orderedDataColumnKeys,
} from "@/app/protected/screenings/screenings-row-data";

/**
 * Slim, screen-agnostic row shape. Both user_scan_rows and
 * public_screening_result_rows can be projected into this.
 */
export type BasicScreeningRow = {
  id: string | number;
  symbol: string | null;
  rowData: Record<string, unknown>;
};

type SortDir = "asc" | "desc";

const SYMBOL_COLUMN = "__symbol";
const DEFAULT_SORT_KEY = "RS_Rank";
const COLLAPSED_PAGE_SIZE = 10;
const EXPANDED_PAGE_SIZE = 25;

type Props = {
  rows: BasicScreeningRow[];
  /** Optional fixed list of columns to show. If omitted, columns are
   *  inferred from row_data and ordered by ROW_DATA_COLUMN_PRIORITY. */
  columns?: string[];
  /** Hide the search input. */
  hideSearch?: boolean;
  /** Empty-state message. */
  emptyLabel?: string;
};

function formatHeader(key: string): string {
  return key
    .replace(/_/g, " ")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function formatValue(v: unknown, isBoolCol: boolean): React.ReactNode {
  if (v === null || v === undefined || v === "") return <span className="text-muted-foreground">—</span>;
  if (typeof v === "boolean") {
    return v ? (
      <Check className="inline h-3.5 w-3.5 text-emerald-500" aria-label="Yes" />
    ) : (
      <X className="inline h-3.5 w-3.5 text-muted-foreground/60" aria-label="No" />
    );
  }
  if (isBoolCol) {
    // Boolean column but value isn't a JS boolean — coerce loosely.
    const truthy = v === true || v === 1 || v === "true" || v === "1";
    return truthy ? (
      <Check className="inline h-3.5 w-3.5 text-emerald-500" />
    ) : (
      <X className="inline h-3.5 w-3.5 text-muted-foreground/60" />
    );
  }
  if (typeof v === "number") {
    return Number.isInteger(v) ? v.toLocaleString() : v.toFixed(2);
  }
  return String(v);
}

export function ScreeningResultsTable({
  rows,
  columns,
  hideSearch = false,
  emptyLabel = "No rows yet.",
}: Props) {
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState<string>(DEFAULT_SORT_KEY);
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [expanded, setExpanded] = useState(false);
  const [page, setPage] = useState(0);

  const allKeys = useMemo(() => collectAllRowDataKeys(rows), [rows]);
  const dataColumns = useMemo(
    () => columns ?? orderedDataColumnKeys(allKeys),
    [columns, allKeys],
  );

  const boolColumns = useMemo(() => {
    const set = new Set<string>();
    for (const k of dataColumns) if (isBooleanColumn(rows, k)) set.add(k);
    return set;
  }, [dataColumns, rows]);

  const numericColumns = useMemo(() => {
    const set = new Set<string>();
    for (const k of dataColumns) if (isNumericColumn(rows, k)) set.add(k);
    return set;
  }, [dataColumns, rows]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter((r) => (r.symbol ?? "").toLowerCase().includes(q));
  }, [rows, search]);

  const sorted = useMemo(() => {
    const out = [...filtered];
    out.sort((a, b) => {
      let av: unknown;
      let bv: unknown;
      if (sortKey === SYMBOL_COLUMN) {
        av = a.symbol ?? "";
        bv = b.symbol ?? "";
      } else {
        av = a.rowData[sortKey];
        bv = b.rowData[sortKey];
      }
      const cmp = compareRowDataValues(av, bv);
      return sortDir === "asc" ? cmp : -cmp;
    });
    return out;
  }, [filtered, sortKey, sortDir]);

  // Pagination: collapsed → first 10 only; expanded → 25 per page with
  // prev/next controls for the remainder.
  const pageSize = expanded ? EXPANDED_PAGE_SIZE : COLLAPSED_PAGE_SIZE;
  const totalPages = Math.max(1, Math.ceil(sorted.length / pageSize));
  const safePage = Math.min(page, totalPages - 1);

  useEffect(() => {
    // Filter / sort / collapse changes invalidate the current page index.
    setPage(0);
  }, [search, sortKey, sortDir, expanded]);

  const visible = expanded
    ? sorted.slice(safePage * pageSize, (safePage + 1) * pageSize)
    : sorted.slice(0, COLLAPSED_PAGE_SIZE);

  const hiddenWhenCollapsed = sorted.length - COLLAPSED_PAGE_SIZE;
  const windowStart = expanded ? safePage * pageSize + 1 : 1;
  const windowEnd = expanded
    ? safePage * pageSize + visible.length
    : visible.length;

  const onHeaderClick = (key: string) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      // Numerics default descending (RS Rank, EPS growth, etc.); strings ascending.
      setSortDir(numericColumns.has(key) || key === SYMBOL_COLUMN ? "desc" : "asc");
    }
  };

  if (rows.length === 0) {
    return <p className="text-sm text-muted-foreground">{emptyLabel}</p>;
  }

  return (
    <div className="space-y-3">
      {!hideSearch && (
        <div className="relative max-w-xs">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search symbol…"
            className="pl-8 h-9"
          />
        </div>
      )}

      <div className="overflow-x-auto rounded-md border border-border">
        <table className="min-w-full text-xs">
          <thead className="bg-muted/40">
            <tr>
              <HeaderCell
                label="Symbol"
                isSorted={sortKey === SYMBOL_COLUMN}
                dir={sortDir}
                onClick={() => onHeaderClick(SYMBOL_COLUMN)}
                sticky
              />
              {dataColumns.map((key) => (
                <HeaderCell
                  key={key}
                  label={formatHeader(key)}
                  isSorted={sortKey === key}
                  dir={sortDir}
                  onClick={() => onHeaderClick(key)}
                  align={
                    numericColumns.has(key)
                      ? "right"
                      : boolColumns.has(key)
                        ? "center"
                        : "left"
                  }
                />
              ))}
            </tr>
          </thead>
          <tbody>
            {visible.map((r) => (
              <tr
                key={r.id}
                className="border-t border-border/70 hover:bg-muted/30"
              >
                <td className="px-3 py-2 font-medium sticky left-0 bg-background">
                  {r.symbol ?? "—"}
                </td>
                {dataColumns.map((key) => (
                  <td
                    key={key}
                    className={cn(
                      "px-3 py-2 whitespace-nowrap",
                      numericColumns.has(key) && "text-right tabular-nums",
                      boolColumns.has(key) && "text-center",
                    )}
                  >
                    {formatValue(r.rowData[key], boolColumns.has(key))}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-xs text-muted-foreground">
          {sorted.length === 0
            ? "No matching rows"
            : expanded
              ? `Showing ${windowStart}–${windowEnd} of ${sorted.length}`
              : `Showing ${windowEnd} of ${sorted.length}`}
        </p>

        {!expanded && hiddenWhenCollapsed > 0 && (
          <Button
            variant="outline"
            size="sm"
            onClick={() => setExpanded(true)}
          >
            Show more ({hiddenWhenCollapsed} more)
          </Button>
        )}

        {expanded && totalPages > 1 && (
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={safePage === 0}
              aria-label="Previous page"
            >
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <span className="text-xs text-muted-foreground tabular-nums min-w-[5rem] text-center">
              Page {safePage + 1} of {totalPages}
            </span>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
              disabled={safePage >= totalPages - 1}
              aria-label="Next page"
            >
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}

function HeaderCell({
  label,
  isSorted,
  dir,
  onClick,
  align = "left",
  sticky = false,
}: {
  label: string;
  isSorted: boolean;
  dir: SortDir;
  onClick: () => void;
  align?: "left" | "right" | "center";
  sticky?: boolean;
}) {
  const Icon = !isSorted ? ArrowUpDown : dir === "asc" ? ArrowUp : ArrowDown;
  return (
    <th
      onClick={onClick}
      className={cn(
        "px-3 py-2 font-medium cursor-pointer select-none",
        align === "right" && "text-right",
        align === "center" && "text-center",
        sticky && "sticky left-0 bg-muted/40 z-10",
      )}
    >
      <span
        className={cn(
          "inline-flex items-center gap-1.5",
          align === "right" && "justify-end w-full",
          align === "center" && "justify-center w-full",
        )}
      >
        {label}
        <Icon
          className={cn(
            "h-3 w-3 shrink-0",
            isSorted ? "text-foreground" : "text-muted-foreground/50",
          )}
        />
      </span>
    </th>
  );
}
