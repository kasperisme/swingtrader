import "server-only";
import { cacheLife, cacheTag } from "next/cache";

import { fmpGetCompanyProfile, fmpGetOhlc, type FmpOhlcBar } from "@/app/actions/fmp";
import { getPricedInVote } from "@/lib/quote/priced-in";
import { getTickerPeers } from "@/lib/quote/peers";
import { getTickerImpactNewsResult } from "@/lib/quote/ticker-impact";

/**
 * The quote page's cross-request cache.
 *
 * The page already wrapped these in React's `cache()`, but that is
 * REQUEST-scoped: it stops `generateMetadata` and the body from issuing the same
 * query twice within one render, and does nothing at all for the next visitor.
 * So every hit on /quote/NVDA re-ran an FMP profile call, a 365-day scored-news
 * query, the priced-in read and the peer graph — measured at ~3.2s cold.
 *
 * Everything here is cacheable for a simple reason: it is not per-user and it is
 * not per-request. All three Supabase reads go through the SERVICE client, so
 * there is no cookie, no session and no row-level filtering to leak between
 * viewers — the same symbol yields the same bytes for everyone.
 *
 * The lifetimes are set by how often the underlying thing actually changes, not
 * by how fresh it would be nice to look:
 *
 *   profile   company name, sector, description  — changes on a corporate action
 *   priced-in rebuilt by the nightly batch       — an hour of staleness is none
 *   peers     the relationship graph, refreshed daily
 *   events    scored coverage, arriving continuously — the only one worth minutes
 *   bars      daily OHLC; the last candle moves intraday
 *
 * NOT cached, deliberately: the live quote. It is the one number on the page a
 * reader would notice going stale, and it is also the cheapest call.
 *
 * Each entry is tagged by symbol so a future writer (the priced-in batch, the
 * scorer) can call `revalidateTag(\`quote:\${symbol}\`)` and drop just that
 * ticker rather than waiting out the window.
 */

export async function cachedProfile(symbol: string) {
  "use cache";
  cacheLife("hours");
  cacheTag(`quote:${symbol}`);
  const res = await fmpGetCompanyProfile(symbol);
  return res.ok ? res.data : null;
}

export async function cachedEvents(symbol: string) {
  "use cache";
  cacheLife("minutes");
  cacheTag(`quote:${symbol}`);
  return getTickerImpactNewsResult(symbol, { days: 365, limit: 150, perBucket: 2 });
}

export async function cachedPricedIn(symbol: string) {
  "use cache";
  cacheLife("hours");
  cacheTag(`quote:${symbol}`);
  return getPricedInVote(symbol);
}

export async function cachedPeers(symbol: string) {
  "use cache";
  cacheLife("hours");
  cacheTag(`quote:${symbol}`);
  return getTickerPeers(symbol);
}

export async function cachedBars(symbol: string): Promise<FmpOhlcBar[]> {
  "use cache";
  cacheLife("minutes");
  cacheTag(`quote:${symbol}`);
  const res = await fmpGetOhlc(symbol, "1day");
  return res.ok ? res.data : [];
}
