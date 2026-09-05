"use server";

import { createServiceClient } from "@/lib/supabase/service";
import { fetchAllPaged } from "@/lib/supabase/paginate";

/**
 * Reads for the public Arena — the competing AI paper-trading agents.
 *
 * Every query goes through an `arena_*_public_v` view, which filters to
 * `is_published`. An agent still being tuned cannot reach these functions, so a
 * forgotten `.eq()` in a page cannot leak one onto the site.
 *
 * All of it is read-only. Trading happens in `services/arena` (Python), on a
 * cron, against the service role — nothing the web app does can move a
 * position, and that separation is what makes the published record credible.
 *
 * Everything is scoped to a CHAMPIONSHIP. Standings, returns and drawdowns are
 * computed within one fixed window, because every agent is re-funded at the
 * start of each — a curve that spans a re-funding is not a curve.
 */

/** A platform resource an agent actually consulted, with the page that publishes it. */
export type ArenaResource = {
  kind: "screening" | "article" | "ticker" | "topic";
  key: string;
  label: string;
  href: string;
  detail: string | null;
};

/** One entry in an agent's declared data surface. */
export type ArenaToolSurface = {
  name: string;
  label: string;
  reads: string;
  href: string;
};

export type ArenaChampionship = {
  id: string;
  slug: string;
  name: string;
  description: string | null;
  starts_on: string;
  ends_on: string;
  status: "upcoming" | "running" | "complete" | "abandoned";
  starting_cash: number;
  is_backtest: boolean;
  concluded_at: string | null;
  champion_return: number | null;
  champion_slug: string | null;
  champion_name: string | null;
  runner_up_slug: string | null;
  runner_up_name: string | null;
  entrants: number;
};

export type ArenaReign = {
  reign_no: number;
  agent_id: string;
  agent_slug: string;
  agent_name: string;
  held_from: string;
  held_through: string;
  championships_won: number;
  successful_defences: number;
  championship_slugs: string[];
  is_current_holder: boolean;
};

export type ArenaStanding = {
  championship_id: string;
  championship_slug: string;
  championship_name: string;
  championship_status: string;
  starts_on: string;
  ends_on: string;
  championship_is_backtest: boolean;
  id: string;
  slug: string;
  name: string;
  tagline: string | null;
  inspiration: string | null;
  engine: "llm" | "deterministic";
  sort_order: number;
  starting_cash: number;
  as_of: string | null;
  nav: number | null;
  cash: number | null;
  long_value: number | null;
  short_value: number | null;
  n_positions: number | null;
  daily_return: number | null;
  total_return: number | null;
  max_drawdown: number | null;
  nav_days: number | null;
  sharpe: number | null;
  filled_orders: number;
  closed_trades: number;
  winning_trades: number;
  win_rate: number | null;
  realized_pnl: number | null;
  avg_realized_pct: number | null;
  is_champion: boolean | null;
};

export type ArenaAgent = {
  id: string;
  slug: string;
  name: string;
  tagline: string | null;
  approach: string | null;
  inspiration: string | null;
  tool_surface: ArenaToolSurface[] | null;
  engine: "llm" | "deterministic";
  starting_cash: number;
  max_position_pct: number;
  max_positions: number;
  allow_shorts: boolean;
  funded_on: string | null;
  sort_order: number;
  is_active: boolean;
};

export type ArenaNavPoint = {
  agent_slug: string;
  as_of: string;
  nav: number;
  cash: number;
  /** Positive market value of longs. */
  long_value: number;
  /** Positive MAGNITUDE of shorts — a liability, so NAV subtracts it. */
  short_value: number;
  n_positions: number;
  daily_return: number | null;
  cumulative_return: number | null;
  drawdown: number | null;
  is_backtest: boolean;
  /** The book as it stood at this close — lets the page show a past day's portfolio. */
  positions: {
    holdings?: ArenaHolding[];
    /** Names whose mark is older than this session; the NAV carries the last known price. */
    stale_marks?: string[];
  } | null;
};

/** One line of a stored end-of-session book. */
export type ArenaHolding = {
  ticker: string;
  /** Signed: > 0 long, < 0 short. */
  quantity: number;
  avg_cost: number;
  mark: number;
  /** Signed, so shorts subtract. */
  market_value: number;
};

export type ArenaPosition = {
  agent_slug: string;
  ticker: string;
  quantity: number;
  avg_cost: number;
  last_price: number | null;
  marked_at: string | null;
  opened_at: string;
  market_value: number;
  unrealized_pnl: number;
  unrealized_pct: number | null;
};

export type ArenaOrder = {
  id: string;
  agent_slug: string;
  ticker: string;
  side: "buy" | "sell";
  /**
   * What the fill did to the book. `side` alone is ambiguous once agents can
   * short — a sell either closes a long or OPENS a short, and a buy either
   * opens a long or COVERS one. NULL on rows written before 2026-09-05 and on
   * unfilled orders; render the bare side in that case rather than guessing.
   */
  position_effect:
    | "open_long"
    | "close_long"
    | "open_short"
    | "cover_short"
    | "flip_to_short"
    | "flip_to_long"
    | null;
  quantity: number;
  status: "pending" | "filled" | "rejected" | "cancelled";
  reject_reason: string | null;
  thesis: string | null;
  conviction: number | null;
  stop_price: number | null;
  target_price: number | null;
  submitted_at: string;
  intended_for: string | null;
  filled_at: string | null;
  fill_price: number | null;
  notional: number | null;
  realized_pnl: number | null;
  realized_pct: number | null;
  is_backtest: boolean;
};

export type ArenaDecision = {
  id: string;
  agent_slug: string;
  decision_date: string;
  status: string;
  narrative: string | null;
  rounds_used: number | null;
  tools_called: Record<string, number> | null;
  resources: ArenaResource[] | null;
  orders_requested: number;
  orders_accepted: number;
  orders_rejected: number;
  nav_at_decision: number | null;
  duration_ms: number | null;
  is_backtest: boolean;
};

function sb() {
  return createServiceClient().schema("swingtrader");
}

/* ── Championships ────────────────────────────────────────────────────────── */

export async function listChampionships(): Promise<ArenaChampionship[]> {
  const { data, error } = await sb()
    .from("arena_championships_public_v")
    .select("*");
  if (error) {
    console.error("listChampionships", error.message);
    return [];
  }
  return ((data ?? []) as ArenaChampionship[]).filter(
    (c) => c.status !== "abandoned",
  );
}

/**
 * The championship a page should show by default: the running one, else the
 * most recently completed. Returns null before the first has been created.
 */
export async function getFeaturedChampionship(
  slug?: string,
): Promise<ArenaChampionship | null> {
  const all = await listChampionships();
  if (slug) return all.find((c) => c.slug === slug) ?? null;
  return (
    all.find((c) => c.status === "running") ??
    all.find((c) => c.status === "complete") ??
    all[0] ??
    null
  );
}

/** Every reign, oldest first. The entry flagged `is_current_holder` has the belt. */
export async function getTitleLineage(): Promise<ArenaReign[]> {
  const { data, error } = await sb().from("arena_title_lineage_v").select("*");
  if (error) {
    console.error("getTitleLineage", error.message);
    return [];
  }
  return (data ?? []) as ArenaReign[];
}

/* ── Standings ────────────────────────────────────────────────────────────── */

/** Standings for one championship, best total return first. */
export async function listStandings(
  championshipId?: string,
): Promise<ArenaStanding[]> {
  let q = sb().from("arena_leaderboard_v").select("*");
  if (championshipId) q = q.eq("championship_id", championshipId);
  const { data, error } = await q;
  if (error) {
    console.error("listStandings", error.message);
    return [];
  }
  const rows = (data ?? []) as ArenaStanding[];
  return rows.sort((a, b) => {
    if (a.total_return == null && b.total_return == null)
      return a.sort_order - b.sort_order;
    if (a.total_return == null) return 1;
    if (b.total_return == null) return -1;
    return b.total_return - a.total_return;
  });
}

export async function getAgent(slug: string): Promise<ArenaAgent | null> {
  const { data, error } = await sb()
    .from("arena_agents_public_v")
    .select("*")
    .eq("slug", slug)
    .limit(1)
    .maybeSingle();
  if (error) {
    console.error("getAgent", error.message);
    return null;
  }
  return (data as ArenaAgent) ?? null;
}

export async function listAgents(): Promise<ArenaAgent[]> {
  const { data, error } = await sb()
    .from("arena_agents_public_v")
    .select("*")
    .order("sort_order");
  if (error) {
    console.error("listAgents", error.message);
    return [];
  }
  return (data ?? []) as ArenaAgent[];
}

/* ── Curves ───────────────────────────────────────────────────────────────── */

const NAV_COLUMNS =
  "agent_slug,as_of,nav,cash,long_value,short_value,n_positions," +
  "daily_return,cumulative_return,drawdown,is_backtest,positions";

/**
 * Every agent's NAV curve for one championship, keyed by slug.
 *
 * Pages rather than taking one shot: PostgREST caps an unbounded select at
 * ~1,000 rows, so a plain query would start silently dropping the newest
 * sessions partway through a season and the chart would simply stop moving.
 */
export async function listAllNavCurves(
  championshipId?: string,
): Promise<Record<string, ArenaNavPoint[]>> {
  const { data, error } = await fetchAllPaged<ArenaNavPoint & { championship_id?: string }>(
    (from, to) => {
      let q = sb()
        .from("arena_nav_history_public_v")
        .select(`${NAV_COLUMNS},championship_id`);
      if (championshipId) q = q.eq("championship_id", championshipId);
      return q.order("as_of").range(from, to).overrideTypes<ArenaNavPoint[]>();
    },
  );
  if (error) {
    console.error("listAllNavCurves", error);
    return {};
  }
  const out: Record<string, ArenaNavPoint[]> = {};
  for (const row of data) (out[row.agent_slug] ??= []).push(row);
  return out;
}

export async function listNavCurve(
  slug: string,
  championshipId?: string,
): Promise<ArenaNavPoint[]> {
  const { data, error } = await fetchAllPaged<ArenaNavPoint>((from, to) => {
    let q = sb()
      .from("arena_nav_history_public_v")
      .select(`${NAV_COLUMNS},championship_id`)
      .eq("agent_slug", slug);
    if (championshipId) q = q.eq("championship_id", championshipId);
    return q.order("as_of").range(from, to).overrideTypes<ArenaNavPoint[]>();
  });
  if (error) {
    console.error("listNavCurve", error);
    return [];
  }
  return data;
}

/* ── Book, orders, reasoning ──────────────────────────────────────────────── */

export async function listPositions(slug: string): Promise<ArenaPosition[]> {
  const { data, error } = await sb()
    .from("arena_positions_public_v")
    .select("*")
    .eq("agent_slug", slug);
  if (error) {
    console.error("listPositions", error.message);
    return [];
  }
  return ((data ?? []) as ArenaPosition[]).sort(
    (a, b) => Math.abs(b.market_value) - Math.abs(a.market_value),
  );
}

/**
 * Orders, newest first. Rejected and cancelled orders are included by design —
 * what an agent tried and was refused is part of the record, not an error to
 * be hidden.
 */
export async function listOrders(
  slug: string | null,
  limit = 40,
): Promise<ArenaOrder[]> {
  let q = sb().from("arena_orders_public_v").select("*");
  if (slug) q = q.eq("agent_slug", slug);
  // Ordered by the SESSION traded, not by when the row was written. A replay
  // writes 46 sessions of orders within an hour of wall-clock time, so sorting
  // on `submitted_at` would interleave July and September arbitrarily.
  const { data, error } = await q
    .order("intended_for", { ascending: false, nullsFirst: false })
    .order("submitted_at", { ascending: false })
    .limit(limit);
  if (error) {
    console.error("listOrders", error.message);
    return [];
  }
  return (data ?? []) as ArenaOrder[];
}

export async function listDecisions(
  slug: string | null,
  limit = 20,
): Promise<ArenaDecision[]> {
  let q = sb().from("arena_decisions_public_v").select("*");
  if (slug) q = q.eq("agent_slug", slug);
  const { data, error } = await q
    .order("decision_date", { ascending: false })
    .limit(limit);
  if (error) {
    console.error("listDecisions", error.message);
    return [];
  }
  return (data ?? []) as ArenaDecision[];
}

/**
 * The distinct resources an agent has cited recently, most-cited first.
 *
 * This is the agent page's backlink block: the actual screening boards, quote
 * pages and articles this agent's decisions have rested on, rather than a
 * static list of what it is theoretically allowed to read.
 */
export async function listAgentResources(
  slug: string,
  limit = 24,
): Promise<(ArenaResource & { citations: number })[]> {
  const decisions = await listDecisions(slug, 30);
  const byHref = new Map<string, ArenaResource & { citations: number }>();
  for (const d of decisions) {
    for (const r of d.resources ?? []) {
      const existing = byHref.get(r.href);
      if (existing) existing.citations += 1;
      else byHref.set(r.href, { ...r, citations: 1 });
    }
  }
  return [...byHref.values()]
    .sort((a, b) => b.citations - a.citations || a.label.localeCompare(b.label))
    .slice(0, limit);
}

/** Headline numbers for the page intro. */
export async function getArenaStats(championshipId?: string): Promise<{
  agents: number;
  sessions: number;
  filledOrders: number;
  asOf: string | null;
}> {
  const standings = await listStandings(championshipId);
  return {
    agents: standings.length,
    sessions: Math.max(0, ...standings.map((s) => s.nav_days ?? 0)),
    filledOrders: standings.reduce((n, s) => n + (s.filled_orders ?? 0), 0),
    asOf: standings.map((s) => s.as_of).filter(Boolean).sort().at(-1) ?? null,
  };
}
