"use server";

export type FmpOhlcBar = {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
};

export type FmpPriceAtDateResult = {
  price: number;
  source: "historical" | "quote";
  asOfDate: string;
};

export type FmpActionError = { ok: false; error: string };
export type FmpOhlcSuccess = { ok: true; data: FmpOhlcBar[] };
export type FmpQuoteSuccess = { ok: true; data: unknown };
export type FmpSearchSuccess = { ok: true; data: unknown[] };
export type FmpPriceAtDateSuccess = { ok: true; data: FmpPriceAtDateResult };

function getNewYorkOffsetMinutes(utcDate: Date): number {
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
    get("year"),
    get("month") - 1,
    get("day"),
    get("hour") % 24,
    get("minute"),
    get("second"),
  );
  return Math.round((nyMs - utcDate.getTime()) / 60_000);
}

function appendEtOffset(dateLike: string): string {
  if (/[zZ]|[+-]\d{2}:\d{2}$/.test(dateLike)) return dateLike;

  const m = dateLike.match(
    /^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2})(?::(\d{2}))?)?$/,
  );
  if (!m) return dateLike;

  const year = Number.parseInt(m[1], 10);
  const month = Number.parseInt(m[2], 10);
  const day = Number.parseInt(m[3], 10);
  const hour = Number.parseInt(m[4] ?? "0", 10);
  const minute = Number.parseInt(m[5] ?? "0", 10);
  const second = Number.parseInt(m[6] ?? "0", 10);

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

function normalizeSymbolInput(symbolParam: string): string {
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
  if (symbol.replace(/^\^/, "").toUpperCase() === "GSPC") {
    symbol = "^GSPC";
  }
  return symbol;
}

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const MAX_SEARCH_QUERY_LEN = 80;

function subtractCalendarDays(ymd: string, days: number): string {
  const [y, m, d] = ymd.split("-").map((x) => Number.parseInt(x, 10));
  if (!Number.isFinite(y) || !Number.isFinite(m) || !Number.isFinite(d)) return ymd;
  const ms = Date.UTC(y, m - 1, d) - days * 86_400_000;
  return new Date(ms).toISOString().slice(0, 10);
}

function pickHistoricalClose(
  rows: { date: string; close: unknown }[],
  dateStr: string,
): { close: number; asOfDate: string } | null {
  const eligible = rows.filter((h) => {
    if (typeof h.date !== "string" || h.date > dateStr) return false;
    const c = typeof h.close === "number" ? h.close : Number(h.close);
    return Number.isFinite(c);
  });
  if (eligible.length === 0) return null;
  eligible.sort((a, b) => b.date.localeCompare(a.date));
  const top = eligible[0];
  const close = typeof top.close === "number" ? top.close : Number(top.close);
  return { close, asOfDate: top.date };
}

export async function fmpGetOhlc(
  symbolParam: string,
  intervalRaw?: string,
): Promise<FmpOhlcSuccess | FmpActionError> {
  if (!symbolParam?.trim()) {
    return { ok: false, error: "symbol required" };
  }

  const interval = intervalRaw === "1hour" ? "1hour" : "1day";
  const symbol = normalizeSymbolInput(symbolParam);

  const apiKey = process.env.FMP_API_KEY;
  if (!apiKey) {
    return { ok: false, error: "FMP_API_KEY not configured" };
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
    const rows: unknown[] = Array.isArray(data) ? data : (data?.historical ?? []);
    if (rows.length === 0) continue;
    historical = rows;
    fetched = true;
    break;
  }

  if (!fetched) {
    return { ok: false, error: "FMP request failed" };
  }

  const normalized = historical
    .map((row: unknown) => {
      if (row == null || typeof row !== "object") return null;
      const r = row as Record<string, unknown>;
      const dateRaw = r.date ?? r.label;
      if (dateRaw == null) return null;
      const dateStr = String(dateRaw);
      const normalizedDate = interval === "1hour" ? appendEtOffset(dateStr) : dateStr;
      return {
        date: normalizedDate,
        open: Number(r.open),
        high: Number(r.high),
        low: Number(r.low),
        close: Number(r.close),
        volume: Number(r.volume),
      };
    })
    .filter((b): b is NonNullable<typeof b> => b != null && Number.isFinite(b.close));

  const sorted = [...normalized].sort(
    (a, b) => new Date(a.date).getTime() - new Date(b.date).getTime(),
  );
  return { ok: true, data: sorted };
}

export async function fmpGetQuote(symbol: string): Promise<FmpQuoteSuccess | FmpActionError> {
  if (!symbol?.trim()) {
    return { ok: false, error: "symbol required" };
  }

  const apiKey = process.env.FMP_API_KEY;
  if (!apiKey) {
    return { ok: false, error: "FMP_API_KEY not configured" };
  }

  const url = `https://financialmodelingprep.com/stable/quote?symbol=${encodeURIComponent(symbol.trim())}&apikey=${apiKey}`;
  const res = await fetch(url, { next: { revalidate: 60 } });
  if (!res.ok) {
    return { ok: false, error: "FMP request failed" };
  }

  const data: unknown = await res.json();
  return { ok: true, data };
}

export async function fmpSearchSymbol(query: string): Promise<FmpSearchSuccess | FmpActionError> {
  const trimmed = query.trim();
  if (trimmed.length < 1) {
    return { ok: false, error: "query required" };
  }
  if (trimmed.length > MAX_SEARCH_QUERY_LEN) {
    return { ok: false, error: "query too long" };
  }

  const apiKey = process.env.FMP_API_KEY;
  if (!apiKey) {
    return { ok: false, error: "FMP_API_KEY not configured" };
  }

  const url = `https://financialmodelingprep.com/stable/search-symbol?query=${encodeURIComponent(trimmed)}&apikey=${encodeURIComponent(apiKey)}`;
  const res = await fetch(url, { next: { revalidate: 120 } });
  if (!res.ok) {
    return { ok: false, error: "FMP request failed" };
  }

  const data: unknown = await res.json();
  if (!Array.isArray(data)) {
    return { ok: false, error: "Unexpected FMP response" };
  }

  return { ok: true, data };
}

export async function fmpGetPriceAtDate(
  symbolParam: string,
  dateStr: string,
): Promise<FmpPriceAtDateSuccess | FmpActionError> {
  if (!symbolParam?.trim()) {
    return { ok: false, error: "symbol required" };
  }
  if (!dateStr || !DATE_RE.test(dateStr)) {
    return { ok: false, error: "date must be YYYY-MM-DD" };
  }

  const symbol = normalizeSymbolInput(symbolParam);
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

  const apiKey = process.env.FMP_API_KEY;
  if (!apiKey) {
    return { ok: false, error: "FMP_API_KEY not configured" };
  }

  const fromStr = subtractCalendarDays(dateStr, 60);

  for (const candidate of symbolCandidates) {
    const histUrl = `https://financialmodelingprep.com/api/v3/historical-price-full/${encodeURIComponent(candidate)}?from=${fromStr}&to=${dateStr}&apikey=${encodeURIComponent(apiKey)}`;
    const histRes = await fetch(histUrl, { next: { revalidate: 300 } });
    if (!histRes.ok) continue;

    const histJson: unknown = await histRes.json();
    const historical = Array.isArray(histJson)
      ? histJson
      : typeof histJson === "object" &&
          histJson !== null &&
          Array.isArray((histJson as { historical?: unknown }).historical)
        ? (histJson as { historical: { date: string; close: unknown }[] }).historical
        : [];

    const picked = pickHistoricalClose(historical, dateStr);
    if (picked) {
      return {
        ok: true,
        data: {
          price: picked.close,
          source: "historical" as const,
          asOfDate: picked.asOfDate,
        },
      };
    }
  }

  for (const candidate of symbolCandidates) {
    const quoteUrl = `https://financialmodelingprep.com/stable/quote?symbol=${encodeURIComponent(candidate)}&apikey=${encodeURIComponent(apiKey)}`;
    const quoteRes = await fetch(quoteUrl, { next: { revalidate: 60 } });
    if (!quoteRes.ok) continue;
    const quoteJson: unknown = await quoteRes.json();
    const row = Array.isArray(quoteJson) ? quoteJson[0] : null;
    if (
      row &&
      typeof row === "object" &&
      row !== null &&
      typeof (row as { price?: unknown }).price === "number" &&
      Number.isFinite((row as { price: number }).price)
    ) {
      const price = (row as { price: number }).price;
      return {
        ok: true,
        data: {
          price,
          source: "quote" as const,
          asOfDate: dateStr,
        },
      };
    }
  }

  return { ok: false, error: "No price data for symbol/date" };
}
