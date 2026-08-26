import type { ScreeningRow } from "./screenings-types";

export const TECH_CRITERIA: {
  key: keyof ScreeningRow;
  short: string;
  label: string;
}[] = [
  {
    key: "PriceOverSMA150And200",
    short: "P>SMA",
    label: "Price > SMA150 & SMA200",
  },
  { key: "SMA150AboveSMA200", short: "150>200", label: "SMA150 > SMA200" },
  {
    key: "SMA50AboveSMA150And200",
    short: "50>150",
    label: "SMA50 > SMA150 & SMA200",
  },
  { key: "SMA200Slope", short: "200↗", label: "SMA200 Uptrending" },
  {
    key: "PriceAbove25Percent52WeekLow",
    short: ">Low",
    label: "Price > 52wk Low +25%",
  },
  {
    key: "PriceWithin25Percent52WeekHigh",
    short: "<High",
    label: "Price within 25% of 52wk High",
  },
  { key: "RSOver70", short: "RS>70", label: "RS > 70" },
];

/** Short label for results table header (technical keys → acronym, row_data keys → truncated key). */
export function screeningsColumnHeaderShort(key: string): string {
  const tech = TECH_CRITERIA.find((t) => t.key === key);
  if (tech) return tech.short;
  if (key.length > 20) return `${key.slice(0, 18)}…`;
  return key;
}
