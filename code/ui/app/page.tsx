import Link from "next/link";
import Image from "next/image";
import { ArrowRight, BarChart3, Compass, Filter, Newspaper, Target, Workflow } from "lucide-react";

type CardItem = {
  title: string;
  description: string;
  icon: React.ComponentType<{ className?: string }>;
};

const benefitCards: CardItem[] = [
  {
    title: "Spot market-moving narratives faster",
    description:
      "See the strongest stories and themes rising across the market, so you focus on what matters first.",
    icon: Newspaper,
  },
  {
    title: "Find stocks and sectors connected to those narratives",
    description:
      "Quickly connect each narrative to the companies and sectors with the highest likely exposure.",
    icon: Target,
  },
  {
    title: "Build a better daily research workflow",
    description:
      "Start your day with clearer direction, less noise, and a repeatable process for idea generation.",
    icon: Workflow,
  },
];

const howItWorksSteps = [
  "Track the strongest news narratives",
  "See which sectors and stocks are most exposed",
  "Screen for possible opportunities",
];

const productValueItems: CardItem[] = [
  {
    title: "Narrative tracking",
    description: "Follow the news themes gaining momentum so you can research with context, not guesswork.",
    icon: BarChart3,
  },
  {
    title: "Company and sector exposure",
    description:
      "Understand which tickers and groups are most tied to each narrative before the move is obvious.",
    icon: Compass,
  },
  {
    title: "Custom screening",
    description: "Filter opportunities by the factors you care about and keep your process consistent.",
    icon: Filter,
  },
];

const trustItems = [
  {
    title: "Who it is for",
    description:
      "Built for traders, investors, and research-focused users who want to connect news to market opportunities faster.",
  },
  {
    title: "How it is different",
    description:
      "A normal stock screener starts with static filters. News Impact Screener starts with live narratives and shows what they may influence.",
  },
  {
    title: "Why it is useful",
    description:
      "It helps you move from headline overload to a clear watchlist and better daily research decisions.",
  },
];

function IconTile({ icon: Icon }: { icon: React.ComponentType<{ className?: string }> }) {
  return (
    <div className="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-border bg-background">
      <Icon className="h-5 w-5 text-foreground" />
    </div>
  );
}

export default function Home() {
  return (
    <main className="min-h-screen bg-background text-foreground">
      <div className="mx-auto max-w-6xl px-6 lg:px-8">
        <header className="flex items-center justify-between border-b border-border py-5">
          <div className="flex items-center gap-2">
            <Image
              src="/icon.png"
              alt="newsimpactscreener logo"
              width={20}
              height={20}
              className="rounded-sm"
            />
            <p className="text-sm font-semibold tracking-tight">newsimpactscreener.com</p>
          </div>
          <div className="flex items-center gap-4">
            <Link
              href="/blog"
              className="text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
            >
              Blog
            </Link>
            <Link
              href="/auth/login"
              className="rounded-md border border-border px-4 py-2 text-sm font-medium text-foreground transition-colors hover:bg-muted"
            >
              Sign in
            </Link>
          </div>
        </header>

        <section className="grid gap-12 py-16 md:grid-cols-2 md:items-center md:py-24">
          <div>
            <p className="text-sm font-medium text-muted-foreground">For traders and investors</p>
            <h1 className="mt-4 text-4xl font-semibold tracking-tight sm:text-5xl">
              See which news stories are moving the market.
            </h1>
            <p className="mt-5 max-w-xl text-base leading-7 text-muted-foreground sm:text-lg">
              News Impact Screener helps traders and investors turn market news into clearer stock
              ideas, sector signals, and faster research.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Link
                href="#final-cta"
                className="inline-flex items-center gap-2 rounded-md bg-foreground px-5 py-3 text-sm font-semibold text-background transition-opacity hover:opacity-90"
              >
                Get Early Access
                <ArrowRight className="h-4 w-4" />
              </Link>
              <Link
                href="#how-it-works"
                className="inline-flex items-center rounded-md border border-border px-5 py-3 text-sm font-semibold text-foreground transition-colors hover:bg-muted"
              >
                See How It Works
              </Link>
            </div>
          </div>

          <div className="rounded-2xl border border-border bg-card p-6 shadow-sm">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Live narrative snapshot</p>
            <div className="mt-5 space-y-3">
              {["AI infrastructure demand", "Rate-cut expectations", "Energy supply pressure"].map((item, index) => (
                <div key={item} className="flex items-center justify-between rounded-lg border border-border bg-background px-4 py-3">
                  <p className="text-sm font-medium">{item}</p>
                  <span className="rounded-full bg-muted px-2.5 py-1 text-xs font-medium text-muted-foreground">
                    #{index + 1}
                  </span>
                </div>
              ))}
            </div>
            <div className="mt-5 rounded-lg border border-border bg-background p-4">
              <p className="text-xs text-muted-foreground">Top exposed groups</p>
              <p className="mt-2 text-sm font-medium">Semiconductors, Cloud, Utilities</p>
            </div>
          </div>
        </section>

        <section className="border-t border-border py-16 md:py-20">
          <div className="grid gap-4 md:grid-cols-3">
            {benefitCards.map((card) => (
              <article key={card.title} className="rounded-xl border border-border bg-card p-6 shadow-sm">
                <IconTile icon={card.icon} />
                <h2 className="mt-4 text-lg font-semibold tracking-tight">{card.title}</h2>
                <p className="mt-2 text-sm leading-6 text-muted-foreground">{card.description}</p>
              </article>
            ))}
          </div>
        </section>

        <section id="how-it-works" className="border-t border-border py-16 md:py-20">
          <h2 className="text-2xl font-semibold tracking-tight sm:text-3xl">How it works</h2>
          <div className="mt-8 grid gap-4 md:grid-cols-3">
            {howItWorksSteps.map((step, index) => (
              <div key={step} className="rounded-xl border border-border bg-card p-6">
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Step {index + 1}</p>
                <p className="mt-3 text-base font-medium leading-7">{step}</p>
              </div>
            ))}
          </div>
        </section>

        <section className="border-t border-border py-16 md:py-20">
          <h2 className="text-2xl font-semibold tracking-tight sm:text-3xl">Why it is useful</h2>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-muted-foreground">
            Keep research practical: follow narratives, understand exposure, and screen opportunities from one simple workflow.
          </p>
          <div className="mt-8 grid gap-4 md:grid-cols-3">
            {productValueItems.map((item) => (
              <article key={item.title} className="rounded-xl border border-border bg-card p-6">
                <IconTile icon={item.icon} />
                <h3 className="mt-4 text-base font-semibold">{item.title}</h3>
                <p className="mt-2 text-sm leading-6 text-muted-foreground">{item.description}</p>
              </article>
            ))}
          </div>
        </section>

        <section className="border-t border-border py-16 md:py-20">
          <h2 className="text-2xl font-semibold tracking-tight sm:text-3xl">Quick clarity</h2>
          <div className="mt-8 grid gap-4 md:grid-cols-3">
            {trustItems.map((item) => (
              <article key={item.title} className="rounded-xl border border-border bg-card p-6">
                <h3 className="text-base font-semibold">{item.title}</h3>
                <p className="mt-2 text-sm leading-6 text-muted-foreground">{item.description}</p>
              </article>
            ))}
          </div>
        </section>

        <section id="final-cta" className="border-t border-border py-16 md:py-20">
          <div className="rounded-2xl border border-border bg-card p-7 sm:p-10">
            <h2 className="text-2xl font-semibold tracking-tight sm:text-3xl">
              Turn daily news into clearer market opportunities.
            </h2>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-muted-foreground">
              Join the early access list to get updates and first access to News Impact Screener.
            </p>
            <form className="mt-7 flex flex-col gap-3 sm:flex-row">
              <label htmlFor="email" className="sr-only">
                Email address
              </label>
              <input
                id="email"
                type="email"
                required
                placeholder="Enter your email"
                className="h-11 w-full rounded-md border border-border bg-background px-3 text-sm outline-none ring-0 transition focus-visible:border-foreground"
              />
              <button
                type="submit"
                className="inline-flex h-11 items-center justify-center rounded-md bg-foreground px-5 text-sm font-semibold text-background transition-opacity hover:opacity-90"
              >
                Get Early Access
              </button>
            </form>
          </div>
        </section>
      </div>
    </main>
  );
}
