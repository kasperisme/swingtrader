import Link from "next/link";
import type { Metadata } from "next";

/**
 * The site had no not-found boundary at all, so an unmatched path fell to
 * Next's bare built-in page — and, before the proxy gate was inverted, never
 * even reached it (the auth allow-list 307ed everything unlisted to
 * /auth/login). This is the page a retired URL should land on: a real 404
 * status, noindex, and enough onward links that the visit is not a dead end.
 */
export const metadata: Metadata = {
  title: "Page not found",
  robots: { index: false, follow: true },
};

const DESTINATIONS = [
  { href: "/articles", label: "The Tape", hint: "Every story, scored for market impact" },
  { href: "/quote", label: "Tickers", hint: "Per-symbol catalysts, charts and peers" },
  { href: "/topics", label: "Topics", hint: "Live trackers for the stories that keep moving" },
  { href: "/marketscreenings", label: "Screenings", hint: "Curated swing-trading boards" },
  { href: "/arena", label: "The Arena", hint: "Nine AI agents trading $100,000 each" },
  { href: "/briefings", label: "Daily briefing", hint: "Your tickers, one PDF before the open" },
];

export default function NotFound() {
  return (
    <div className="mx-auto w-full max-w-3xl px-6 py-20 md:py-28">
      <p className="font-mono text-xs uppercase tracking-[0.14em] text-muted-foreground">
        Error 404
      </p>
      <h1 className="mt-4 text-3xl font-semibold tracking-tight md:text-4xl">
        That page isn&apos;t here
      </h1>
      <p className="mt-4 max-w-prose text-sm leading-6 text-muted-foreground">
        The link may be out of date, or the story or ticker it pointed at may no
        longer be covered. Nothing is broken on your end.
      </p>

      <nav aria-label="Elsewhere on the site" className="mt-10">
        <h2 className="font-mono text-xs uppercase tracking-[0.14em] text-muted-foreground">
          Try instead
        </h2>
        <ul className="mt-4 grid gap-px overflow-hidden rounded-lg border border-border bg-border sm:grid-cols-2">
          {DESTINATIONS.map(({ href, label, hint }) => (
            <li key={href} className="bg-background">
              <Link
                href={href}
                className="flex h-full flex-col gap-1 p-4 transition-colors hover:bg-muted focus-visible:bg-muted focus-visible:outline-none"
              >
                <span className="text-sm font-medium">{label}</span>
                <span className="text-xs leading-5 text-muted-foreground">
                  {hint}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      </nav>

      <p className="mt-10 text-sm text-muted-foreground">
        Or head back to the{" "}
        <Link href="/" className="underline underline-offset-2 hover:text-foreground">
          home page
        </Link>
        .
      </p>
    </div>
  );
}
