import {
  getLatestMarketScreeningResultRows,
} from "@/app/actions/market-screenings";
import {
  collectAllRowDataKeys,
  orderedDataColumnKeys,
} from "@/app/protected/screenings/screenings-row-data";

function csvCell(value: unknown): string {
  if (value === null || value === undefined) return "";
  let str: string;
  if (typeof value === "string") str = value;
  else if (typeof value === "number" || typeof value === "boolean") str = String(value);
  else {
    try {
      str = JSON.stringify(value);
    } catch {
      str = String(value);
    }
  }
  // RFC 4180: wrap in quotes if it contains , " \n \r; double up any quotes.
  if (/[",\r\n]/.test(str)) {
    return `"${str.replace(/"/g, '""')}"`;
  }
  return str;
}

function formatHeader(key: string): string {
  return key
    .replace(/_/g, " ")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export type ScreeningCsv = {
  /** CSV text (no BOM — suitable for an email attachment). */
  content: string;
  rowCount: number;
  runAt: string | null;
};

/**
 * Build the latest-results CSV for a screening, matching the on-page table /
 * download-route column shape. Returns null if there are no results yet so the
 * caller can send the confirmation email without an attachment.
 */
export async function buildLatestResultsCsv(
  screeningId: string,
): Promise<ScreeningCsv | null> {
  const { rows, runAt } = await getLatestMarketScreeningResultRows(screeningId);
  if (rows.length === 0) return null;

  const basicRows = rows.map((r) => ({ rowData: r.rowData }));
  const dataColumns = orderedDataColumnKeys(collectAllRowDataKeys(basicRows));
  const header = ["Symbol", ...dataColumns.map(formatHeader)];

  const lines: string[] = [header.map(csvCell).join(",")];
  for (const r of rows) {
    lines.push(
      [
        csvCell(r.symbol ?? ""),
        ...dataColumns.map((k) => csvCell(r.rowData[k])),
      ].join(","),
    );
  }

  return {
    content: lines.join("\r\n") + "\r\n",
    rowCount: rows.length,
    runAt,
  };
}
