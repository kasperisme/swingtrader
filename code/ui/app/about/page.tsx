import fs from "node:fs";
import path from "node:path";
import type { Metadata } from "next";
import Link from "next/link";
import {
  SITE_URL,
  SITE_NAME,
  SITE_SAME_AS,
  SITE_X_PROFILE_URL,
  SITE_X_HANDLE,
  SITE_INSTAGRAM_PROFILE_URL,
  SITE_INSTAGRAM_HANDLE,
  AUTHOR,
} from "@/lib/site";

const CANONICAL = "/about";
const TITLE = `About ${SITE_NAME}`;
const DESCRIPTION = `Who runs ${SITE_NAME}, how every story is scored and mapped to tickers, and the editorial rules the analysis is held to.`;

export const metadata: Metadata = {
  title: "About",
  description: DESCRIPTION,
  alternates: { canonical: CANONICAL },
  openGraph: { type: "profile", url: CANONICAL, title: TITLE, description: DESCRIPTION },
  twitter: { card: "summary", title: TITLE, description: DESCRIPTION },
};

/**
 * Resolve the author portrait from `public/`, trying each web-safe extension.
 * Returns null when no file is there, so the page renders a monogram instead
 * of a broken image — the photo can land later without a code change.
 */
function findPortrait(basename: string): string | null {
  for (const ext of ["webp", "jpg", "jpeg", "png"]) {
    const rel = `/${basename}.${ext}`;
    if (fs.existsSync(path.join(process.cwd(), "public", `${basename}.${ext}`))) {
      return rel;
    }
  }
  return null;
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <p className="mb-3 inline-flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.2em] text-amber-500/80">
      <span className="h-px w-6 bg-amber-500/60" />
      {children}
    </p>
  );
}

function Step({
  n,
  title,
  children,
}: {
  n: number;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <li className="grid grid-cols-[1.75rem_1fr] gap-4">
      <span className="mt-0.5 font-mono text-[10px] uppercase tracking-widest text-muted-foreground/70">
        {String(n).padStart(2, "0")}
      </span>
      <div className="min-w-0">
        <h3 className="text-sm font-semibold tracking-tight text-foreground">{title}</h3>
        <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">{children}</p>
      </div>
    </li>
  );
}

export default function AboutPage() {
  const portrait = findPortrait(AUTHOR.photoBasename);
  const initials = AUTHOR.name
    .split(/\s+/)
    .map((w) => w[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();

  // Person node, shared `@id` with the Organization graph in the root layout so
  // the founder, the byline on every article and this page resolve to one
  // entity rather than three lookalikes.
  const jsonLd = {
    "@context": "https://schema.org",
    "@graph": [
      {
        "@type": "AboutPage",
        "@id": `${SITE_URL}${CANONICAL}#page`,
        url: `${SITE_URL}${CANONICAL}`,
        name: TITLE,
        description: DESCRIPTION,
        about: { "@id": `${SITE_URL}/#organization` },
        mainEntity: { "@id": `${SITE_URL}/#author` },
        publisher: { "@id": `${SITE_URL}/#organization` },
      },
      {
        "@type": "Person",
        "@id": `${SITE_URL}/#author`,
        name: AUTHOR.name,
        jobTitle: AUTHOR.role,
        url: `${SITE_URL}${CANONICAL}`,
        image: portrait ? `${SITE_URL}${portrait}` : undefined,
        description: AUTHOR.background || undefined,
        worksFor: { "@id": `${SITE_URL}/#organization` },
        sameAs: SITE_SAME_AS,
      },
      {
        "@type": "BreadcrumbList",
        itemListElement: [
          { "@type": "ListItem", position: 1, name: "Home", item: SITE_URL },
          { "@type": "ListItem", position: 2, name: "About", item: `${SITE_URL}${CANONICAL}` },
        ],
      },
    ],
  };

  return (
    <div className="mx-auto flex w-full min-w-0 max-w-3xl flex-col gap-12 px-4 py-10 sm:px-6 lg:px-8">
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />

      {/* ── Breadcrumb ─────────────────────────────────────────────── */}
      <nav aria-label="Breadcrumb" className="-mb-6 text-xs text-muted-foreground">
        <ol className="flex flex-wrap items-center gap-1.5">
          <li>
            <Link href="/" className="hover:text-foreground">
              Home
            </Link>
          </li>
          <li aria-hidden className="text-muted-foreground/50">
            /
          </li>
          <li className="font-medium text-foreground" aria-current="page">
            About
          </li>
        </ol>
      </nav>

      {/* ── Header ─────────────────────────────────────────────────── */}
      <header className="border-b border-border/60 pb-8">
        <SectionLabel>About</SectionLabel>
        <h1 className="text-3xl font-bold leading-tight tracking-tight md:text-4xl">
          News connected to markets — and someone accountable for the connection.
        </h1>
        <p className="mt-4 text-base leading-relaxed text-muted-foreground">
          {SITE_NAME} reads market news as it breaks, pulls out the claims that can
          actually move a price, and maps each one to the tickers it touches. This
          page explains who is behind it, how the analysis is produced, and the rules
          it is held to.
        </p>
      </header>

      {/* ── Who ────────────────────────────────────────────────────── */}
      <section>
        <SectionLabel>Who writes this</SectionLabel>
        <div className="flex flex-col gap-5 sm:flex-row sm:items-start sm:gap-6">
          {portrait ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={portrait}
              alt={`${AUTHOR.name}, ${AUTHOR.role} of ${SITE_NAME}`}
              width={112}
              height={112}
              className="h-28 w-28 shrink-0 rounded-lg border border-border object-cover"
            />
          ) : (
            <div
              aria-hidden
              className="flex h-28 w-28 shrink-0 items-center justify-center rounded-lg border border-border bg-muted/40 font-mono text-2xl tracking-widest text-muted-foreground"
            >
              {initials}
            </div>
          )}
          <div className="min-w-0">
            <h2 className="text-xl font-semibold tracking-tight">{AUTHOR.name}</h2>
            <p className="mt-1 font-mono text-[11px] uppercase tracking-[0.2em] text-amber-500/80">
              {AUTHOR.role}
            </p>
            <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
              {SITE_NAME} is built and written by {AUTHOR.name} — the scoring pipeline,
              the company-relationship graph behind the ticker mapping, the research
              methodology and the writing. There is no anonymous editorial desk here;
              when the analysis is wrong, it is wrong under a name.
            </p>
            {AUTHOR.background ? (
              <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
                {AUTHOR.background}
              </p>
            ) : null}
            <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-muted-foreground">
              <a
                href={SITE_X_PROFILE_URL}
                target="_blank"
                rel="me noopener noreferrer"
                className="transition-colors hover:text-foreground"
              >
                {SITE_X_HANDLE} on X
              </a>
              <a
                href={SITE_INSTAGRAM_PROFILE_URL}
                target="_blank"
                rel="me noopener noreferrer"
                className="transition-colors hover:text-foreground"
              >
                {SITE_INSTAGRAM_HANDLE} on Instagram
              </a>
            </div>
          </div>
        </div>
      </section>

      {/* ── Method ─────────────────────────────────────────────────── */}
      <section>
        <SectionLabel>How a story becomes a score</SectionLabel>
        <p className="mb-6 text-sm leading-relaxed text-muted-foreground">
          Nothing here is a hand-picked opinion piece. Every story runs through the
          same pipeline, and every number on the site is the output of a step you can
          point at.
        </p>
        <ol className="flex flex-col gap-5">
          <Step n={1} title="Ingest">
            Market news is pulled continuously from wire services and publisher feeds.
            We never republish a publisher&apos;s article text — every story links back
            to the original, and what you read here is our analysis of it.
          </Step>
          <Step n={2} title="Extract the claims">
            A story is broken into discrete, checkable claims rather than treated as
            one blob of sentiment. &ldquo;A six-figure H-1B fee has been proposed&rdquo;
            is a claim; the headline around it is not.
          </Step>
          <Step n={3} title="Score each claim for market impact">
            Each claim is scored on how much it can plausibly move a price, and the
            reasoning behind the score is stored and shown alongside it. You see why a
            claim scored what it did, not just the number.
          </Step>
          <Step n={4} title="Map claims to tickers">
            Scores are attached to companies through a typed relationship graph —
            suppliers, customers, competitors, subsidiaries, acquirers — so a story
            about one company reaches the others it actually touches, with the link
            type named rather than inferred from a keyword match.
          </Step>
          <Step n={5} title="Put it on the chart">
            Each{" "}
            <Link href="/quote" className="text-foreground underline underline-offset-4 hover:text-amber-400">
              ticker page
            </Link>{" "}
            plots the scored catalysts on the price history, so a claim&apos;s score
            sits next to what the stock actually did next — including when the two
            disagree.
          </Step>
          <Step n={6} title="Track the theme over time">
            Related stories accumulate into{" "}
            <Link href="/topics" className="text-foreground underline underline-offset-4 hover:text-amber-400">
              topic trackers
            </Link>{" "}
            so a developing story reads as one thread instead of forty disconnected
            headlines.
          </Step>
        </ol>
      </section>

      {/* ── Editorial rules ────────────────────────────────────────── */}
      <section>
        <SectionLabel>Editorial policy</SectionLabel>
        <ul className="flex flex-col gap-4 text-sm leading-relaxed text-muted-foreground">
          <li>
            <span className="font-medium text-foreground">Sources are credited and linked.</span>{" "}
            Every story names its publisher and links to the original. We analyse the
            news; we do not reprint it.
          </li>
          <li>
            <span className="font-medium text-foreground">Nobody pays for coverage.</span>{" "}
            No company can pay to be scored, featured, or scored differently. There is
            no sponsored placement anywhere on the site.
          </li>
          <li>
            <span className="font-medium text-foreground">Predictions are sealed before the outcome exists.</span>{" "}
            Forward predictions in{" "}
            <Link href="/research" className="text-foreground underline underline-offset-4 hover:text-amber-400">
              research
            </Link>{" "}
            are hash-locked at the moment they are made. A prediction whose content no
            longer matches its lock was edited after the fact, and the integrity check
            surfaces it. This exists because our own earlier work failed
            retrospectively — the measurement was designed after the data, and three
            believable numbers were published before the bugs behind them were found.
          </li>
          <li>
            <span className="font-medium text-foreground">Mistakes get corrected in place.</span>{" "}
            When a score, a mapping or a write-up is wrong, it is fixed and the change
            is noted rather than quietly removed.
          </li>
          <li>
            <span className="font-medium text-foreground">Automation is disclosed.</span>{" "}
            Claim extraction, scoring and summarisation are produced by models running
            in the pipeline described above, reviewed by {AUTHOR.name.split(" ")[0]}.
            Where a page is model-generated, it says so.
          </li>
        </ul>
      </section>

      {/* ── Disclaimer ─────────────────────────────────────────────── */}
      <section className="rounded-lg border border-border bg-card p-5">
        <SectionLabel>Important — not investment advice</SectionLabel>
        <div className="flex flex-col gap-3 text-sm leading-relaxed text-muted-foreground">
          <p>
            {SITE_NAME} publishes research and information for educational purposes
            only. Nothing on this site is investment advice, a recommendation, or an
            offer to buy or sell any security. {AUTHOR.name} is not a registered
            investment adviser or broker-dealer, and no content here is tailored to
            your circumstances.
          </p>
          <p>
            Impact scores, sentiment values, price targets and &ldquo;priced-in&rdquo;
            decompositions are model outputs and estimates. They can be wrong, and
            being right in the past does not make them right next time. Trading
            carries risk, including the loss of your entire position.
          </p>
          <p>
            Do your own research and consider speaking to a licensed professional
            before making any investment decision. Full terms are in the{" "}
            <Link href="/terms" className="text-foreground underline underline-offset-4 hover:text-amber-400">
              terms of service
            </Link>{" "}
            and{" "}
            <Link href="/privacy" className="text-foreground underline underline-offset-4 hover:text-amber-400">
              privacy policy
            </Link>
            .
          </p>
        </div>
      </section>

      {/* ── Contact ────────────────────────────────────────────────── */}
      <section className="border-t border-border/60 pt-8">
        <SectionLabel>Contact</SectionLabel>
        <p className="text-sm leading-relaxed text-muted-foreground">
          Corrections, questions, or something we scored wrong — reach{" "}
          {AUTHOR.name.split(" ")[0]} at{" "}
          <a
            href={SITE_X_PROFILE_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="text-foreground underline underline-offset-4 hover:text-amber-400"
          >
            {SITE_X_HANDLE}
          </a>
          . Corrections are taken seriously and acted on.
        </p>
      </section>
    </div>
  );
}
