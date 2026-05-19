"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import {
  ArrowUpDown,
  ArrowUpRight,
  BellRing,
  Code as CodeIcon,
  Download as DownloadIcon,
  Search,
  Sparkles,
} from "lucide-react";
import { Input } from "@/components/ui/input";
import { humanizeCron } from "@/lib/cron-format";
import type { PublicScreening } from "@/app/actions/public-screenings";

type Props = {
  screenings: PublicScreening[];
  subscribedIds: string[];
};

type SortKey = "latest" | "downloads";

function formatCount(n: number): string {
  if (n < 1000) return n.toString();
  if (n < 10_000) return `${(n / 1000).toFixed(1).replace(/\.0$/, "")}k`;
  return `${Math.round(n / 1000)}k`;
}

function formatRelative(iso: string | null): string {
  if (!iso) return "Not run yet";
  const ms = Date.now() - new Date(iso).getTime();
  if (Number.isNaN(ms)) return "—";
  const minutes = Math.floor(ms / 60_000);
  if (minutes < 60) return `${Math.max(1, minutes)}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(iso).toLocaleDateString();
}

export function ScreeningsGalleryList({ screenings, subscribedIds }: Props) {
  const [query, setQuery] = useState("");
  const [activeCategory, setActiveCategory] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>("latest");
  const [showOnlySubscribed, setShowOnlySubscribed] = useState(false);

  const subscribedSet = useMemo(() => new Set(subscribedIds), [subscribedIds]);
  const subscribedCount = subscribedSet.size;

  const categories = useMemo(() => {
    const set = new Set<string>();
    for (const s of screenings) if (s.category) set.add(s.category);
    return [...set].sort();
  }, [screenings]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const base = screenings.filter((s) => {
      if (showOnlySubscribed && !subscribedSet.has(s.id)) return false;
      if (activeCategory && s.category !== activeCategory) return false;
      if (!q) return true;
      const hay = [s.name, s.category ?? "", s.description ?? "", s.slug]
        .join(" ")
        .toLowerCase();
      return hay.includes(q);
    });
    if (sortKey === "downloads") {
      return [...base].sort(
        (a, b) =>
          (b.download_count ?? 0) - (a.download_count ?? 0) ||
          new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
      );
    }
    return base;
  }, [screenings, query, activeCategory, sortKey, showOnlySubscribed, subscribedSet]);

  return (
    <>
      {/* Filter strip — search + sort left, category pills right. */}
      <div className="mt-10 flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div className="flex w-full max-w-xl items-center gap-2">
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search screenings…"
              className="h-10 bg-background pl-9 font-medium placeholder:font-normal"
            />
          </div>
          <SortToggle value={sortKey} onChange={setSortKey} />
        </div>

        {(categories.length > 0 || subscribedCount > 0) && (
          <nav
            aria-label="Filter by category"
            className="-mx-1 flex flex-wrap gap-1.5 md:mx-0"
          >
            <CategoryPill
              label="All"
              active={activeCategory === null && !showOnlySubscribed}
              onClick={() => {
                setActiveCategory(null);
                setShowOnlySubscribed(false);
              }}
              count={screenings.length}
            />
            {subscribedCount > 0 && (
              <CategoryPill
                label="Subscribed"
                active={showOnlySubscribed}
                onClick={() => setShowOnlySubscribed((v) => !v)}
                count={subscribedCount}
                accent
              />
            )}
            {categories.map((c) => (
              <CategoryPill
                key={c}
                label={c}
                active={activeCategory === c}
                onClick={() =>
                  setActiveCategory((prev) => (prev === c ? null : c))
                }
                count={screenings.filter((s) => s.category === c).length}
              />
            ))}
          </nav>
        )}
      </div>

      {filtered.length === 0 ? (
        <div className="mt-16 rounded-lg border border-dashed border-border/70 px-6 py-14 text-center">
          <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
            No matches
          </p>
          <p className="mt-2 text-sm text-foreground">
            {query || activeCategory
              ? "Try a different search or clear the filter."
              : "No public screenings published yet — check back soon."}
          </p>
        </div>
      ) : (
        <ol className="mt-8 border-t border-border/70">
          {filtered.map((s, index) => (
            <ScreeningRow
              key={s.id}
              screening={s}
              index={index}
              sortKey={sortKey}
              isSubscribed={subscribedSet.has(s.id)}
            />
          ))}
        </ol>
      )}
    </>
  );
}

function SortToggle({
  value,
  onChange,
}: {
  value: SortKey;
  onChange: (next: SortKey) => void;
}) {
  const next: SortKey = value === "latest" ? "downloads" : "latest";
  const label = value === "latest" ? "Latest" : "Most downloaded";
  return (
    <button
      type="button"
      onClick={() => onChange(next)}
      aria-label={`Sort: ${label}. Click to switch.`}
      className="inline-flex h-10 shrink-0 cursor-pointer items-center gap-1.5 rounded-md border border-border/70 bg-background px-3 text-xs font-medium text-muted-foreground transition-colors hover:border-border hover:text-foreground"
    >
      <ArrowUpDown className="h-3.5 w-3.5" />
      <span className="hidden sm:inline">{label}</span>
    </button>
  );
}

function CategoryPill({
  label,
  active,
  onClick,
  count,
  accent = false,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
  count: number;
  accent?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={
        "group inline-flex cursor-pointer items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition-colors " +
        (active
          ? "border-primary/60 bg-primary/10 text-primary"
          : accent
            ? "border-primary/40 bg-background text-primary/80 hover:border-primary/60 hover:text-primary"
            : "border-border/70 bg-background text-muted-foreground hover:border-border hover:text-foreground")
      }
    >
      {accent && <BellRing className="h-3 w-3" />}
      {label}
      <span
        className={
          "tabular-nums " +
          (active
            ? "text-primary/80"
            : accent
              ? "text-primary/60"
              : "text-muted-foreground/70")
        }
      >
        {count}
      </span>
    </button>
  );
}

function ScreeningRow({
  screening,
  index,
  sortKey,
  isSubscribed,
}: {
  screening: PublicScreening;
  index: number;
  sortKey: SortKey;
  isSubscribed: boolean;
}) {
  const ranToday = Boolean(
    screening.last_run_at &&
      Date.now() - new Date(screening.last_run_at).getTime() <
        24 * 60 * 60 * 1000,
  );
  const detailHref = `/marketscreenings/${screening.slug}`;

  return (
    <li
      className="group relative animate-screening-row-in border-b border-border/70 transition-colors hover:bg-muted/40 focus-within:bg-muted/40"
      style={{ animationDelay: `${Math.min(index, 12) * 40}ms` }}
    >
      {/* Full-row overlay link sits behind action buttons. */}
      <Link
        href={detailHref}
        aria-label={`Open ${screening.name}`}
        className="absolute inset-0 z-0 rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60"
      />

      <div className="relative z-10 grid grid-cols-12 items-start gap-x-6 gap-y-3 px-1 py-7 pointer-events-none">
        {/* Index — turns amber for the top 3 when sorted by downloads. */}
        <div className="col-span-2 md:col-span-1">
          <span
            className={
              "font-mono text-xs tabular-nums " +
              (sortKey === "downloads" && index < 3
                ? "text-primary"
                : "text-muted-foreground/70")
            }
          >
            {(index + 1).toString().padStart(2, "0")}
          </span>
        </div>

        {/* Title block */}
        <div className="col-span-10 md:col-span-7">
          <div className="flex flex-wrap items-center gap-2 font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
            {screening.category && (
              <span className="text-foreground/70">{screening.category}</span>
            )}
            {screening.category && (
              <span aria-hidden className="text-border">
                ·
              </span>
            )}
            <span>{humanizeCron(screening.schedule, screening.timezone)}</span>
            {screening.llm_prompt && (
              <>
                <span aria-hidden className="text-border">
                  ·
                </span>
                <span
                  title="Each ticker gets an LLM analysis with notes and entry levels"
                  className="inline-flex items-center gap-1 text-primary/80"
                >
                  <Sparkles className="h-3 w-3" />
                  AI analysis
                </span>
              </>
            )}
          </div>

          <h2 className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-2xl font-semibold leading-tight tracking-tight text-foreground transition-colors group-hover:text-primary">
            <span>{screening.name}</span>
            {isSubscribed && (
              <span
                title="You are subscribed"
                className="pointer-events-auto inline-flex items-center gap-1 rounded-full border border-primary/40 bg-primary/10 px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.18em] text-primary"
              >
                <BellRing className="h-2.5 w-2.5" />
                Subscribed
              </span>
            )}
          </h2>

          {screening.description && (
            <p className="mt-2 max-w-[62ch] text-sm leading-6 text-muted-foreground line-clamp-2">
              {screening.description}
            </p>
          )}
        </div>

        {/* Right column: status + actions. Re-enable pointer events on
            interactive children so they sit above the overlay link. */}
        <div className="col-span-12 flex items-center justify-between gap-3 md:col-span-4 md:flex-col md:items-end md:justify-start">
          <div className="pointer-events-auto flex items-center gap-2 font-mono text-[11px] tabular-nums text-muted-foreground">
            <SignalDot live={ranToday} triggered={screening.last_triggered} />
            <span>{formatRelative(screening.last_run_at)}</span>
          </div>

          <div className="pointer-events-auto flex items-center gap-1">
            <a
              href={`/marketscreenings/${screening.slug}/export`}
              download
              title={`Download latest results as CSV — ${screening.download_count} download${screening.download_count === 1 ? "" : "s"}`}
              aria-label="Download latest results as CSV"
              className="group/dl inline-flex cursor-pointer items-center gap-1.5 rounded-md border border-transparent px-1.5 py-1 text-[11px] font-mono tabular-nums text-muted-foreground transition-colors hover:border-border hover:bg-background hover:text-foreground"
            >
              <DownloadIcon className="h-3.5 w-3.5" />
              <span
                className={
                  screening.download_count > 0
                    ? "text-foreground/80 group-hover/dl:text-foreground"
                    : "text-muted-foreground/60"
                }
              >
                {formatCount(screening.download_count ?? 0)}
              </span>
            </a>
            <SecondaryAction
              href={`/api/public-screenings/${screening.slug}`}
              title="Fetch latest results as JSON"
              external
            >
              <CodeIcon className="h-3.5 w-3.5" />
            </SecondaryAction>
            <span
              aria-hidden
              className="ml-1 inline-flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition-all group-hover:translate-x-0.5 group-hover:text-primary"
            >
              <ArrowUpRight className="h-4 w-4" />
            </span>
          </div>
        </div>
      </div>
    </li>
  );
}

function SignalDot({
  live,
  triggered,
}: {
  live: boolean;
  triggered: boolean | null;
}) {
  if (live && triggered) {
    return (
      <span className="relative inline-flex h-2 w-2 items-center justify-center">
        <span className="absolute inline-flex h-full w-full animate-signal-pulse rounded-full bg-emerald-400/60" />
        <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-emerald-400" />
      </span>
    );
  }
  if (live) {
    return (
      <span className="relative inline-flex h-2 w-2 items-center justify-center">
        <span className="absolute inline-flex h-full w-full animate-signal-pulse rounded-full bg-primary/50" />
        <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-primary" />
      </span>
    );
  }
  return <span className="inline-block h-1.5 w-1.5 rounded-full bg-border" />;
}

function SecondaryAction({
  href,
  title,
  children,
  download,
  external,
}: {
  href: string;
  title: string;
  children: React.ReactNode;
  download?: boolean;
  external?: boolean;
}) {
  return (
    <a
      href={href}
      title={title}
      aria-label={title}
      download={download}
      target={external ? "_blank" : undefined}
      rel={external ? "noopener noreferrer" : undefined}
      onClick={(e) => e.stopPropagation()}
      className="inline-flex h-7 w-7 cursor-pointer items-center justify-center rounded-md border border-transparent text-muted-foreground transition-colors hover:border-border hover:bg-background hover:text-foreground"
    >
      {children}
    </a>
  );
}
