import "server-only";
import { cacheLife, cacheTag } from "next/cache";

import { createServiceClient } from "@/lib/supabase/service";

/**
 * The CEO directory's reads, over `swingtrader.company_ceos` (one row per
 * symbol) and `ceo_directory_v` (one row per person).
 *
 * The table is filled by `code/analytics/services/ceos` from FMP, so everything
 * here is reference data that changes on a proxy filing or a succession — the
 * cache lifetimes are hours, not minutes.
 *
 * Every read fails SOFT (empty / null). The quote page asks for its CEO row on
 * every render; a directory outage must cost it a link, never the page.
 */

const SCHEMA = "swingtrader";

export type CeoCompensation = {
  year: number;
  salary: number | null;
  bonus: number | null;
  stock_award: number | null;
  option_award: number | null;
  incentive: number | null;
  other: number | null;
  total: number | null;
  filing_date: string | null;
  link: string | null;
  name_and_position: string | null;
};

export type CeoTeamMember = {
  name: string;
  title: string | null;
  pay: number | null;
  currency_pay: string | null;
  year_born: number | null;
};

/** One company a person runs. */
export type CeoRole = {
  symbol: string;
  companyName: string | null;
  exchange: string | null;
  sector: string | null;
  industry: string | null;
  country: string | null;
  marketCap: number | null;
  ceoNameRaw: string;
  ceoName: string;
  slug: string;
  title: string | null;
  yearBorn: number | null;
  titleSince: string | null;
  pay: number | null;
  currencyPay: string | null;
  compensation: CeoCompensation[];
  executives: CeoTeamMember[];
  contentChangedAt: string | null;
};

export type CeoListing = {
  slug: string;
  name: string;
  title: string | null;
  symbols: string[];
  primaryCompany: string | null;
  sector: string | null;
  marketCap: number | null;
  yearBorn: number | null;
  latestPay: number | null;
  latestPayYear: number | null;
  hasCompensation: boolean;
  contentChangedAt: string | null;
};

const ROLE_COLUMNS =
  "symbol, company_name, exchange, sector, industry, country, market_cap, ceo_name_raw, ceo_name, ceo_slug, ceo_title, year_born, title_since, pay, currency_pay, compensation, executives, content_changed_at";

function num(v: unknown): number | null {
  return v != null && Number.isFinite(Number(v)) ? Number(v) : null;
}
function str(v: unknown): string | null {
  return typeof v === "string" && v.trim() ? v.trim() : null;
}

function toRole(r: Record<string, unknown>): CeoRole {
  return {
    symbol: String(r.symbol),
    companyName: str(r.company_name),
    exchange: str(r.exchange),
    sector: str(r.sector),
    industry: str(r.industry),
    country: str(r.country),
    marketCap: num(r.market_cap),
    ceoNameRaw: String(r.ceo_name_raw ?? ""),
    ceoName: String(r.ceo_name ?? ""),
    slug: String(r.ceo_slug ?? ""),
    title: str(r.ceo_title),
    yearBorn: num(r.year_born),
    titleSince: str(r.title_since),
    pay: num(r.pay),
    currencyPay: str(r.currency_pay),
    compensation: Array.isArray(r.compensation) ? (r.compensation as CeoCompensation[]) : [],
    executives: Array.isArray(r.executives) ? (r.executives as CeoTeamMember[]) : [],
    contentChangedAt: str(r.content_changed_at),
  };
}

function toListing(r: Record<string, unknown>): CeoListing {
  return {
    slug: String(r.ceo_slug),
    name: String(r.ceo_name ?? ""),
    title: str(r.ceo_title),
    symbols: Array.isArray(r.symbols) ? (r.symbols as string[]) : [],
    primaryCompany: str(r.primary_company),
    sector: str(r.sector),
    marketCap: num(r.market_cap),
    yearBorn: num(r.year_born),
    latestPay: num(r.latest_pay),
    latestPayYear: num(r.latest_pay_year),
    hasCompensation: Boolean(r.has_compensation),
    contentChangedAt: str(r.content_changed_at),
  };
}

/** The CEO row behind a quote page, or null. Tagged with the quote's own tag
 *  so `revalidateTag("quote:NVDA")` drops it with the rest of the page. */
export async function getCeoForSymbol(symbol: string): Promise<CeoRole | null> {
  "use cache";
  cacheLife("hours");
  cacheTag(`quote:${symbol}`, "ceos");
  try {
    const { data, error } = await createServiceClient()
      .schema(SCHEMA)
      .from("company_ceos")
      .select(ROLE_COLUMNS)
      .eq("symbol", symbol)
      .maybeSingle();
    if (error || !data) return null;
    return toRole(data as Record<string, unknown>);
  } catch (e) {
    console.warn("getCeoForSymbol", e);
    return null;
  }
}

/** Every company one person runs, largest first. Empty when the slug is unknown. */
export async function getCeoRoles(slug: string): Promise<CeoRole[]> {
  "use cache";
  cacheLife("hours");
  cacheTag(`ceo:${slug}`, "ceos");
  try {
    const { data, error } = await createServiceClient()
      .schema(SCHEMA)
      .from("company_ceos")
      .select(ROLE_COLUMNS)
      .eq("ceo_slug", slug)
      .order("market_cap", { ascending: false, nullsFirst: false });
    if (error || !Array.isArray(data)) return [];
    return (data as Record<string, unknown>[]).map(toRole);
  } catch (e) {
    console.warn("getCeoRoles", e);
    return [];
  }
}

const LISTING_COLUMNS =
  "ceo_slug, ceo_name, ceo_title, symbols, primary_company, sector, market_cap, year_born, latest_pay, latest_pay_year, has_compensation, content_changed_at";

/** PostgREST `or()` takes a comma/paren grammar; strip anything that could
 *  break out of the ilike pattern rather than trying to escape it. */
function safeSearch(q: string): string {
  return q.replace(/[,()*%\\:"']/g, " ").replace(/\s+/g, " ").trim().slice(0, 64);
}

export async function listCeos(
  opts: { search?: string; limit?: number; offset?: number } = {},
): Promise<{ items: CeoListing[]; total: number }> {
  "use cache";
  cacheLife("hours");
  cacheTag("ceos");
  const limit = Math.max(1, Math.min(opts.limit ?? 50, 200));
  const offset = Math.max(0, opts.offset ?? 0);
  try {
    let query = createServiceClient()
      .schema(SCHEMA)
      .from("ceo_directory_v")
      .select(LISTING_COLUMNS, { count: "exact" })
      .order("market_cap", { ascending: false, nullsFirst: false })
      .order("ceo_slug", { ascending: true })
      .range(offset, offset + limit - 1);

    const q = safeSearch(opts.search ?? "");
    if (q) {
      const sym = q.toUpperCase().replace(/\s+/g, "");
      query = query.or(
        `ceo_name.ilike.*${q}*,primary_company.ilike.*${q}*,symbols.cs.{${sym}}`,
      );
    }

    const { data, error, count } = await query;
    if (error || !Array.isArray(data)) return { items: [], total: 0 };
    return {
      items: (data as Record<string, unknown>[]).map(toListing),
      total: count ?? data.length,
    };
  } catch (e) {
    console.warn("listCeos", e);
    return { items: [], total: 0 };
  }
}

/** For the sitemap: people whose page carries the pay history, largest first. */
export async function listCeoSitemapEntries(
  limit = 1000,
): Promise<{ slug: string; contentChangedAt: string | null }[]> {
  try {
    const { data, error } = await createServiceClient()
      .schema(SCHEMA)
      .from("ceo_directory_v")
      .select("ceo_slug, content_changed_at")
      .eq("has_compensation", true)
      .order("market_cap", { ascending: false, nullsFirst: false })
      .limit(limit);
    if (error || !Array.isArray(data)) return [];
    return (data as Record<string, unknown>[]).map((r) => ({
      slug: String(r.ceo_slug),
      contentChangedAt: str(r.content_changed_at),
    }));
  } catch (e) {
    console.warn("listCeoSitemapEntries", e);
    return [];
  }
}

/** Slugs for `generateStaticParams`; the largest few are enough to prerender. */
export async function listTopCeoSlugs(limit = 50): Promise<string[]> {
  const entries = await listCeoSitemapEntries(limit);
  return entries.map((e) => e.slug);
}
