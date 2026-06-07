import type { Metadata } from "next";
import { Suspense } from "react";
import { connection } from "next/server";
import {
  getMySubscriptionIds,
  listMarketScreenings,
} from "@/app/actions/market-screenings";
import { ScreeningsGalleryList } from "./_components/screenings-gallery-list";

const GALLERY_DESCRIPTION =
  "Curated swing-trading screenings — Stage 2, technicals, fundamentals — delivered on a schedule. Subscribe to get results in your inbox.";

export const metadata: Metadata = {
  title: "Market Screenings | News Impact Screener",
  description: GALLERY_DESCRIPTION,
  alternates: { canonical: "/marketscreenings" },
  openGraph: {
    type: "website",
    title: "Market Screenings",
    description: GALLERY_DESCRIPTION,
    url: "/marketscreenings",
  },
  twitter: {
    card: "summary_large_image",
    title: "Market Screenings",
    description: GALLERY_DESCRIPTION,
  },
};

function formatRelative(iso: string | null): string {
  if (!iso) return "—";
  const ms = Date.now() - new Date(iso).getTime();
  if (Number.isNaN(ms)) return "—";
  const minutes = Math.floor(ms / 60_000);
  if (minutes < 60) return `${Math.max(1, minutes)}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d`;
  return new Date(iso).toLocaleDateString();
}

// The page shell prerenders statically; the screening data + per-user
// subscription state (auth cookies) stream inside the Suspense boundary at
// request time. Under Next's Cache Components, request-time data must live in a
// Suspense boundary — reading it at the top level would reject the in-flight
// fetch when the static prerender completes.
export default function ScreeningsGalleryPage() {
  return (
    <div className="relative isolate">
      {/* Decorative grid backdrop — pointer-events safe, sits behind everything. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 -z-10 h-[420px] bg-terminal-grid opacity-[0.35] [mask-image:linear-gradient(to_bottom,black,transparent)]"
      />

      <div className="mx-auto max-w-6xl px-4 pt-12 pb-20 sm:px-6 md:pt-20">
        <Suspense fallback={<GallerySkeleton />}>
          <GalleryContent />
        </Suspense>
      </div>
    </div>
  );
}

async function GalleryContent() {
  // Defer to request time: the data is per-user (subscriptions) and live, so it
  // must not run during the static prerender. connection() suspends this branch
  // until a request exists, so the service-client fetch never starts mid-prerender.
  await connection();

  const [screenings, subscribedIds] = await Promise.all([
    listMarketScreenings(),
    getMySubscriptionIds(),
  ]);

  const lastUpdated = screenings.reduce<string | null>((acc, s) => {
    if (!s.last_run_at) return acc;
    if (!acc) return s.last_run_at;
    return new Date(s.last_run_at) > new Date(acc) ? s.last_run_at : acc;
  }, null);

  const triggeredCount = screenings.filter((s) => s.last_triggered).length;

  return (
    <>
      {/* Editorial header — 12 column asymmetric split. */}
      <header className="grid grid-cols-12 gap-x-6 gap-y-8 border-b border-border/70 pb-10">
          <div className="col-span-12 md:col-span-8">
            <div className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.22em] text-muted-foreground">
              <span className="inline-block h-[1px] w-6 bg-primary" />
              <span>Gallery</span>
              <span className="text-border">/</span>
              <span className="text-foreground/70">
                {screenings.length.toString().padStart(2, "0")} screenings
              </span>
            </div>

            <h1 className="mt-5 text-5xl font-bold leading-[0.95] tracking-tight md:text-6xl">
              Market
              <br />
              <span className="text-foreground/60">screenings.</span>
            </h1>

            <p className="mt-6 max-w-[58ch] text-base leading-7 text-muted-foreground">
              Curated, opinionated filters that run on a cron — Stage&nbsp;2, trend
              templates, fundamentals. Subscribe to receive results in your inbox
              and via Telegram, or pull them through the JSON API.
            </p>
          </div>

          {/* Stats column — sits to the right on desktop, stacks below on mobile. */}
          <aside className="col-span-12 md:col-span-4 md:pt-1">
            <dl className="grid grid-cols-3 gap-px overflow-hidden rounded-lg border border-border/70 bg-border/70 md:grid-cols-1">
              <Stat
                label="Last run"
                value={formatRelative(lastUpdated)}
                hint={lastUpdated ? "ago" : null}
              />
              <Stat
                label="Triggered"
                value={triggeredCount.toString()}
                hint="last cycle"
                accent={triggeredCount > 0}
              />
              <Stat
                label="Tracking"
                value={screenings.length.toString()}
                hint="published"
              />
            </dl>
          </aside>
      </header>

      <ScreeningsGalleryList
        screenings={screenings}
        subscribedIds={subscribedIds}
      />
    </>
  );
}

function GallerySkeleton() {
  return (
    <div className="animate-pulse">
      <div className="grid grid-cols-12 gap-x-6 gap-y-8 border-b border-border/70 pb-10">
        <div className="col-span-12 space-y-5 md:col-span-8">
          <div className="h-3 w-40 rounded bg-muted" />
          <div className="h-16 w-64 rounded bg-muted" />
          <div className="h-12 w-full max-w-[58ch] rounded bg-muted" />
        </div>
        <aside className="col-span-12 md:col-span-4">
          <div className="h-40 rounded-lg border border-border/70 bg-muted/40" />
        </aside>
      </div>
      <div className="mt-10 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="h-44 rounded-xl border border-border/70 bg-muted/40" />
        ))}
      </div>
    </div>
  );
}

function Stat({
  label,
  value,
  hint,
  accent = false,
}: {
  label: string;
  value: string;
  hint?: string | null;
  accent?: boolean;
}) {
  return (
    <div className="bg-background/70 px-4 py-3.5">
      <dt className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
        {label}
      </dt>
      <dd className="mt-1 flex items-baseline gap-1.5">
        <span
          className={
            "text-2xl font-semibold tabular-nums " +
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
