import Link from "next/link";
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import {
  getMySubscription,
  getPublicScreeningBySlug,
  getPublicScreeningResults,
} from "@/app/actions/public-screenings";
import { humanizeCron } from "@/lib/cron-format";
import { SubscribeButton } from "../_components/subscribe-button";

type Props = { params: Promise<{ slug: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const s = await getPublicScreeningBySlug(slug);
  if (!s) return { title: "Screening not found" };
  return {
    title: `${s.name} | Public Screenings`,
    description:
      s.description ??
      `${s.name} — curated swing-trading screening that runs on ${humanizeCron(s.schedule)}.`,
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

// Strip a small set of HTML tags that Telegram-format summaries contain.
// We render web output as plain text to avoid injection from script authors.
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

  const [results, subscription] = await Promise.all([
    getPublicScreeningResults(screening.id, 10),
    isAuthed
      ? getMySubscription(screening.id)
      : Promise.resolve({ isSubscribed: false, notificationsEnabled: false }),
  ]);

  return (
    <div className="mx-auto max-w-3xl px-4 py-12 sm:px-6 md:py-20">
      <Link
        href="/screenings"
        className="text-xs text-muted-foreground hover:text-foreground"
      >
        ← All screenings
      </Link>

      <header className="mt-6 mb-10">
        <div className="flex items-center gap-3 text-xs text-muted-foreground">
          {screening.category && (
            <span className="rounded-full border border-border px-2 py-0.5">
              {screening.category}
            </span>
          )}
          <span>{humanizeCron(screening.schedule, screening.timezone)}</span>
        </div>

        <h1 className="mt-3 text-4xl font-bold tracking-tight">
          {screening.name}
        </h1>

        {screening.description && (
          <p className="mt-4 text-base leading-7 text-muted-foreground">
            {screening.description}
          </p>
        )}

        <div className="mt-6">
          <SubscribeButton
            screeningSlug={screening.slug}
            screeningName={screening.name}
            isAuthed={isAuthed}
            initialSubscribed={subscription.isSubscribed}
          />
        </div>
      </header>

      <section>
        <h2 className="text-sm font-semibold tracking-wide uppercase text-muted-foreground">
          Recent runs
        </h2>
        {results.length === 0 ? (
          <p className="mt-4 text-sm text-muted-foreground">
            This screening hasn&rsquo;t run yet. Subscribe to be notified when it does.
          </p>
        ) : (
          <ol className="mt-4 divide-y divide-border">
            {results.map((r) => (
              <li key={r.id} className="py-5">
                <div className="flex items-center gap-3 text-xs text-muted-foreground">
                  <time dateTime={r.run_at}>{formatRunDate(r.run_at)}</time>
                  <span aria-hidden>·</span>
                  <span
                    className={
                      r.triggered
                        ? "text-emerald-500"
                        : "text-muted-foreground"
                    }
                  >
                    {r.triggered ? "Triggered" : "No trigger"}
                  </span>
                </div>
                {r.summary && (
                  <p className="mt-2 text-sm leading-6 whitespace-pre-wrap text-foreground/90">
                    {stripHtml(r.summary)}
                  </p>
                )}
              </li>
            ))}
          </ol>
        )}
      </section>
    </div>
  );
}
