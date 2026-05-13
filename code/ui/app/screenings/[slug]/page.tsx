import Link from "next/link";
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import {
  ArrowLeft,
  Code as CodeIcon,
  Download as DownloadIcon,
} from "lucide-react";
import { createClient } from "@/lib/supabase/server";
import {
  getLatestPublicScreeningResultRows,
  getMySubscription,
  getPublicScreeningBySlug,
  getPublicScreeningResults,
} from "@/app/actions/public-screenings";
import { humanizeCron } from "@/lib/cron-format";
import {
  ScreeningResultsTable,
  type BasicScreeningRow,
} from "@/components/screening-results-table";
import { SubscribeButton } from "../_components/subscribe-button";

type Props = { params: Promise<{ slug: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const s = await getPublicScreeningBySlug(slug);
  if (!s) return { title: "Screening not found" };
  const description =
    s.description ??
    `${s.name} — curated swing-trading screening that runs on ${humanizeCron(s.schedule)}.`;
  const canonical = `/screenings/${s.slug}`;
  return {
    title: `${s.name} | Public Screenings`,
    description,
    alternates: { canonical },
    openGraph: {
      type: "article",
      title: s.name,
      description,
      url: canonical,
    },
    twitter: {
      card: "summary_large_image",
      title: s.name,
      description,
    },
  };
}

function formatRunDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return new Intl.DateTimeFormat("en-US", {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "numeric",
    minute: "2-digit",
  }).format(d);
}

function formatRelative(iso: string | null): string {
  if (!iso) return "Not yet";
  const ms = Date.now() - new Date(iso).getTime();
  if (Number.isNaN(ms)) return "—";
  const minutes = Math.floor(ms / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(iso).toLocaleDateString();
}

function stripHtml(input: string): string {
  return input.replace(/<[^>]+>/g, "");
}

export default async function PublicScreeningDetailPage({ params }: Props) {
  const { slug } = await params;
  const screening = await getPublicScreeningBySlug(slug);
  if (!screening) notFound();

  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  const isAuthed = Boolean(user);

  const [results, subscription, latestRows] = await Promise.all([
    getPublicScreeningResults(screening.id, 10),
    isAuthed
      ? getMySubscription(screening.id)
      : Promise.resolve({ isSubscribed: false, notificationsEnabled: false }),
    getLatestPublicScreeningResultRows(screening.id),
  ]);

  const tableRows: BasicScreeningRow[] = latestRows.rows.map((r) => ({
    id: r.id,
    symbol: r.symbol,
    rowData: r.rowData,
  }));

  const triggeredRuns = results.filter((r) => r.triggered).length;
  const triggerRate =
    results.length > 0
      ? Math.round((triggeredRuns / results.length) * 100)
      : null;

  return (
    <div className="relative isolate">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 -z-10 h-[360px] bg-terminal-grid opacity-[0.3] [mask-image:linear-gradient(to_bottom,black,transparent)]"
      />

      <div className="mx-auto max-w-6xl px-4 pt-10 pb-20 sm:px-6 md:pt-14">
        {/* Breadcrumb */}
        <Link
          href="/screenings"
          className="inline-flex items-center gap-1.5 font-mono text-[11px] uppercase tracking-[0.18em] text-muted-foreground transition-colors hover:text-foreground"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          All screenings
        </Link>

        {/* Hero — asymmetric: title + lede on left, subscribe column on right. */}
        <header className="mt-6 grid grid-cols-12 gap-x-6 gap-y-10">
          <div className="col-span-12 lg:col-span-8">
            <div className="flex flex-wrap items-center gap-2 font-mono text-[11px] uppercase tracking-[0.22em] text-muted-foreground">
              <span className="inline-block h-[1px] w-6 bg-primary" />
              {screening.category && (
                <>
                  <span className="text-foreground/80">{screening.category}</span>
                  <span aria-hidden className="text-border">
                    /
                  </span>
                </>
              )}
              <span>{humanizeCron(screening.schedule, screening.timezone)}</span>
            </div>

            <h1 className="mt-5 text-5xl font-bold leading-[0.95] tracking-tight md:text-6xl">
              {screening.name}
              <span className="text-primary">.</span>
            </h1>

            {screening.description && (
              <p className="mt-6 max-w-[62ch] text-base leading-7 text-muted-foreground">
                {screening.description}
              </p>
            )}
          </div>

          <aside className="col-span-12 lg:col-span-4 lg:pt-2">
            <div className="rounded-xl border border-border/70 bg-card/40 p-5 backdrop-blur-sm">
              <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
                Subscribe
              </p>
              <p className="mt-1 text-sm leading-6 text-foreground/80">
                Get results delivered the moment this screening runs.
              </p>
              <div className="mt-4">
                <SubscribeButton
                  screeningSlug={screening.slug}
                  screeningName={screening.name}
                  isAuthed={isAuthed}
                  initialSubscribed={subscription.isSubscribed}
                />
              </div>
            </div>
          </aside>
        </header>

        {/* Stats strip — 4 cells, hairline-separated, no card-overuse. */}
        <dl className="mt-12 grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-border/70 bg-border/70 md:grid-cols-4">
          <Stat
            label="Tickers"
            value={tableRows.length.toString()}
            hint={tableRows.length === 1 ? "result" : "results"}
            accent={tableRows.length > 0}
          />
          <Stat
            label="Last run"
            value={formatRelative(latestRows.runAt)}
          />
          <Stat
            label="Trigger rate"
            value={triggerRate === null ? "—" : `${triggerRate}%`}
            hint={
              triggerRate === null
                ? null
                : `${triggeredRuns}/${results.length} runs`
            }
          />
          <Stat
            label="Cadence"
            value={humanizeCron(screening.schedule, screening.timezone)}
            small
          />
        </dl>

        {/* Latest results */}
        <section className="mt-16">
          <SectionHeader
            kicker="01"
            title="Latest results"
            meta={latestRows.runAt ? formatRunDate(latestRows.runAt) : undefined}
            actions={
              tableRows.length > 0 ? (
                <div className="flex items-center gap-2">
                  <ToolbarAction
                    href={`/screenings/${screening.slug}/export`}
                    download
                    icon={<DownloadIcon className="h-3.5 w-3.5" />}
                    label="CSV"
                  />
                  <ToolbarAction
                    href={`/api/public-screenings/${screening.slug}`}
                    external
                    icon={<CodeIcon className="h-3.5 w-3.5" />}
                    label="JSON"
                  />
                </div>
              ) : null
            }
          />

          <div className="mt-6">
            <ScreeningResultsTable
              rows={tableRows}
              emptyLabel="No results yet — this screening hasn't produced any tickers."
            />
          </div>

          {tableRows.length > 0 && (
            <details className="mt-6 rounded-lg border border-border/70 bg-muted/20 p-4 text-xs">
              <summary className="cursor-pointer font-mono text-[11px] uppercase tracking-[0.18em] text-muted-foreground hover:text-foreground">
                Programmatic access
              </summary>
              <div className="mt-3 space-y-2 text-muted-foreground">
                <p>Fetch the latest results as JSON:</p>
                <pre className="overflow-x-auto rounded-md border border-border/60 bg-background p-3 font-mono text-[11px] leading-5 text-foreground">
{`curl https://newsimpactscreener.com/api/public-screenings/${screening.slug}`}
                </pre>
                <p>
                  Response includes the screening metadata, the latest run
                  timestamp, and the per-ticker rows.
                </p>
              </div>
            </details>
          )}
        </section>

        {/* Recent runs — timeline */}
        <section className="mt-20">
          <SectionHeader kicker="02" title="Recent runs" />

          {results.length === 0 ? (
            <p className="mt-6 text-sm text-muted-foreground">
              This screening hasn&rsquo;t run yet. Subscribe to be notified
              when it does.
            </p>
          ) : (
            <ol className="mt-6 relative">
              {/* Vertical spine */}
              <span
                aria-hidden
                className="absolute left-[7px] top-2 bottom-2 w-px bg-border/70"
              />
              {results.map((r, i) => (
                <li
                  key={r.id}
                  className="relative pl-8 pb-8 last:pb-0 animate-screening-row-in"
                  style={{ animationDelay: `${Math.min(i, 8) * 40}ms` }}
                >
                  <span
                    className={
                      "absolute left-0 top-[6px] inline-flex h-[14px] w-[14px] items-center justify-center rounded-full border " +
                      (r.triggered
                        ? "border-emerald-400/50 bg-emerald-500/10"
                        : "border-border bg-background")
                    }
                  >
                    <span
                      className={
                        "inline-block h-1.5 w-1.5 rounded-full " +
                        (r.triggered ? "bg-emerald-400" : "bg-muted-foreground/60")
                      }
                    />
                  </span>

                  <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                    <time
                      dateTime={r.run_at}
                      className="font-mono text-xs tabular-nums text-foreground"
                    >
                      {formatRunDate(r.run_at)}
                    </time>
                    <span
                      className={
                        "font-mono text-[10px] uppercase tracking-[0.18em] " +
                        (r.triggered
                          ? "text-emerald-400"
                          : "text-muted-foreground")
                      }
                    >
                      {r.triggered ? "Triggered" : "No trigger"}
                    </span>
                  </div>

                  {r.summary && (
                    <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-foreground/85">
                      {stripHtml(r.summary)}
                    </p>
                  )}
                </li>
              ))}
            </ol>
          )}
        </section>
      </div>
    </div>
  );
}

function Stat({
  label,
  value,
  hint,
  accent = false,
  small = false,
}: {
  label: string;
  value: string;
  hint?: string | null;
  accent?: boolean;
  small?: boolean;
}) {
  return (
    <div className="bg-background/70 px-5 py-4">
      <dt className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
        {label}
      </dt>
      <dd className="mt-1.5 flex items-baseline gap-1.5">
        <span
          className={
            (small ? "text-base " : "text-2xl ") +
            "font-semibold tabular-nums leading-tight " +
            (accent ? "text-primary" : "text-foreground")
          }
        >
          {value}
        </span>
        {hint && (
          <span className="text-xs text-muted-foreground">{hint}</span>
        )}
      </dd>
    </div>
  );
}

function SectionHeader({
  kicker,
  title,
  meta,
  actions,
}: {
  kicker: string;
  title: string;
  meta?: string;
  actions?: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3 border-b border-border/70 pb-3">
      <div className="flex items-baseline gap-3">
        <span className="font-mono text-[11px] uppercase tracking-[0.22em] text-muted-foreground">
          {kicker}
        </span>
        <h2 className="text-xl font-semibold tracking-tight">{title}</h2>
        {meta && (
          <span className="font-mono text-[11px] text-muted-foreground">
            {meta}
          </span>
        )}
      </div>
      {actions}
    </div>
  );
}

function ToolbarAction({
  href,
  icon,
  label,
  download,
  external,
}: {
  href: string;
  icon: React.ReactNode;
  label: string;
  download?: boolean;
  external?: boolean;
}) {
  return (
    <a
      href={href}
      download={download}
      target={external ? "_blank" : undefined}
      rel={external ? "noopener noreferrer" : undefined}
      className="inline-flex cursor-pointer items-center gap-1.5 rounded-md border border-border/70 bg-background px-2.5 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:border-border hover:text-foreground"
    >
      {icon}
      {label}
    </a>
  );
}
