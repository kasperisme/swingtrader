import { NextResponse } from "next/server";
import {
  getLatestPublicScreeningResultRows,
  getPublicScreeningBySlug,
  recordPublicScreeningDownload,
} from "@/app/actions/public-screenings";
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

export async function GET(
  _req: Request,
  ctx: { params: Promise<{ slug: string }> },
) {
  const { slug } = await ctx.params;

  const screening = await getPublicScreeningBySlug(slug);
  if (!screening) {
    return new NextResponse("Screening not found", { status: 404 });
  }

  const { rows, runAt } = await getLatestPublicScreeningResultRows(screening.id);
  if (rows.length === 0) {
    return new NextResponse("No results yet for this screening.", { status: 404 });
  }

  // Use the same column discovery as the on-page table so the file shape
  // matches what the user sees in the UI.
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

  const datePart = runAt
    ? new Date(runAt).toISOString().slice(0, 10)
    : new Date().toISOString().slice(0, 10);
  const filename = `${screening.slug}-${datePart}.csv`;

  // BOM + CSV so Excel opens UTF-8 cleanly.
  const body = "﻿" + lines.join("\r\n") + "\r\n";

  // Best-effort: bump the DB counter and fire a PostHog event. Awaited so
  // the increment is durable before we close the response; recorder swallows
  // its own errors so a slow PH or RPC never breaks the download.
  await recordPublicScreeningDownload({
    screeningId: screening.id,
    screeningSlug: screening.slug,
    screeningName: screening.name,
  });

  return new NextResponse(body, {
    status: 200,
    headers: {
      "Content-Type": "text/csv; charset=utf-8",
      "Content-Disposition": `attachment; filename="${filename}"`,
      "Cache-Control": "no-store",
    },
  });
}
