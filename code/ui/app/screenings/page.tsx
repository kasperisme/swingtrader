import Link from "next/link";
import type { Metadata } from "next";
import { listPublicScreenings } from "@/app/actions/public-screenings";
import { humanizeCron } from "@/lib/cron-format";

export const metadata: Metadata = {
  title: "Public Screenings | News Impact Screener",
  description:
    "Curated swing-trading screenings — Stage 2, technicals, fundamentals — delivered on a schedule. Subscribe to get results in your inbox.",
};

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

export default async function ScreeningsGalleryPage() {
  const screenings = await listPublicScreenings();

  return (
    <div className="mx-auto max-w-4xl px-4 py-12 sm:px-6 md:py-20">
      <div className="mb-12">
        <h1 className="text-4xl font-bold tracking-tight">Public Screenings</h1>
        <p className="mt-3 text-base text-muted-foreground">
          Curated screenings that run on a schedule. Subscribe to receive results in
          your inbox and via Telegram.
        </p>
      </div>

      {screenings.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No public screenings published yet — check back soon.
        </p>
      ) : (
        <div className="divide-y divide-border">
          {screenings.map((s, index) => (
            <article key={s.id} className={index === 0 ? "pb-10" : "py-10"}>
              <div className="flex items-center gap-3 text-xs text-muted-foreground">
                {s.category && (
                  <span className="rounded-full border border-border px-2 py-0.5">
                    {s.category}
                  </span>
                )}
                <span>{humanizeCron(s.schedule, s.timezone)}</span>
                <span aria-hidden>·</span>
                <span>Last run: {formatRelative(s.last_run_at)}</span>
              </div>

              <h2 className="mt-3 text-2xl font-semibold tracking-tight leading-snug">
                <Link
                  href={`/screenings/${s.slug}`}
                  className="hover:text-primary transition-colors"
                >
                  {s.name}
                </Link>
              </h2>

              {s.description && (
                <p className="mt-3 text-sm leading-6 text-muted-foreground">
                  {s.description}
                </p>
              )}

              <div className="mt-4">
                <Link
                  href={`/screenings/${s.slug}`}
                  className="text-sm font-medium text-primary hover:underline"
                >
                  View screening →
                </Link>
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
