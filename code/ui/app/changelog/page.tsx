import { Suspense } from "react";
import { isSanityConfigured, sanityFetch } from "@/lib/sanity/client";
import { changelogEntriesQuery } from "@/lib/sanity/queries";
import type { ChangelogEntry } from "@/lib/sanity/types";
import { CavemanContent } from "@/components/caveman-content";

export const metadata = {
  title: "Changelog | News Impact Screener",
  description: "What's new — feature releases, improvements, and fixes.",
};

const TAG_STYLES: Record<string, string> = {
  feature: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
  improvement: "bg-blue-500/10 text-blue-400 border-blue-500/20",
  fix: "bg-amber-500/10 text-amber-400 border-amber-500/20",
  breaking: "bg-red-500/10 text-red-400 border-red-500/20",
};

function Tag({ value }: { value: string }) {
  const style = TAG_STYLES[value] ?? "bg-muted text-muted-foreground border-border";
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium capitalize ${style}`}
    >
      {value}
    </span>
  );
}

function formatDate(date: string): string {
  const parsed = new Date(date);
  if (Number.isNaN(parsed.getTime())) return date;
  return new Intl.DateTimeFormat("en-US", {
    year: "numeric",
    month: "long",
    day: "numeric",
  }).format(parsed);
}

async function ChangelogContent() {
  if (!isSanityConfigured) {
    return (
      <p className="text-sm text-muted-foreground">
        Sanity is not configured. Set{" "}
        <code className="rounded bg-muted px-1.5 py-0.5 text-xs font-mono">NEXT_PUBLIC_SANITY_PROJECT_ID</code> to
        enable changelog content.
      </p>
    );
  }

  const entries = await sanityFetch<ChangelogEntry[]>(changelogEntriesQuery);

  if (entries.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">No changelog entries yet.</p>
    );
  }

  return (
    <div className="relative">
      {/* Vertical timeline line */}
      <div className="absolute left-0 top-2 bottom-0 w-px bg-border md:left-[7.5rem]" aria-hidden />

      <div className="space-y-12">
        {entries.map((entry) => (
          <div key={entry._id} className="relative flex flex-col gap-4 md:flex-row md:gap-8">
            {/* Date label — left column on md+ */}
            <div className="md:w-28 md:shrink-0 md:text-right">
              <time
                dateTime={entry.date}
                className="text-xs font-medium text-muted-foreground tabular-nums"
              >
                {formatDate(entry.date)}
              </time>
            </div>

            {/* Dot on the line */}
            <div
              className="absolute left-[-4px] top-1 hidden h-2.5 w-2.5 rounded-full border-2 border-primary bg-background md:left-[calc(7.5rem-4px)] md:block"
              aria-hidden
            />

            {/* Content */}
            <div className="flex-1 pl-4 md:pl-8">
              {/* Tags */}
              {entry.tags && entry.tags.length > 0 && (
                <div className="mb-2 flex flex-wrap gap-1.5">
                  {entry.tags.map((tag) => (
                    <Tag key={tag} value={tag} />
                  ))}
                </div>
              )}

              <h2 className="text-lg font-semibold tracking-tight">{entry.title}</h2>

              {entry.body?.length > 0 && (
                <div className="mt-3 text-sm leading-7 text-muted-foreground prose prose-sm dark:prose-invert max-w-none">
                  <CavemanContent body={entry.body} cavemanBody={entry.cavemanBody} />
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function ChangelogPage() {
  return (
    <div className="mx-auto max-w-3xl px-4 py-12 sm:px-6 md:py-20">
      <div className="mb-14">
        <h1 className="text-4xl font-bold tracking-tight">Changelog</h1>
        <p className="mt-3 text-base text-muted-foreground">
          New features, improvements, and fixes — shipped to{" "}
          <span className="font-medium text-foreground">newsimpactscreener</span>.
        </p>
      </div>

      <Suspense
        fallback={
          <p className="text-sm text-muted-foreground animate-pulse">Loading changelog…</p>
        }
      >
        <ChangelogContent />
      </Suspense>
    </div>
  );
}
