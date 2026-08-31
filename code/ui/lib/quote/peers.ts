import "server-only";
import { createServiceClient } from "@/lib/supabase/service";

/**
 * A ticker this one is connected to, as the news actually described the link.
 *
 * The quote page already renders the full relationship graph — but that is a
 * d3 canvas mounted client-side on scroll, so a crawler sees an empty div. The
 * result was 1,500 quote pages with zero outbound links to each other: the
 * ticker link graph existed in the database and nowhere in the HTML. This is
 * the same data, flattened to one hop and rendered server-side as plain
 * anchors, so the connections are crawlable and the copy around them is unique
 * to this ticker.
 */
export type TickerPeer = {
  ticker: string;
  /** supplier | customer | partner | competitor | subsidiary | acquirer | … */
  relType: string;
  /** Which way the edge was stated: this ticker as subject, or as object. */
  direction: "out" | "in";
  /** Distinct articles that established the link — the ranking signal. */
  articleCount: number;
  strength: number;
};

const SCHEMA = "swingtrader";

/**
 * Only link to symbols that have a quote page worth linking to.
 *
 * The graph is built from what the coverage says, so its nodes include things
 * that are not US listings: foreign tickers as locally quoted (`2330` for TSMC,
 * `000660` for SK Hynix), industry placeholders (`AI (INDUSTRY)`) and private
 * companies (`ANTHROPIC`). `/quote/ANTHROPIC` is a page our data vendor knows
 * nothing about, and pointing crawlers at empty pages is the opposite of the
 * point. A US ticker is 1–5 letters, optionally a class suffix.
 */
const LINKABLE = /^[A-Z]{1,5}([.\-][A-Z]{1,2})?$/;

/** BRK.B and BRK-B are the same company written twice — link it once. */
function tickerRoot(ticker: string): string {
  return ticker.split(/[.\-]/)[0];
}

/**
 * One-hop neighbours of `symbol`, strongest first.
 *
 * Reads `get_relationship_neighborhood` (the same RPC the explorer uses) with
 * the service role, so it resolves for logged-out visitors and crawlers the
 * way the rest of the public quote page does. Never throws: a peer block is a
 * bonus on the page, not a precondition for it.
 */
export async function getTickerPeers(
  symbol: string,
  limit = 12,
): Promise<TickerPeer[]> {
  const ticker = symbol.trim().toUpperCase();
  if (!ticker) return [];

  try {
    const supabase = createServiceClient();
    const { data, error } = await supabase
      .schema(SCHEMA)
      .rpc("get_relationship_neighborhood", {
        p_seed: ticker,
        p_hops: 1,
        p_min_strength: 0.25,
        // Two independent articles before a link is worth a page-level claim.
        p_min_mentions: 2,
        p_rel_types: null,
        // The RPC truncates the edge set by its own scan order, NOT by
        // strength — at the old cap of 120 a mega-cap like NVDA came back cut
        // off mid-alphabet, so "top peers" meant AAPL, ACER, ACHR, ADX. Ask
        // for the whole one-hop ring and do the ranking here.
        p_limit_nodes: 400,
        p_limit_edges: 1500,
        p_days_lookback: null,
      });
    if (error) throw error;

    // Collapse multi-edges: two companies can be described as both partners and
    // competitors across a year of coverage. Keep the best-evidenced label.
    const best = new Map<string, TickerPeer>();
    for (const raw of Array.isArray(data) ? data : []) {
      const row = raw as Record<string, unknown>;
      if (String(row.row_type ?? "") !== "edge") continue;

      const from = String(row.from_ticker ?? "").trim().toUpperCase();
      const to = String(row.to_ticker ?? "").trim().toUpperCase();
      const relType = String(row.rel_type ?? "").trim().toLowerCase();
      if (!from || !to || !relType || from === to) continue;

      // One hop only — the RPC also returns the second ring.
      const isOut = from === ticker;
      const isIn = to === ticker;
      if (!isOut && !isIn) continue;

      const peerTicker = isOut ? to : from;
      if (!LINKABLE.test(peerTicker)) continue;

      const peer: TickerPeer = {
        ticker: peerTicker,
        relType,
        direction: isOut ? "out" : "in",
        articleCount: Number(row.article_count ?? 0),
        strength: Number(row.strength_avg ?? 0),
      };
      const key = tickerRoot(peer.ticker);
      const prev = best.get(key);
      if (!prev || peer.articleCount > prev.articleCount) best.set(key, peer);
    }

    return [...best.values()]
      .sort((a, b) => b.articleCount - a.articleCount || b.strength - a.strength)
      .slice(0, limit);
  } catch (e) {
    console.warn("[quote/peers] neighborhood lookup failed", ticker, e);
    return [];
  }
}

/** How the link reads in a sentence, from this ticker's side. */
export function peerLabel(peer: TickerPeer): string {
  const t = peer.relType;
  if (t === "supplier") return peer.direction === "out" ? "Supplier" : "Customer";
  if (t === "customer") return peer.direction === "out" ? "Customer" : "Supplier";
  if (t === "subsidiary") return peer.direction === "out" ? "Subsidiary" : "Parent";
  if (t === "acquirer") return peer.direction === "out" ? "Acquired" : "Acquirer";
  if (t === "investor") return peer.direction === "out" ? "Investment" : "Investor";
  return t.charAt(0).toUpperCase() + t.slice(1);
}
