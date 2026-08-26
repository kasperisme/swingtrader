"use client";

import { ChevronDown, ChevronUp } from "lucide-react";

export function ScreeningsSortIcon({
  col,
  sortKey,
  sortDir,
}: {
  col: string;
  sortKey: string;
  sortDir: "asc" | "desc";
}) {
  if (sortKey !== col) return null;
  return sortDir === "asc" ? (
    <ChevronUp className="w-3 h-3 inline ml-0.5" />
  ) : (
    <ChevronDown className="w-3 h-3 inline ml-0.5" />
  );
}
