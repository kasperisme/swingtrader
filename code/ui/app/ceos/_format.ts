/** Shared formatting for the CEO pages. Fixed locale: the pages are prerendered. */

const USD_COMPACT = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  notation: "compact",
  maximumFractionDigits: 1,
});

const USD_FULL = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
});

export function fmtUsdCompact(n: number | null | undefined): string {
  return n == null || !Number.isFinite(n) ? "—" : USD_COMPACT.format(n);
}

export function fmtUsd(n: number | null | undefined): string {
  return n == null || !Number.isFinite(n) ? "—" : USD_FULL.format(n);
}

/** Pay in its own currency when FMP says it is not USD, never silently relabelled. */
export function fmtPay(n: number | null | undefined, currency: string | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return "—";
  const cur = (currency || "USD").toUpperCase();
  if (cur === "USD") return USD_COMPACT.format(n);
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: cur,
      notation: "compact",
      maximumFractionDigits: 1,
    }).format(n);
  } catch {
    return `${USD_COMPACT.format(n).replace("$", "")} ${cur}`;
  }
}
