import { NextRequest, NextResponse } from "next/server";

function getNewYorkOffsetMinutes(utcDate: Date): number {
  // Extract wall-clock components for America/New_York via formatToParts,
  // then rebuild as a UTC instant to diff against the real UTC time.
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/New_York",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).formatToParts(utcDate);
  const get = (type: string) => Number(parts.find((p) => p.type === type)?.value ?? 0);
  const nyMs = Date.UTC(
    get("year"), get("month") - 1, get("day"),
    get("hour") % 24, get("minute"), get("second"),
  );
  return Math.round((nyMs - utcDate.getTime()) / 60_000);
}

/**
 * Given a naive ET datetime string from FMP (e.g. "2026-04-08 15:30:00"),
 * appends the America/New_York UTC offset so the caller knows the timezone
 * without any UTC conversion, e.g. "2026-04-08T15:30:00-04:00".
 *
 * If the string already carries timezone info it is left unchanged.
 */
function appendEtOffset(dateLike: string): string {
  // Already timezone-aware — return as-is.
  if (/[zZ]|[+-]\d{2}:\d{2}$/.test(dateLike)) return dateLike;

  const m = dateLike.match(
    /^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2})(?::(\d{2}))?)?$/,
  );
  if (!m) return dateLike;

  const year   = Number.parseInt(m[1], 10);
  const month  = Number.parseInt(m[2], 10);
  const day    = Number.parseInt(m[3], 10);
  const hour   = Number.parseInt(m[4] ?? "0", 10);
  const minute = Number.parseInt(m[5] ?? "0", 10);
  const second = Number.parseInt(m[6] ?? "0", 10);

  // Use the naive local time as a proxy UTC instant to resolve the ET offset
  // (close enough for DST determination away from transition boundaries).
  const naiveMs = Date.UTC(year, month - 1, day, hour, minute, second);
  const offsetMinutes = getNewYorkOffsetMinutes(new Date(naiveMs));
  const sign = offsetMinutes >= 0 ? "+" : "-";
  const absMin = Math.abs(offsetMinutes);
  const offsetStr = `${sign}${String(Math.floor(absMin / 60)).padStart(2, "0")}:${String(absMin % 60).padStart(2, "0")}`;

  const hh = String(hour).padStart(2, "0");
  const mm = String(minute).padStart(2, "0");
  const ss = String(second).padStart(2, "0");
  return `${m[1]}-${m[2]}-${m[3]}T${hh}:${mm}:${ss}${offsetStr}`;
}

export async function GET(req: NextRequest) {
  const symbolParam = req.nextUrl.searchParams.get("symbol");
  const interval = req.nextUrl.searchParams.get("interval") ?? "1day";
  if (!symbolParam) {
    return NextResponse.json({ error: "symbol required" }, { status: 400 });
  }

  // Handle both normal and accidentally double-encoded symbols.
  let symbol = symbolParam.trim();
  for (let i = 0; i < 2; i++) {
    try {
      const decoded = decodeURIComponent(symbol);
      if (decoded === symbol) break;
      symbol = decoded;
    } catch {
      break;
    }
  }

  // Enforce literal S&P 500 ticker for upstream FMP requests.
  if (symbol.replace(/^\^/, "").toUpperCase() === "GSPC") {
    symbol = "^GSPC";
  }

  const apiKey = process.env.FMP_API_KEY;
  if (!apiKey) {
    return NextResponse.json(
      { error: "FMP_API_KEY not configured" },
      { status: 500 },
    );
  }

  const now = new Date();
  const symbolCandidates = Array.from(
    new Set([
      symbol,
      symbol === "^GSPC"
        ? "GSPC"
        : symbol.startsWith("^")
          ? symbol.slice(1)
          : symbol,
    ]),
  );

  const from = new Date(now);
  const toStr = now.toISOString().split("T")[0];
  let fromStr = "";
  if (interval === "1hour") {
    from.setMonth(from.getMonth() - 6);
  } else {
    from.setFullYear(from.getFullYear() - 1);
  }
  fromStr = from.toISOString().split("T")[0];

  let historical: unknown[] = [];
  let fetched = false;
  for (const candidate of symbolCandidates) {
    const url =
      interval === "1hour"
        ? `https://financialmodelingprep.com/stable/historical-chart/1hour?symbol=${candidate}&from=${fromStr}&to=${toStr}&apikey=${encodeURIComponent(apiKey)}`
        : `https://financialmodelingprep.com/api/v3/historical-price-full/${candidate}?from=${fromStr}&to=${toStr}&apikey=${encodeURIComponent(apiKey)}`;

    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) continue;

    const data = await res.json();
    const rows: unknown[] = Array.isArray(data)
      ? data
      : (data?.historical ?? []);
    if (rows.length === 0) continue;
    historical = rows;
    fetched = true;
    break;
  }

  if (!fetched) {
    return NextResponse.json({ error: "FMP request failed" }, { status: 502 });
  }

  const normalized = historical
    .map((row: unknown) => {
      if (row == null || typeof row !== "object") return null;
      const r = row as Record<string, unknown>;
      const dateRaw = r.date ?? r.label;
      if (dateRaw == null) return null;
      const dateStr = String(dateRaw);
      const normalizedDate =
        interval === "1hour" ? appendEtOffset(dateStr) : dateStr;
      return {
        date: normalizedDate,
        open: Number(r.open),
        high: Number(r.high),
        low: Number(r.low),
        close: Number(r.close),
        volume: Number(r.volume),
      };
    })
    .filter(
      (b): b is NonNullable<typeof b> => b != null && Number.isFinite(b.close),
    );

  const sorted = [...normalized].sort(
    (a, b) => new Date(a.date).getTime() - new Date(b.date).getTime(),
  );
  return NextResponse.json(sorted);
}
