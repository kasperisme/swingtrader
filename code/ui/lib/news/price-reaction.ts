import "server-only";
import { cacheLife, cacheTag } from "next/cache";
import { connection } from "next/server";

import { fmpGetOhlc, fmpGetQuote, type FmpOhlcBar } from "@/app/actions/fmp";
import { subtractCalendarDays } from "@/lib/fmp-date-utils";

/**
 * How the stock has actually moved since a story ran — the other half of
 * "expected −0.20". The commonest reason to open a stock article is to explain
 * a move, and the page had no idea the stock had a price.
 *
 * The baseline is the last regular-session close AT OR BEFORE publication, so
 * the move is everything the market did after it could have read the piece:
 *
 *   published Mon 01:48 ET (pre-market) → baseline Fri close; Monday is session 1
 *   published Mon 11:00 ET (intraday)   → baseline Fri close; the morning before
 *                                         publication is included — unavoidable
 *                                         with daily bars, and small next to a day
 *   published Mon 17:30 ET (after close) → baseline Mon close; Tuesday is session 1
 *
 * Raw, not market-adjusted: a −0.20 name up 3% on a +2% tape reads "agrees" when
 * it barely moved relative to anything. Stated on the page rather than hidden.
 */

export type PriceReaction =
  | {
      status: "pending";
      ticker: string;
      /** The latest price — the close the market will open against. */
      lastPrice: number;
      lastDate: string;
    }
  | {
      status: "moved";
      ticker: string;
      refClose: number;
      refDate: string;
      price: number;
      movePct: number;
      /** Regular sessions traded since publication (≥1). */
      sessions: number;
      /** "today" = the first session after publication is the current one. */
      window: "today" | "since";
    };

const CLOSE_MINUTES_ET = 16 * 60;

function etParts(d: Date): { date: string; minutes: number } {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/New_York",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(d);
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "00";
  return {
    date: `${get("year")}-${get("month")}-${get("day")}`,
    minutes: (Number(get("hour")) % 24) * 60 + Number(get("minute")),
  };
}

async function cachedDailyBars(symbol: string, from: string, to: string): Promise<FmpOhlcBar[]> {
  "use cache";
  // The last bar moves intraday; everything before it is settled. `to` is in
  // the key, so the window rolls over at the ET date change on its own.
  cacheLife("minutes");
  cacheTag(`quote:${symbol}`);
  const res = await fmpGetOhlc(symbol, "1day", { from, to });
  if (!res.ok) throw new Error(res.error);
  return res.data;
}

function num(v: unknown): number | null {
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

export async function getPriceReaction(
  ticker: string,
  publishedIso: string,
): Promise<PriceReaction | null> {
  // "Now" and the live quote are per-request by definition.
  await connection();
  const pub = new Date(publishedIso);
  if (Number.isNaN(pub.getTime())) return null;
  const symbol = ticker.trim().toUpperCase();

  const pubEt = etParts(pub);
  const todayEt = etParts(new Date()).date;

  let bars: FmpOhlcBar[] = [];
  const [quoteRes] = await Promise.all([
    fmpGetQuote(symbol),
    cachedDailyBars(symbol, subtractCalendarDays(pubEt.date, 10), todayEt)
      .then((b) => {
        bars = b;
      })
      .catch(() => {}),
  ]);
  if (!quoteRes.ok || !Array.isArray(quoteRes.data)) return null;
  const q = (quoteRes.data[0] ?? null) as Record<string, unknown> | null;
  const price = num(q?.price);
  if (price == null || price <= 0) return null;
  const ts = num(q?.timestamp);
  const lastTrade = ts != null ? new Date(ts * 1000) : null;

  // Baseline: the last close the market printed before it could read the piece.
  const ref = bars
    .filter((b) => b.date < pubEt.date || (b.date === pubEt.date && pubEt.minutes >= CLOSE_MINUTES_ET))
    .at(-1);
  if (!ref || !(ref.close > 0)) return null;

  if (!lastTrade || lastTrade.getTime() <= pub.getTime()) {
    return {
      status: "pending",
      ticker: symbol,
      lastPrice: price,
      lastDate: lastTrade ? etParts(lastTrade).date : ref.date,
    };
  }

  const lastTradeDate = etParts(lastTrade).date;
  const traded = new Set(bars.filter((b) => b.date > ref.date).map((b) => b.date));
  if (lastTradeDate > ref.date) traded.add(lastTradeDate);
  const sessions = Math.max(1, traded.size);

  return {
    status: "moved",
    ticker: symbol,
    refClose: ref.close,
    refDate: ref.date,
    price,
    movePct: (price / ref.close - 1) * 100,
    sessions,
    window: sessions === 1 && lastTradeDate === todayEt ? "today" : "since",
  };
}
