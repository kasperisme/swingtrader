import type { Metadata } from "next";
import { FileText, ArrowUpRight } from "lucide-react";
import { SubscribeForm } from "./_components/subscribe-form";

// Real example briefing, served from /public. Shown on the page so visitors
// can see exactly what they'll receive before subscribing.
const SAMPLE_PDF = "/sample-news-briefing.pdf";
const SAMPLE_DATE = "Jun 11, 2026";

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

          <a
            href={SAMPLE_PDF}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-5 inline-flex items-center gap-2 self-start text-sm font-semibold text-amber-400 underline-offset-4 transition-colors hover:text-amber-300 hover:underline"
          >
            <FileText className="h-4 w-4" />
            See a real sample briefing (PDF)
            <ArrowUpRight className="h-3.5 w-3.5" />
          </a>

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

      {/* Sample briefing — show, don't tell */}
      <section className="mt-16 border-t border-border pt-12 lg:mt-20 lg:pt-16">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="font-mono text-xs uppercase tracking-[0.2em] text-amber-500">
              Sample
            </p>
            <h2 className="mt-2 text-balance text-2xl font-bold tracking-tight sm:text-3xl">
              See exactly what lands in your inbox
            </h2>
            <p className="mt-2 max-w-prose text-sm leading-relaxed text-muted-foreground">
              A real briefing PDF — summaries, sentiment and an impact score for
              every story. The same clean format you&apos;ll get every weekday,
              an hour before the open.
            </p>
          </div>
          <a
            href={SAMPLE_PDF}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex shrink-0 items-center gap-2 rounded-xl bg-amber-500 px-5 py-2.5 text-sm font-semibold text-black shadow-lg shadow-amber-500/20 transition-colors hover:bg-amber-400"
          >
            <FileText className="h-4 w-4" />
            Open full sample
            <ArrowUpRight className="h-4 w-4" />
          </a>
        </div>

        {/* Framed preview: live PDF first page on desktop, document card on
            mobile (mobile browsers render PDFs in iframes inconsistently). An
            overlay anchor owns the click so the embedded PDF never scroll-traps. */}
        <div className="group relative mt-8 overflow-hidden rounded-2xl border border-border bg-card shadow-[0_24px_80px_-32px_rgba(0,0,0,0.6)]">
          <a
            href={SAMPLE_PDF}
            target="_blank"
            rel="noopener noreferrer"
            aria-label="Open the full sample briefing PDF"
            className="absolute inset-0 z-10"
          />

          {/* Faux document toolbar */}
          <div className="flex items-center gap-2 border-b border-border bg-background/60 px-4 py-2.5">
            <span className="h-2.5 w-2.5 rounded-full bg-border" />
            <span className="h-2.5 w-2.5 rounded-full bg-border" />
            <span className="h-2.5 w-2.5 rounded-full bg-border" />
            <span className="ml-2 font-mono text-xs text-muted-foreground">
              news-briefing-{SAMPLE_DATE}.pdf
            </span>
          </div>

          {/* Desktop: real first-page preview */}
          <div className="relative hidden h-[440px] sm:block">
            <iframe
              title="Sample briefing preview"
              src={`${SAMPLE_PDF}#view=FitH&toolbar=0&navpanes=0`}
              className="pointer-events-none h-full w-full"
              loading="lazy"
            />
            <div className="pointer-events-none absolute inset-x-0 bottom-0 h-28 bg-gradient-to-t from-card to-transparent" />
            <span className="pointer-events-none absolute bottom-5 left-1/2 -translate-x-1/2 rounded-full border border-amber-500/30 bg-background/90 px-4 py-1.5 text-xs font-semibold text-amber-400 opacity-0 shadow-lg transition-opacity duration-300 group-hover:opacity-100">
              Open full briefing →
            </span>
          </div>

          {/* Mobile: document card fallback */}
          <div className="flex items-center gap-4 p-6 sm:hidden">
            <span className="inline-flex h-12 w-12 shrink-0 items-center justify-center rounded-xl border border-amber-500/30 bg-amber-500/10">
              <FileText className="h-6 w-6 text-amber-400" />
            </span>
            <div className="min-w-0">
              <p className="text-sm font-semibold">Sample news briefing</p>
              <p className="mt-0.5 text-xs text-muted-foreground">
                Tap to view the full PDF · {SAMPLE_DATE}
              </p>
            </div>
            <ArrowUpRight className="ml-auto h-5 w-5 shrink-0 text-amber-400" />
          </div>
        </div>
      </section>
    </main>
  );
}
