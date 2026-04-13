import Link from "next/link";
import { Suspense } from "react";
import { unstable_noStore as noStore } from "next/cache";
import { createClient as createSupabaseClient } from "@supabase/supabase-js";
import {
  ArrowRight,
  BarChart3,
  Compass,
  Filter,
  Newspaper,
  Target,
  Workflow,
  TrendingUp,
  Zap,
  Shield,
} from "lucide-react";

import { createClient } from "@/lib/supabase/server";
import {
  ArticlesGrid,
  ArticlesGridFallback,
  type ArticleGridItem,
} from "@/components/articles-grid";
import { EarlyAccessSignupForm } from "@/components/early-access-signup-form";

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
      `Turn \u201cwhat\u2019s everyone talking about?\u201d into \u201cwhat might affect the names in my brokerage or IRA?\u201d\u2014before the connection is obvious everywhere else.`,
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
  {
    label: "Follow the themes heating up",
    detail:
      "Track narratives as they build—AI infrastructure, rate expectations, energy policy—before they become headlines everywhere.",
  },
  {
    label: "See which stocks and sectors are most exposed",
    detail:
      "Get a clear picture of which companies sit closest to a story so you know where to look, not just what happened.",
  },
  {
    label: "Narrow ideas that match how you invest",
    detail:
      "Filter by the factors you care about—growth, value, sector, risk—and keep your process consistent without manual spreadsheets.",
  },
];

const productValueItems: CardItem[] = [
  {
    title: "Themes, not just tickers",
    description:
      "Watch how narratives build over time so you're not reacting to every single headline in isolation.",
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
    title: "Who it's for",
    icon: Shield,
    description:
      "Retail and self-directed investors who manage their own accounts—taxable brokerage, IRA, or both—and want news tied to opportunities, not noise.",
  },
  {
    title: "How it's different",
    icon: TrendingUp,
    description:
      "Most screeners start with static filters. News Impact Screener starts with what's happening in the world and shows what it might push on in the market.",
  },
  {
    title: "Why it helps",
    icon: Zap,
    description:
      `Less doom-scrolling, fewer \u201cwhat did I miss?\u201d moments, and a shorter path from a headline to a watchlist you actually understand.`,
  },
];

const tickerThemes = [
  "AI chip demand surge",
  "Rate cut expectations",
  "Energy supply pressure",
  "China EV competition",
  "Cloud hyperscaler capex",
  "Reshoring manufacturing",
  "Defense spending outlook",
  "Consumer credit stress",
  "Biotech regulatory cycle",
  "Dollar strength impact",
];

async function LandingArticlesHeaderAndList() {
  noStore();
  let landingArticles: ArticleGridItem[] = [];
  try {
    const secretKey = process.env.SUPABASE_SECRET_KEY;
    const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
    const supabase =
      secretKey && supabaseUrl
        ? createSupabaseClient(supabaseUrl, secretKey, {
            auth: { persistSession: false, autoRefreshToken: false },
          })
        : await createClient();
    const { data } = await supabase
      .schema("swingtrader")
      .from("news_articles")
      .select("id, slug, title, url, image_url, published_at, created_at")
      .order("published_at", { ascending: false, nullsFirst: false })
      .order("created_at", { ascending: false })
      .limit(4);
    landingArticles = (data ?? []) as ArticleGridItem[];
  } catch {
    landingArticles = [];
  }

  return (
    <>
      <p className="text-xs font-semibold uppercase tracking-widest text-amber-500/80">
        {landingArticles.length > 0 ? "Latest articles" : "Live narrative snapshot"}
      </p>
      <div className="mt-4">
        {landingArticles.length > 0 ? (
          <ArticlesGrid articles={landingArticles} />
        ) : (
          <div className="space-y-2">
            {["AI infrastructure demand", "Rate-cut expectations", "Energy supply pressure"].map(
              (item, index) => (
                <div
                  key={item}
                  className="flex items-center justify-between rounded-lg border border-border bg-background/50 px-4 py-3"
                >
                  <p className="text-sm font-medium">{item}</p>
                  <span className="rounded-full border border-amber-500/20 bg-amber-500/10 px-2.5 py-0.5 text-xs font-semibold text-amber-400">
                    #{index + 1}
                  </span>
                </div>
              ),
            )}
          </div>
        )}
      </div>
    </>
  );
}

export default function Home() {
  const doubledTicker = [...tickerThemes, ...tickerThemes];

  return (
    <main className="min-h-screen bg-background text-foreground">
      {/* ── HERO ─────────────────────────────────────────────────── */}
      <section className="relative overflow-hidden pt-12 pb-0 md:pt-20">
        {/* Subtle grid background */}
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 bg-[linear-gradient(to_right,hsl(var(--border))_1px,transparent_1px),linear-gradient(to_bottom,hsl(var(--border))_1px,transparent_1px)] bg-[size:72px_72px] opacity-40"
        />
        {/* Radial amber glow top-center */}
        <div
          aria-hidden
          className="pointer-events-none absolute -top-32 left-1/2 h-[480px] w-[720px] -translate-x-1/2 rounded-full bg-amber-500/10 blur-3xl"
        />

        <div className="relative mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
          <div className="grid gap-12 lg:grid-cols-2 lg:items-center">
            {/* Left: copy */}
            <div>
              <div className="inline-flex items-center gap-2 rounded-full border border-amber-500/25 bg-amber-500/10 px-3 py-1.5 text-xs font-semibold text-amber-400">
                <span className="h-1.5 w-1.5 rounded-full bg-amber-400" />
                For retail &amp; self-directed investors
              </div>

              <h1 className="mt-6 text-4xl font-bold tracking-tight sm:text-5xl lg:text-[3.25rem] lg:leading-[1.1]">
                The news moves stocks.{" "}
                <span className="text-amber-400">Know which ones.</span>
              </h1>

              <p className="mt-5 max-w-lg text-base leading-7 text-muted-foreground sm:text-lg">
                News Impact Screener connects headlines to stocks and sectors—so you see what
                themes are rising, what might be exposed, and where to focus next. No terminal
                required.
              </p>

              <div className="mt-8 flex flex-wrap gap-3">
                <Link
                  href="#final-cta"
                  className="inline-flex cursor-pointer items-center gap-2 rounded-xl bg-violet-600 px-6 py-3 text-sm font-semibold text-white shadow-lg shadow-violet-500/20 transition-all hover:bg-violet-500 hover:shadow-violet-500/30"
                >
                  Get Early Access
                  <ArrowRight className="h-4 w-4" />
                </Link>
                <Link
                  href="#how-it-works"
                  className="inline-flex cursor-pointer items-center rounded-xl border border-border px-6 py-3 text-sm font-semibold text-foreground transition-colors hover:bg-muted"
                >
                  See How It Works
                </Link>
              </div>
            </div>

            {/* Right: live articles card */}
            <div className="rounded-2xl border border-border bg-card p-6 shadow-xl">
              <Suspense
                fallback={
                  <>
                    <p className="text-xs font-semibold uppercase tracking-widest text-amber-500/80">
                      Latest scanned articles
                    </p>
                    <div className="mt-4">
                      <ArticlesGridFallback />
                    </div>
                  </>
                }
              >
                <LandingArticlesHeaderAndList />
              </Suspense>
              <div className="mt-4 rounded-xl border border-border bg-background/60 p-3">
                <p className="text-xs text-muted-foreground">Example themes being tracked</p>
                <div className="mt-2 flex flex-wrap gap-2">
                  {["Semiconductors", "Cloud Capex", "Defense", "Utilities"].map((tag) => (
                    <span
                      key={tag}
                      className="rounded-full border border-amber-500/20 bg-amber-500/10 px-2.5 py-0.5 text-xs font-semibold text-amber-400"
                    >
                      {tag}
                    </span>
                  ))}
                </div>
              </div>
            </div>
          </div>

          {/* News ticker — visible above the fold */}
          <div className="relative mt-10 overflow-hidden rounded-xl border border-border bg-card py-3">
            <div className="pointer-events-none absolute inset-y-0 left-0 w-12 bg-gradient-to-r from-card to-transparent z-10" />
            <div className="pointer-events-none absolute inset-y-0 right-0 w-12 bg-gradient-to-l from-card to-transparent z-10" />
            <div className="flex animate-news-roll gap-0 whitespace-nowrap">
              {doubledTicker.map((item, i) => (
                <span
                  key={`${item}-${i}`}
                  className="inline-flex items-center gap-3 px-6 text-xs font-medium text-muted-foreground"
                >
                  <span className="h-1 w-1 rounded-full bg-amber-500/60" />
                  {item}
                </span>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* ── BENTO FEATURES ───────────────────────────────────────── */}
      <section className="border-t border-border py-16 md:py-24">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
          <p className="text-xs font-semibold uppercase tracking-widest text-amber-500">
            Why it works
          </p>
          <h2 className="mt-3 text-2xl font-bold tracking-tight sm:text-3xl">
            Built for how retail investors actually research
          </h2>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-muted-foreground">
            You don't need a desk full of monitors. Follow themes, see exposure, and narrow ideas
            in one place.
          </p>

          {/* Bento grid */}
          <div className="mt-10 grid gap-4 md:grid-cols-3">
            {/* Card 1 — wide */}
            {(() => {
              const Icon0 = benefitCards[0].icon;
              return (
                <article className="group relative cursor-default overflow-hidden rounded-2xl border border-border bg-card p-6 transition-all duration-200 hover:border-amber-500/30 hover:shadow-lg hover:shadow-amber-500/5 md:col-span-2">
                  <div className="inline-flex h-10 w-10 items-center justify-center rounded-xl border border-border bg-background">
                    <Icon0 className="h-5 w-5 text-amber-400" />
                  </div>
                  <h3 className="mt-4 text-lg font-semibold tracking-tight">{benefitCards[0].title}</h3>
                  <p className="mt-2 text-sm leading-6 text-muted-foreground">
                    {benefitCards[0].description}
                  </p>
                  <div
                    aria-hidden
                    className="pointer-events-none absolute -bottom-8 -right-8 h-32 w-32 rounded-full bg-amber-500/5 blur-2xl opacity-0 transition-opacity duration-300 group-hover:opacity-100"
                  />
                </article>
              );
            })()}

            {/* Card 2 */}
            {(() => {
              const Icon1 = benefitCards[1].icon;
              return (
                <article className="group relative cursor-default overflow-hidden rounded-2xl border border-border bg-card p-6 transition-all duration-200 hover:border-amber-500/30 hover:shadow-lg hover:shadow-amber-500/5">
                  <div className="inline-flex h-10 w-10 items-center justify-center rounded-xl border border-border bg-background">
                    <Icon1 className="h-5 w-5 text-amber-400" />
                  </div>
                  <h3 className="mt-4 text-base font-semibold tracking-tight">
                    {benefitCards[1].title}
                  </h3>
                  <p className="mt-2 text-sm leading-6 text-muted-foreground">
                    {benefitCards[1].description}
                  </p>
                  <div
                    aria-hidden
                    className="pointer-events-none absolute -bottom-8 -right-8 h-32 w-32 rounded-full bg-amber-500/5 blur-2xl opacity-0 transition-opacity duration-300 group-hover:opacity-100"
                  />
                </article>
              );
            })()}

            {/* Card 3 — full width, horizontal layout */}
            {(() => {
              const Icon2 = benefitCards[2].icon;
              return (
                <article className="group relative cursor-default overflow-hidden rounded-2xl border border-border bg-card p-6 transition-all duration-200 hover:border-amber-500/30 hover:shadow-lg hover:shadow-amber-500/5 md:col-span-3 md:flex md:items-center md:gap-8">
                  <div className="shrink-0">
                    <div className="inline-flex h-10 w-10 items-center justify-center rounded-xl border border-border bg-background">
                      <Icon2 className="h-5 w-5 text-amber-400" />
                    </div>
                  </div>
                  <div className="mt-4 md:mt-0">
                    <h3 className="text-base font-semibold tracking-tight">{benefitCards[2].title}</h3>
                    <p className="mt-1 text-sm leading-6 text-muted-foreground">
                      {benefitCards[2].description}
                    </p>
                  </div>
                  <div
                    aria-hidden
                    className="pointer-events-none absolute -bottom-8 right-8 h-32 w-32 rounded-full bg-amber-500/5 blur-2xl opacity-0 transition-opacity duration-300 group-hover:opacity-100"
                  />
                </article>
              );
            })()}
          </div>
        </div>
      </section>

      {/* ── HOW IT WORKS ─────────────────────────────────────────── */}
      <section id="how-it-works" className="border-t border-border py-16 md:py-24">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
          <p className="text-xs font-semibold uppercase tracking-widest text-amber-500">
            How it works
          </p>
          <h2 className="mt-3 text-2xl font-bold tracking-tight sm:text-3xl">Three steps, no terminal</h2>

          <div className="relative mt-10">
            {/* Connecting line */}
            <div
              aria-hidden
              className="absolute top-5 left-0 right-0 hidden h-px bg-gradient-to-r from-transparent via-amber-500/30 to-transparent md:block"
            />
            <div className="relative grid gap-8 md:grid-cols-3">
              {howItWorksSteps.map((step, index) => (
                <div key={step.label} className="flex flex-col">
                  <div className="relative z-10 flex h-10 w-10 items-center justify-center rounded-full border border-amber-500/30 bg-amber-500/10 text-sm font-bold text-amber-400">
                    {index + 1}
                  </div>
                  <h3 className="mt-5 text-base font-semibold">{step.label}</h3>
                  <p className="mt-2 text-sm leading-6 text-muted-foreground">{step.detail}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* ── PRODUCT VALUES ───────────────────────────────────────── */}
      <section className="border-t border-border py-16 md:py-24">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
          <p className="text-xs font-semibold uppercase tracking-widest text-amber-500">
            What you get
          </p>
          <h2 className="mt-3 text-2xl font-bold tracking-tight sm:text-3xl">
            Signal, not noise
          </h2>
          <div className="mt-10 grid gap-4 sm:grid-cols-2 md:grid-cols-3">
            {productValueItems.map((item) => (
              <article
                key={item.title}
                className="group cursor-default rounded-2xl border border-border bg-card p-6 transition-all duration-200 hover:border-amber-500/30 hover:shadow-lg hover:shadow-amber-500/5"
              >
                <div className="inline-flex h-10 w-10 items-center justify-center rounded-xl border border-border bg-background">
                  <item.icon className="h-5 w-5 text-amber-400" />
                </div>
                <h3 className="mt-4 text-base font-semibold">{item.title}</h3>
                <p className="mt-2 text-sm leading-6 text-muted-foreground">{item.description}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      {/* ── STRAIGHT ANSWERS ─────────────────────────────────────── */}
      <section className="border-t border-border py-16 md:py-24">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
          <p className="text-xs font-semibold uppercase tracking-widest text-amber-500">
            Straight answers
          </p>
          <h2 className="mt-3 text-2xl font-bold tracking-tight sm:text-3xl">
            Common questions
          </h2>
          <div className="mt-10 grid gap-4 sm:grid-cols-2 md:grid-cols-3">
            {trustItems.map((item) => (
              <article
                key={item.title}
                className="rounded-2xl border border-border bg-card p-6"
              >
                <div className="inline-flex h-10 w-10 items-center justify-center rounded-xl border border-border bg-background">
                  <item.icon className="h-5 w-5 text-amber-400" />
                </div>
                <h3 className="mt-4 text-base font-semibold">{item.title}</h3>
                <p className="mt-2 text-sm leading-6 text-muted-foreground">{item.description}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      {/* ── FINAL CTA ────────────────────────────────────────────── */}
      <section id="final-cta" className="relative border-t border-border py-20 md:py-28">
        {/* Ambient glows */}
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 overflow-hidden"
        >
          <div className="absolute bottom-0 left-1/4 h-72 w-72 rounded-full bg-amber-500/8 blur-3xl" />
          <div className="absolute bottom-0 right-1/4 h-72 w-72 rounded-full bg-violet-500/8 blur-3xl" />
        </div>

        <div className="relative mx-auto max-w-2xl px-4 text-center">
          <p className="text-xs font-semibold uppercase tracking-widest text-amber-500">
            Early access
          </p>
          <h2 className="mt-3 text-3xl font-bold tracking-tight sm:text-4xl">
            Smarter homework for your portfolio.
          </h2>
          <p className="mt-4 text-base leading-7 text-muted-foreground">
            Join the list for product updates and early access. Built for people who invest their
            own money and want context, not chaos.
          </p>

          <EarlyAccessSignupForm />
          <p className="mt-4 text-xs text-muted-foreground">
            No credit card. No terminal subscription.
          </p>
        </div>
      </section>
    </main>
  );
}
