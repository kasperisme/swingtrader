import Link from "next/link";
import { Suspense } from "react";
import { ArrowRight, BarChart3, Compass, Filter, Newspaper, Target, Workflow } from "lucide-react";

import { createClient } from "@/lib/supabase/server";

type CardItem = {
  title: string;
  description: string;
  icon: React.ComponentType<{ className?: string }>;
};

const benefitCards: CardItem[] = [
  {
    title: "Spend time on news that actually moves your watchlist",
    description:
      "Cut through endless headlines. See which stories and themes are gaining traction so you know what to read first—without a terminal or a research team.",
    icon: Newspaper,
  },
  {
    title: "Link headlines to stocks and sectors you care about",
    description:
      "Turn “what’s everyone talking about?” into “what might affect the names in my brokerage or IRA?”—before the connection is obvious everywhere else.",
    icon: Target,
  },
  {
    title: "A simpler way to do your own homework",
    description:
      "Whether you check in daily or on weekends, get a steadier rhythm: less noise, clearer next steps, and fewer rabbit holes.",
    icon: Workflow,
  },
];

const howItWorksSteps = [
  "Follow the news themes that are heating up",
  "See which sectors and stocks are most tied to those themes",
  "Narrow down ideas that match how you invest",
];

const productValueItems: CardItem[] = [
  {
    title: "Themes, not just tickers",
    description:
      "Watch how narratives build over time so you’re not reacting to every single headline in isolation.",
    icon: BarChart3,
  },
  {
    title: "Exposure, in plain terms",
    description:
      "Get a clearer picture of which companies and industries sit closest to a story—helpful context for any self-directed investor.",
    icon: Compass,
  },
  {
    title: "Screen the way you think",
    description:
      "Focus on the factors that matter to you—growth, value, risk, sectors—and keep your process consistent without spreadsheets you maintain by hand.",
    icon: Filter,
  },
];

const trustItems = [
  {
    title: "Who it is for",
    description:
      "Retail and self-directed investors who manage their own accounts—taxable brokerage, IRA, or both—and want news tied to opportunities, not noise.",
  },
  {
    title: "How it is different",
    description:
      "Most screeners start with static filters. News Impact Screener starts with what’s happening in the world and shows what it might push on in the market.",
  },
  {
    title: "Why it helps",
    description:
      "Less doom-scrolling, fewer “what did I miss?” moments, and a shorter path from a headline to a watchlist you actually understand.",
  },
];

function IconTile({ icon: Icon }: { icon: React.ComponentType<{ className?: string }> }) {
  return (
    <div className="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-border bg-background">
      <Icon className="h-5 w-5 text-foreground" />
    </div>
  );
}

type LandingArticle = {
  id: number;
  title: string | null;
  url: string | null;
  image_url: string | null;
};

function LandingSnapshotFallback() {
  return (
    <div className="mt-5 space-y-3 animate-pulse">
      {[0, 1, 2, 3].map((i) => (
        <div key={i} className="flex gap-3 rounded-lg border border-border bg-background p-3">
          <div className="h-14 w-20 shrink-0 rounded-md bg-muted" />
          <div className="flex-1 space-y-2 py-1">
            <div className="h-3 w-4/5 rounded bg-muted" />
            <div className="h-3 w-3/5 rounded bg-muted" />
          </div>
        </div>
      ))}
    </div>
  );
}

async function LandingArticlesHeaderAndList() {
  let landingArticles: LandingArticle[] = [];
  try {
    const supabase = await createClient();
    const { data } = await supabase
      .schema("swingtrader")
      .from("news_articles")
      .select("id, title, url, image_url")
      .order("created_at", { ascending: false })
      .limit(4);
    landingArticles = (data ?? []) as LandingArticle[];
  } catch {
    landingArticles = [];
  }

  return (
    <>
      <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {landingArticles.length > 0 ? "Latest scanned articles" : "Live narrative snapshot"}
      </p>
      {landingArticles.length > 0 ? (
        <div className="mt-5 grid gap-3 sm:grid-cols-2">
          {landingArticles.map((article) => (
            <div key={article.id} className="rounded-lg border border-border bg-background p-3">
              <div className="relative h-36 w-full overflow-hidden rounded-md bg-muted">
                {article.image_url ? (
                  <img
                    src={article.image_url}
                    alt=""
                    className="h-full w-full object-cover"
                    loading="lazy"
                  />
                ) : (
                  <div className="flex h-full w-full items-center justify-center text-[9px] text-muted-foreground">
                    —
                  </div>
                )}
              </div>
              <div className="mt-3 min-w-0">
                <Link
                  href={`/articles/${article.id}`}
                  className="line-clamp-2 text-sm font-medium leading-snug hover:underline"
                >
                  {article.title || article.url || "Untitled article"}
                </Link>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="mt-5 space-y-3">
          {["AI infrastructure demand", "Rate-cut expectations", "Energy supply pressure"].map((item, index) => (
            <div
              key={item}
              className="flex items-center justify-between rounded-lg border border-border bg-background px-4 py-3"
            >
              <p className="text-sm font-medium">{item}</p>
              <span className="rounded-full bg-muted px-2.5 py-1 text-xs font-medium text-muted-foreground">
                #{index + 1}
              </span>
            </div>
          ))}
        </div>
      )}
    </>
  );
}

export default function Home() {
  return (
    <main className="min-h-screen bg-background text-foreground">
      <div className="mx-auto max-w-6xl px-6 lg:px-8">
        <header className="flex items-center justify-between border-b border-border py-5">
          <p className="text-sm font-semibold tracking-tight">newsimpactscreener.com</p>
          <nav className="flex items-center gap-4">
            <Link href="/docs" className="text-sm font-medium text-muted-foreground transition-colors hover:text-foreground">
              Docs
            </Link>
            <Link href="/blog" className="text-sm font-medium text-muted-foreground transition-colors hover:text-foreground">
              Blog
            </Link>
            <Link
              href="/auth/login"
              className="rounded-md border border-border px-4 py-2 text-sm font-medium text-foreground transition-colors hover:bg-muted"
            >
              Sign in
            </Link>
          </nav>
        </header>

        <section className="grid gap-12 py-16 md:grid-cols-2 md:items-center md:py-24">
          <div>
            <p className="text-sm font-medium text-muted-foreground">
              For retail and self-directed investors
            </p>
            <h1 className="mt-4 text-4xl font-semibold tracking-tight sm:text-5xl">
              News that matters—connected to stocks and sectors.
            </h1>
            <p className="mt-5 max-w-xl text-base leading-7 text-muted-foreground sm:text-lg">
              News Impact Screener helps individual investors turn headlines into clearer ideas: what
              themes are rising, what may be exposed, and what to research next in the accounts you
              manage yourself.
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

          <div className="rounded-2xl bg-card p-6 shadow-sm">
            <Suspense
              fallback={
                <>
                  <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    Latest scanned articles
                  </p>
                  <LandingSnapshotFallback />
                </>
              }
            >
              <LandingArticlesHeaderAndList />
            </Suspense>
            <div className="mt-5 rounded-lg border border-border bg-background p-4">
              <p className="text-xs text-muted-foreground">Example themes you might track</p>
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
          <h2 className="text-2xl font-semibold tracking-tight sm:text-3xl">Built for how retail investors research</h2>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-muted-foreground">
            You don’t need a desk full of monitors. Follow themes, see exposure, and narrow ideas in
            one place—whether you invest for the long haul or trade a smaller sleeve of your
            portfolio.
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
          <h2 className="text-2xl font-semibold tracking-tight sm:text-3xl">Straight answers</h2>
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
              Smarter homework for your portfolio—starting with the news.
            </h2>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-muted-foreground">
              Join the list for product updates and early access. Built for people who invest their
              own money and want context, not chaos.
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
