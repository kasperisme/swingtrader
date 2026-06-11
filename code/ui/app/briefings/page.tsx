import type { Metadata } from "next";
import { SubscribeForm } from "./_components/subscribe-form";

export const metadata: Metadata = {
  title: "Daily News Briefings — your tickers & tags, one PDF a day",
  description:
    "A free daily email briefing: the last 24 hours of news, summaries and market impact for the tickers and tags you choose — delivered as a clean PDF an hour before the market opens. No account required.",
  alternates: { canonical: "/briefings" },
  openGraph: {
    type: "website",
    url: "/briefings",
    title: "Daily News Briefings — News Impact Screener",
    description:
      "Pick your tickers and tags. Get a clean PDF of the last 24h of news, summaries and impact every weekday morning. Free, no account.",
  },
};

const STEPS: { title: string; body: string }[] = [
  {
    title: "Pick what you follow",
    body: "Add the tickers and tags you care about — a few names, a whole sector, or a theme like #ai or #earnings.",
  },
  {
    title: "Get one clean PDF",
    body: "Every weekday, an hour before the NYSE opens, we package the last 24 hours of news, sentiment and impact into a structured briefing.",
  },
  {
    title: "Stay in control",
    body: "Edit your tickers and tags or unsubscribe from any email in one click. No account, no password, no spam.",
  },
];

export default function BriefingsPage() {
  return (
    <main className="mx-auto w-full max-w-5xl px-4 py-12 lg:px-6 lg:py-16">
      <div className="grid gap-10 lg:grid-cols-[1.05fr_0.95fr] lg:gap-14">
        {/* Pitch */}
        <section className="flex flex-col justify-center">
          <p className="font-mono text-xs uppercase tracking-[0.2em] text-amber-500">
            Free · No account
          </p>
          <h1 className="mt-3 text-balance text-3xl font-bold leading-tight sm:text-4xl">
            Your morning news briefing, built around{" "}
            <span className="text-amber-500">your</span> tickers.
          </h1>
          <p className="mt-4 max-w-prose text-base leading-relaxed text-muted-foreground">
            Tell us the tickers and tags you watch. Every weekday — an hour
            before the market opens — we send a clean PDF of the last 24 hours of
            news, with summaries and the impact score for each story. Catch what
            moved your names while you were asleep.
          </p>

          <ol className="mt-8 space-y-5">
            {STEPS.map((s, i) => (
              <li key={s.title} className="flex gap-4">
                <span className="mt-0.5 inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-amber-500/40 font-mono text-sm text-amber-500">
                  {i + 1}
                </span>
                <div>
                  <h3 className="text-sm font-semibold text-foreground">{s.title}</h3>
                  <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
                    {s.body}
                  </p>
                </div>
              </li>
            ))}
          </ol>
        </section>

        {/* Sign-up card */}
        <section className="lg:pt-2">
          <div className="rounded-2xl border border-border bg-card p-6 shadow-sm sm:p-8">
            <h2 className="text-lg font-semibold">Start your briefing</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Add a few tickers or tags, drop your email, and your first briefing
              is on its way.
            </p>
            <div className="mt-6">
              <SubscribeForm source="briefings_page" />
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}
