import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { cache, Suspense } from "react";
import { ArrowLeft, ArrowUpRight } from "lucide-react";
import { CavemanContent } from "@/components/caveman-content";
import { TickerLogo } from "@/components/ticker-logo";
import { Portrait } from "@/app/traders/_components/portrait";
import { cachedEvents } from "@/app/quote/[symbol]/_data";
import {
  getCeoRoles,
  listTopCeoSlugs,
  type CeoCompensation,
  type CeoRole,
} from "@/lib/ceos";
import { isSanityConfigured, sanityFetch } from "@/lib/sanity/client";
import { ceoProfileBySlugQuery } from "@/lib/sanity/queries";
import type { CeoProfile } from "@/lib/sanity/types";
import type { ScoredNewsEvent } from "@/lib/quote/ticker-impact";
import { SITE_NAME, SITE_URL } from "@/lib/site";
import { fmtPay, fmtUsd, fmtUsdCompact } from "../_format";

type Props = { params: Promise<{ slug: string }> };

export async function generateStaticParams() {
  // Cache Components requires at least one static param.
  const fallback = [{ slug: "jensen-huang" }];
  const slugs = await listTopCeoSlugs(50);
  return slugs.length > 0 ? slugs.map((slug) => ({ slug })) : fallback;
}

const rolesOf = cache((slug: string) => getCeoRoles(slug));

async function profileOf(slug: string): Promise<CeoProfile | null> {
  if (!isSanityConfigured) return null;
  try {
    return await sanityFetch<CeoProfile | null>(ceoProfileBySlugQuery, { slug });
  } catch {
    return null;
  }
}
const editorialOf = cache(profileOf);

/** The role whose company leads the page: the largest one with a pay history,
 *  else simply the largest. */
function primaryRole(roles: CeoRole[]): CeoRole {
  return roles.find((r) => r.compensation.length > 0) ?? roles[0];
}

/** Dual-class listings (GOOG/GOOGL) are one company; show it once. */
function companies(roles: CeoRole[]): { name: string; roles: CeoRole[] }[] {
  const by = new Map<string, CeoRole[]>();
  for (const r of roles) {
    const key = r.companyName ?? r.symbol;
    by.set(key, [...(by.get(key) ?? []), r]);
  }
  return [...by.entries()].map(([name, rs]) => ({ name, roles: rs }));
}

function describe(name: string, lead: CeoRole): string {
  const role = lead.title ?? "CEO";
  const where = lead.companyName ? `${lead.companyName} (${lead.symbol})` : lead.symbol;
  const pay = lead.compensation[0];
  const paid =
    pay?.total != null
      ? ` Total compensation of ${fmtUsdCompact(pay.total)} in ${pay.year}, per the company's SEC proxy filing.`
      : "";
  return `${name} is ${role} of ${where}.${paid} Title, pay history and the leadership team.`;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const [roles, editorial] = await Promise.all([rolesOf(slug), editorialOf(slug)]);
  if (roles.length === 0) return { title: "CEO not found" };
  const lead = primaryRole(roles);
  const name = editorial?.name || lead.ceoName;
  const description = editorial?.summary?.trim() || describe(name, lead);
  const url = `${SITE_URL}/ceos/${slug}`;
  // A page with neither a pay history nor a written profile is a name and a
  // company — the same commodity line as every data aggregator. It stays
  // followable and asks to be indexed once it carries something of its own.
  const substantive =
    roles.some((r) => r.compensation.length > 0) || Boolean(editorial?.body?.length);
  return {
    title: lead.companyName ? `${name} — CEO of ${lead.companyName}` : name,
    description,
    alternates: { canonical: url },
    robots: substantive ? { index: true, follow: true } : { index: false, follow: true },
    openGraph: { type: "profile", url, title: name, description },
  };
}

function personJsonLd(name: string, roles: CeoRole[], editorial: CeoProfile | null, url: string) {
  const lead = primaryRole(roles);
  const sameAs = (editorial?.links ?? [])
    .map((l) => l.url)
    .filter((u): u is string => Boolean(u && /^https?:\/\//.test(u)));
  const person = {
    "@type": "Person",
    "@id": `${url}#person`,
    name,
    ...(lead.title ? { jobTitle: lead.title } : {}),
    // A bare year is all FMP gives, and all that is claimed.
    ...(lead.yearBorn ? { birthDate: String(lead.yearBorn) } : {}),
    ...(editorial?.imageUrl ? { image: editorial.imageUrl } : {}),
    ...(editorial?.summary ? { description: editorial.summary } : {}),
    ...(sameAs.length ? { sameAs } : {}),
    worksFor: companies(roles).map(({ name: company, roles: rs }) => ({
      "@type": "Corporation",
      name: company,
      tickerSymbol: rs[0].symbol,
      url: `${SITE_URL}/quote/${rs[0].symbol}`,
    })),
  };
  return {
    "@context": "https://schema.org",
    "@graph": [
      person,
      {
        "@type": "ProfilePage",
        "@id": url,
        url,
        name,
        mainEntity: { "@id": `${url}#person` },
        ...(lead.contentChangedAt ? { dateModified: lead.contentChangedAt } : {}),
        isPartOf: { "@type": "WebSite", name: SITE_NAME, url: SITE_URL },
      },
      {
        "@type": "BreadcrumbList",
        itemListElement: [
          { "@type": "ListItem", position: 1, name: "Home", item: SITE_URL },
          { "@type": "ListItem", position: 2, name: "CEOs", item: `${SITE_URL}/ceos` },
          { "@type": "ListItem", position: 3, name, item: url },
        ],
      },
    ],
  };
}

const COMPONENTS: { key: keyof CeoCompensation; label: string }[] = [
  { key: "salary", label: "Salary" },
  { key: "bonus", label: "Bonus" },
  { key: "stock_award", label: "Stock awards" },
  { key: "option_award", label: "Option awards" },
  { key: "incentive", label: "Incentive plan" },
  { key: "other", label: "Other" },
];

/**
 * The latest proxy year, as a hero number and its make-up.
 *
 * One hue, one bar per component scaled to the largest, with the value and its
 * share of the total printed beside it — so the chart is also its own table,
 * and the usual finding (salary is a rounding error next to stock) reads at a
 * glance.
 */
function PayBreakdown({ row, company }: { row: CeoCompensation; company: string }) {
  const parts = COMPONENTS.map((c) => ({ ...c, value: Number(row[c.key] ?? 0) })).filter(
    (p) => p.value > 0,
  );
  const total = row.total ?? parts.reduce((a, p) => a + p.value, 0);
  const max = Math.max(...parts.map((p) => p.value), 1);
  return (
    <div className="rounded-lg border p-5">
      <p className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
        Total compensation · {row.year}
      </p>
      <p className="mt-2 text-4xl font-semibold tabular-nums tracking-tight">
        {fmtUsdCompact(total)}
      </p>
      <p className="mt-1 text-sm text-muted-foreground">
        {fmtUsd(total)} as reported in {company}&apos;s proxy statement.
      </p>
      {parts.length > 0 && (
        <dl className="mt-5 grid gap-2.5">
          {parts.map((p) => {
            const share = total > 0 ? p.value / total : 0;
            return (
              <div
                key={p.key}
                className="grid grid-cols-[7.5rem_minmax(0,1fr)_5.5rem] items-center gap-3 text-sm"
                title={`${p.label}: ${fmtUsd(p.value)} (${Math.round(share * 100)}% of total)`}
              >
                <dt className="text-muted-foreground">{p.label}</dt>
                <dd className="h-2 overflow-hidden rounded-full bg-muted" aria-hidden>
                  <span
                    className="block h-full rounded-full bg-amber-500"
                    style={{ width: `${Math.max(2, (p.value / max) * 100)}%` }}
                  />
                </dd>
                <dd className="text-right font-mono text-xs tabular-nums">
                  {fmtUsdCompact(p.value)}
                  <span className="ml-1.5 text-muted-foreground">{Math.round(share * 100)}%</span>
                </dd>
              </div>
            );
          })}
        </dl>
      )}
    </div>
  );
}

function PayHistory({ rows }: { rows: CeoCompensation[] }) {
  const cols = COMPONENTS.filter((c) => rows.some((r) => Number(r[c.key] ?? 0) > 0));
  return (
    <div className="mt-4 overflow-x-auto">
      <table className="w-full min-w-[34rem] text-sm">
        <caption className="sr-only">Compensation by year</caption>
        <thead>
          <tr className="border-b text-left font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
            <th className="py-2 pr-3 font-normal">Year</th>
            {cols.map((c) => (
              <th key={c.key} className="py-2 pr-3 text-right font-normal">
                {c.label}
              </th>
            ))}
            <th className="py-2 pr-3 text-right font-normal">Total</th>
            <th className="py-2 text-right font-normal">Filing</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.year} className="border-b border-border/60">
              <td className="py-2 pr-3 font-mono tabular-nums">{r.year}</td>
              {cols.map((c) => (
                <td key={c.key} className="py-2 pr-3 text-right font-mono tabular-nums">
                  {fmtUsdCompact(r[c.key] as number | null)}
                </td>
              ))}
              <td className="py-2 pr-3 text-right font-mono font-medium tabular-nums">
                {fmtUsdCompact(r.total)}
              </td>
              <td className="py-2 text-right">
                {r.link ? (
                  <a
                    href={r.link}
                    target="_blank"
                    rel="noopener noreferrer nofollow"
                    className="inline-flex items-center gap-1 font-mono text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
                  >
                    SEC
                    <ArrowUpRight className="h-3 w-3" aria-hidden />
                  </a>
                ) : (
                  <span className="text-muted-foreground">—</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const DAY_FMT = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  year: "numeric",
  timeZone: "UTC",
});

/**
 * Coverage that names them. Reuses the quote page's cached catalyst list for
 * the company and keeps the headlines carrying the surname as a whole word —
 * "Huang" in "Jensen Huang says…" — which is how the press refers to a CEO,
 * whatever given name the proxy filing uses ("Jen-Hsun"). Falls back to the company's latest
 * catalysts, labelled as such, rather than an empty section.
 */
async function Headlines({ name, lead }: { name: string; lead: CeoRole }) {
  const { events } = await cachedEvents(lead.symbol);
  const linked = events.filter((e): e is ScoredNewsEvent & { slug: string } => Boolean(e.slug && e.title));
  const surname = name.replace(/,.*$/, "").replace(/\b(jr|sr|ii|iii|iv)\.?$/i, "").trim().split(/\s+/).pop() ?? "";
  const re = surname.length >= 2 ? new RegExp(`\\b${surname.replace(/[^\p{L}\-']/gu, "")}\\b`, "iu") : null;
  const naming = re ? linked.filter((e) => re.test(e.title ?? "")) : [];
  const shown = (naming.length > 0 ? naming : linked)
    .slice()
    .sort((a, b) => (b.publishedAt ?? "").localeCompare(a.publishedAt ?? ""))
    .slice(0, 6);
  if (shown.length === 0) return null;

  return (
    <section className="mt-12">
      <h2 className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
        {naming.length > 0 ? "In the headlines" : `Latest catalysts at ${lead.companyName ?? lead.symbol}`}
      </h2>
      <ul className="mt-4 grid gap-px overflow-hidden rounded-lg border bg-border">
        {shown.map((e) => (
          <li key={e.articleId} className="bg-background">
            <Link
              href={`/articles/${e.slug}`}
              className="group block p-4 transition-colors hover:bg-muted/50"
            >
              <p className="text-sm font-medium leading-snug group-hover:text-amber-600 dark:group-hover:text-amber-500">
                {e.title}
              </p>
              <p className="mt-1 flex flex-wrap gap-x-2 font-mono text-[11px] text-muted-foreground">
                {e.publishedAt && <span>{DAY_FMT.format(new Date(e.publishedAt))}</span>}
                {e.source && <span>{e.source}</span>}
                {e.sentiment != null && (
                  <span className={e.sentiment > 0 ? "text-emerald-600 dark:text-emerald-500" : e.sentiment < 0 ? "text-rose-600 dark:text-rose-500" : ""}>
                    sentiment {e.sentiment >= 0 ? "+" : ""}
                    {e.sentiment.toFixed(2)}
                  </span>
                )}
              </p>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

async function CeoDetail({ params }: Props) {
  const { slug } = await params;
  const [roles, editorial] = await Promise.all([rolesOf(slug), editorialOf(slug)]);
  if (roles.length === 0) notFound();

  const lead = primaryRole(roles);
  const name = editorial?.name || lead.ceoName;
  const url = `${SITE_URL}/ceos/${slug}`;
  const pay = lead.compensation;
  const team = lead.executives.slice(0, 10);

  return (
    <main className="mx-auto max-w-3xl px-4 py-12 sm:py-16">
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(personJsonLd(name, roles, editorial, url)) }}
      />
      <Link
        href="/ceos"
        className="inline-flex items-center gap-1.5 font-mono text-[11px] uppercase tracking-widest text-muted-foreground transition-colors hover:text-foreground"
      >
        <ArrowLeft className="h-3.5 w-3.5" aria-hidden />
        CEO directory
      </Link>

      <header className="mt-6 flex flex-wrap items-start gap-5">
        <Portrait
          name={name}
          slug={slug}
          url={editorial?.imageUrl}
          alt={editorial?.imageAlt}
          size={88}
        />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-x-3 font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
            {lead.sector && <span>{lead.sector}</span>}
            {lead.yearBorn && <span className="tabular-nums">b. {lead.yearBorn}</span>}
            {lead.country && <span>{lead.country}</span>}
          </div>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight sm:text-4xl">{name}</h1>
          <p className="mt-2 text-base text-muted-foreground">
            {lead.title ?? "CEO"}
            {lead.companyName && (
              <>
                {", "}
                <Link
                  href={`/quote/${lead.symbol}`}
                  className="font-medium text-foreground underline decoration-amber-500/40 underline-offset-4 transition-colors hover:decoration-amber-500"
                >
                  {lead.companyName}
                </Link>
              </>
            )}
          </p>
          {editorial?.knownFor && (
            <p className="mt-1 text-sm text-muted-foreground">{editorial.knownFor}</p>
          )}
          {editorial?.imageUrl && editorial.imageCredit && (
            <p className="mt-2 font-mono text-[10px] text-muted-foreground/70">
              Portrait:{" "}
              {editorial.imageCreditUrl ? (
                <a
                  href={editorial.imageCreditUrl}
                  target="_blank"
                  rel="noopener noreferrer nofollow"
                  className="underline underline-offset-2 hover:text-foreground"
                >
                  {editorial.imageCredit}
                </a>
              ) : (
                editorial.imageCredit
              )}
            </p>
          )}
        </div>
      </header>

      {editorial?.summary && <p className="mt-10 text-lg leading-relaxed">{editorial.summary}</p>}
      {editorial?.body && editorial.body.length > 0 && (
        <div className="prose-custom mt-8 space-y-5">
          <CavemanContent body={editorial.body} cavemanBody={editorial.cavemanBody} />
        </div>
      )}

      <section className="mt-12">
        <h2 className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
          {roles.length > 1 ? "Runs" : "Company"}
        </h2>
        <ul className="mt-4 grid gap-2">
          {companies(roles).map(({ name: company, roles: rs }) => (
            <li key={company}>
              <Link
                href={`/quote/${rs[0].symbol}`}
                className="group flex items-center gap-4 border-l-2 border-l-border py-3 pl-4 transition-colors hover:border-l-amber-500 hover:bg-muted/50"
              >
                <TickerLogo symbol={rs[0].symbol} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium group-hover:text-amber-600 dark:group-hover:text-amber-500">
                    {company}
                  </span>
                  <span className="mt-0.5 block truncate text-xs text-muted-foreground">
                    <span className="font-mono">{rs.map((r) => r.symbol).join(" · ")}</span>
                    {rs[0].industry && <> · {rs[0].industry}</>}
                  </span>
                </span>
                <span className="text-right">
                  <span className="block font-mono text-sm tabular-nums">
                    {fmtUsdCompact(rs[0].marketCap)}
                  </span>
                  <span className="block font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
                    mkt cap
                  </span>
                </span>
              </Link>
            </li>
          ))}
        </ul>
      </section>

      <section className="mt-12">
        <h2 className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
          Pay
        </h2>
        {pay.length > 0 ? (
          <div className="mt-4">
            <PayBreakdown row={pay[0]} company={lead.companyName ?? lead.symbol} />
            {pay.length > 1 && <PayHistory rows={pay} />}
          </div>
        ) : (
          <p className="mt-4 max-w-[62ch] text-sm leading-relaxed text-muted-foreground">
            {lead.pay != null
              ? `Most recently reported pay: ${fmtPay(lead.pay, lead.currencyPay)}. `
              : ""}
            No year-by-year proxy breakdown is on file — common for foreign
            private issuers and recently listed companies, which do not file a
            US proxy statement.
          </p>
        )}
      </section>

      <Suspense fallback={null}>
        <Headlines name={name} lead={lead} />
      </Suspense>

      {team.length > 0 && (
        <section className="mt-12">
          <h2 className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
            Leadership team at {lead.companyName ?? lead.symbol}
          </h2>
          <dl className="mt-4 grid gap-px overflow-hidden rounded-lg border bg-border sm:grid-cols-2">
            {team.map((m, i) => (
              <div key={`${m.name}-${i}`} className="bg-background p-4">
                <dt className="font-medium">{m.name}</dt>
                <dd className="mt-0.5 text-sm text-muted-foreground">{m.title ?? "—"}</dd>
                {m.pay != null && (
                  <dd className="mt-1 font-mono text-xs tabular-nums text-muted-foreground">
                    Pay {fmtPay(m.pay, m.currency_pay)}
                  </dd>
                )}
              </div>
            ))}
          </dl>
        </section>
      )}

      {editorial?.links && editorial.links.length > 0 && (
        <section className="mt-12">
          <h2 className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
            Elsewhere
          </h2>
          <ul className="mt-4 flex flex-wrap gap-2">
            {editorial.links.map((l, i) =>
              l.url ? (
                <li key={i}>
                  <a
                    href={l.url}
                    target="_blank"
                    rel="noopener noreferrer nofollow"
                    className="inline-flex items-center gap-1.5 rounded-full border px-3 py-1 font-mono text-[11px] text-muted-foreground transition-colors hover:border-foreground/30 hover:text-foreground"
                  >
                    {l.label || new URL(l.url).hostname}
                    <ArrowUpRight className="h-3 w-3 opacity-60" aria-hidden />
                  </a>
                </li>
              ) : null,
            )}
          </ul>
        </section>
      )}

      <p className="mt-14 max-w-[68ch] text-xs leading-relaxed text-muted-foreground">
        Names, titles and pay as reported by the company and its SEC filings,
        via Financial Modeling Prep. Reference only — nothing here is investment
        advice, and no affiliation with or endorsement by the people listed is
        implied.
      </p>
    </main>
  );
}

export default function CeoPage(props: Props) {
  return (
    <Suspense
      fallback={
        <main className="mx-auto max-w-3xl px-4 py-12 sm:py-16">
          <div className="h-8 w-56 animate-pulse rounded bg-muted" />
          <div className="mt-6 h-40 animate-pulse rounded bg-muted" />
        </main>
      }
    >
      <CeoDetail {...props} />
    </Suspense>
  );
}
