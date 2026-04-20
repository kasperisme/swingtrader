import Link from "next/link";
import Image from "next/image";
import { Suspense } from "react";
import { unstable_noStore as noStore } from "next/cache";
import { createServiceClient } from "@/lib/supabase/service";
import {
  ArrowRight,
  BarChart3,
  Check,
  Compass,
  Filter,
  Newspaper,
  Target,
  Workflow,
  TrendingUp,
  Zap,
  Shield,
  type LucideProps,
} from "lucide-react";

import { createClient } from "@/lib/supabase/server";
import {
  ArticlesGrid,
  ArticlesGridFallback,
  type ArticleGridItem,
} from "@/components/articles-grid";
import { EarlyAccessSignupForm } from "@/components/early-access-signup-form";
import { PricingTierSwitcher } from "@/components/pricing-tier-switcher";
import { isSanityConfigured, sanityFetch } from "@/lib/sanity/client";
import { newsPublishersQuery, landingPageQuery } from "@/lib/sanity/queries";
import type { NewsPublisher, LandingPage, LandingCardItem, LandingStep, LandingPricingPlan } from "@/lib/sanity/types";

// ── Icon mapping ──────────────────────────────────────────────────────────────

type IconComponent = React.ComponentType<LucideProps & { className?: string }>;

const ICON_MAP: Record<string, IconComponent> = {
  Newspaper,
  Target,
  Workflow,
  BarChart3,
  Compass,
  Filter,
  Shield,
  TrendingUp,
  Zap,
};

function resolveIcon(name: string | null | undefined, fallback: IconComponent): IconComponent {
  return (name && ICON_MAP[name]) ? ICON_MAP[name] : fallback;
}

// ── Hardcoded fallbacks ───────────────────────────────────────────────────────

const DEFAULT_BENEFIT_CARDS: LandingCardItem[] = [
  {
    title: "Spend time on news that actually moves your watchlist",
    description:
      "Cut through endless headlines. See which stories and themes are gaining traction so you know what to read first—without a terminal or a research team.",
    iconName: "Newspaper",
  },
  {
    title: "Link headlines to stocks and sectors you care about",
    description:
      `Turn \u201cwhat\u2019s everyone talking about?\u201d into \u201cwhat might affect the names in my brokerage or IRA?\u201d\u2014before the connection is obvious everywhere else.`,
    iconName: "Target",
  },
  {
    title: "A simpler way to do your own homework",
    description:
      "Whether you check in daily or on weekends, get a steadier rhythm: less noise, clearer next steps, and fewer rabbit holes.",
    iconName: "Workflow",
  },
];

const DEFAULT_HOW_IT_WORKS_STEPS: LandingStep[] = [
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

const DEFAULT_PRODUCT_VALUE_ITEMS: LandingCardItem[] = [
  {
    title: "Themes, not just tickers",
    description:
      "Watch how narratives build over time so you're not reacting to every single headline in isolation.",
    iconName: "BarChart3",
  },
  {
    title: "Exposure, in plain terms",
    description:
      "Get a clearer picture of which companies and industries sit closest to a story—helpful context for any self-directed investor.",
    iconName: "Compass",
  },
  {
    title: "Screen the way you think",
    description:
      "Focus on the factors that matter to you—growth, value, risk, sectors—and keep your process consistent without spreadsheets you maintain by hand.",
    iconName: "Filter",
  },
];

const DEFAULT_TRUST_ITEMS: LandingCardItem[] = [
  {
    title: "Who it's for",
    iconName: "Shield",
    description:
      "Retail and self-directed investors who manage their own accounts—taxable brokerage, IRA, or both—and want news tied to opportunities, not noise.",
  },
  {
    title: "How it's different",
    iconName: "TrendingUp",
    description:
      "Most screeners start with static filters. News Impact Screener starts with what's happening in the world and shows what it might push on in the market.",
  },
  {
    title: "Why it helps",
    iconName: "Zap",
    description:
      `Less doom-scrolling, fewer \u201cwhat did I miss?\u201d moments, and a shorter path from a headline to a watchlist you actually understand.`,
  },
];

const DEFAULT_TICKER_THEMES = [
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

const DEFAULT_PRICING_PLANS: LandingPricingPlan[] = [
  {
    name: "Observer",
    price: "$0",
    billingNote: "forever free",
    annualLabel: null,
    phase2Price: null,
    phase2AnnualLabel: null,
    phase3Price: null,
    phase3AnnualLabel: null,
    description: "Get a feel for the screener. No card, no commitment.",
    features: ["Daily top 5 news-impacted stocks", "Basic impact score", "1-day delay on results"],
    ctaLabel: "Start for free",
    badge: null,
    isHighlighted: false,
    spotLimit: null,
    isCurrentPhase: false,
  },
  {
    name: "Investor",
    price: "$9",
    billingNote: "/ month",
    annualLabel: "$99/yr · lock in forever",
    phase2Price: "$29",
    phase2AnnualLabel: "$299/yr",
    phase3Price: "$39",
    phase3AnnualLabel: "$399/yr",
    description: "Real-time screening, locked at this price for life.",
    features: ["Real-time news impact screener", "Full impact score breakdown", "Sector & theme filters", "Watchlist alerts", "7-day history"],
    ctaLabel: "Lock in $9/mo",
    badge: "Early Access",
    isHighlighted: true,
    spotLimit: 100,
    isCurrentPhase: true,
  },
  {
    name: "Trader",
    price: "$19",
    billingNote: "/ month",
    annualLabel: "$199/yr · lock in forever",
    phase2Price: "$49",
    phase2AnnualLabel: "$499/yr",
    phase3Price: "$69",
    phase3AnnualLabel: "$699/yr",
    description: "Everything in Investor, plus advanced tools. Locked forever.",
    features: ["Everything in Investor", "Extended 30-day history", "AI stock summaries", "Portfolio impact view", "Priority support"],
    ctaLabel: "Lock in $19/mo",
    badge: "Early Access",
    isHighlighted: false,
    spotLimit: 100,
    isCurrentPhase: true,
  },
];

// ── Sub-components ────────────────────────────────────────────────────────────

async function PublishersMarquee() {
  let publishers: NewsPublisher[] = [];
  if (isSanityConfigured) {
    try {
      publishers = await sanityFetch<NewsPublisher[]>(newsPublishersQuery);
    } catch {
      publishers = [];
    }
  }

  if (publishers.length === 0) return null;

  const doubled = [...publishers, ...publishers];

  return (
    <section className="py-12 md:py-16">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
        <p className="text-center text-xs font-semibold uppercase tracking-widest text-muted-foreground">
          Scanning news from
        </p>
      </div>
      <div className="relative mt-8 overflow-hidden">
        <div className="pointer-events-none absolute inset-y-0 left-0 w-16 bg-gradient-to-r from-background to-transparent z-10" />
        <div className="pointer-events-none absolute inset-y-0 right-0 w-16 bg-gradient-to-l from-background to-transparent z-10" />
        <div className="flex animate-news-roll gap-0 whitespace-nowrap">
          {doubled.map((p, i) => (
            <span
              key={`${p._id}-${i}`}
              className="inline-flex items-center gap-2 px-5"
            >
              {p.iconUrl ? (
                <Image
                  src={p.iconUrl}
                  alt={p.name}
                  width={20}
                  height={20}
                  className="h-5 w-5 rounded-sm object-contain opacity-60"
                  unoptimized
                />
              ) : (
                <span className="h-1 w-1 rounded-full bg-muted-foreground/40" />
              )}
              <span className="text-xs font-medium text-muted-foreground">
                {p.name}
              </span>
            </span>
          ))}
        </div>
      </div>
    </section>
  );
}

async function LandingArticlesHeaderAndList() {
  noStore();
  let landingArticles: ArticleGridItem[] = [];
  try {
    let supabase;
    try {
      supabase = createServiceClient();
    } catch {
      supabase = await createClient();
    }
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
                  className="flex items-center justify-between px-1 py-2.5"
                >
                  <p className="text-sm font-medium">{item}</p>
                  <span className="text-xs font-semibold text-amber-500/85">
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

async function getSignupCount(): Promise<number> {
  try {
    const supabase = createServiceClient();
    const { count, error } = await supabase
      .schema("swingtrader")
      .from("early_access_signups")
      .select("id", { count: "exact", head: true });
    if (error) throw error;
    return count ?? 0;
  } catch {
    return 0;
  }
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default async function Home() {
  noStore(); // pricing section shows live signup count — never serve stale
  let cms: LandingPage | null = null;
  if (isSanityConfigured) {
    try {
      cms = await sanityFetch<LandingPage>(landingPageQuery);
    } catch {
      cms = null;
    }
  }

  const heroBadgeText = cms?.heroBadgeText ?? "For retail & self-directed investors";
  const heroHeadlinePart1 = cms?.heroHeadlinePart1 ?? "The news moves stocks.";
  const heroHeadlineHighlight = cms?.heroHeadlineHighlight ?? "Know which ones.";
  const heroDescription =
    cms?.heroDescription ??
    "News Impact Screener connects headlines to stocks and sectors—so you see what themes are rising, what might be exposed, and where to focus next. No terminal required.";
  const heroPrimaryCtaLabel = cms?.heroPrimaryCtaLabel ?? "Get Early Access";
  const heroSecondaryCtaLabel = cms?.heroSecondaryCtaLabel ?? "See How It Works";

  const benefitsSectionLabel = cms?.benefitsSectionLabel ?? "Why it works";
  const benefitsHeading = cms?.benefitsHeading ?? "Built for how retail investors actually research";
  const benefitsSubheading =
    cms?.benefitsSubheading ??
    "You don't need a desk full of monitors. Follow themes, see exposure, and narrow ideas in one place.";
  const benefitCards = cms?.benefitCards?.length ? cms.benefitCards : DEFAULT_BENEFIT_CARDS;

  const howItWorksSectionLabel = cms?.howItWorksSectionLabel ?? "How it works";
  const howItWorksHeading = cms?.howItWorksHeading ?? "Three steps, no terminal";
  const howItWorksSteps = cms?.howItWorksSteps?.length ? cms.howItWorksSteps : DEFAULT_HOW_IT_WORKS_STEPS;

  const productValuesSectionLabel = cms?.productValuesSectionLabel ?? "What you get";
  const productValuesHeading = cms?.productValuesHeading ?? "Signal, not noise";
  const productValueItems = cms?.productValueItems?.length ? cms.productValueItems : DEFAULT_PRODUCT_VALUE_ITEMS;

  const trustSectionLabel = cms?.trustSectionLabel ?? "Straight answers";
  const trustHeading = cms?.trustHeading ?? "Common questions";
  const trustItems = cms?.trustItems?.length ? cms.trustItems : DEFAULT_TRUST_ITEMS;

  const ctaSectionLabel = cms?.ctaSectionLabel ?? "Early access";
  const ctaHeading = cms?.ctaHeading ?? "Smarter homework for your portfolio.";
  const ctaDescription =
    cms?.ctaDescription ??
    "Join the list for product updates and early access. Built for people who invest their own money and want context, not chaos.";
  const ctaFootnote = cms?.ctaFootnote ?? "No credit card. No terminal subscription.";

  const pricingSectionLabel = cms?.pricingSectionLabel ?? "Pricing";
  const pricingHeading = cms?.pricingHeading ?? "Lock in the founder rate.";
  const pricingSubheading = cms?.pricingSubheading ?? "Price increases every 100 subscribers. Early subscribers lock in their rate forever.";
  const pricingFounderNote = cms?.pricingFounderNote ?? "Your price is locked for life. Cancel any time — but once you cancel, the founder rate is gone.";
  const pricingPlans = cms?.pricingPlans?.length ? cms.pricingPlans : DEFAULT_PRICING_PLANS;
  const signupCount = await getSignupCount();
  const currentPlans = pricingPlans.filter((p) => p.isCurrentPhase);
  const freePlan = pricingPlans.find((p) => p.price === "$0");
  const futurePlans = pricingPlans.filter((p) => !p.isCurrentPhase && p !== freePlan);
  const finalPhasePlan = futurePlans[futurePlans.length - 1];

  const offerSectionLabel = cms?.offerSectionLabel ?? null;
  const offerHeading = cms?.offerHeading ?? null;
  const offerSubheading = cms?.offerSubheading ?? null;
  const offerBadge = cms?.offerBadge ?? null;
  const offerOriginalPrice = cms?.offerOriginalPrice ?? null;
  const offerDiscountedPrice = cms?.offerDiscountedPrice ?? null;
  const offerSavingsText = cms?.offerSavingsText ?? null;
  const offerDescription = cms?.offerDescription ?? null;
  const offerFeatures = cms?.offerFeatures ?? null;
  const offerCtaLabel = cms?.offerCtaLabel ?? "Claim Early Access";
  const offerUrgencyText = cms?.offerUrgencyText ?? null;
  const offerExpiryText = cms?.offerExpiryText ?? null;
  const showOffer = !!(offerHeading || offerDiscountedPrice);

  const tickerThemes = cms?.tickerThemes?.length ? cms.tickerThemes : DEFAULT_TICKER_THEMES;
  const doubledTicker = [...tickerThemes, ...tickerThemes];

  return (
    <main className="min-h-screen bg-background text-foreground">
      {/* ── HERO ─────────────────────────────────────────────────── */}
      <section className="pt-12 pb-0 md:pt-20">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
          <div className="grid gap-12 lg:grid-cols-2 lg:items-center">
            {/* Left: copy */}
            <div>
              <div className="inline-flex items-center gap-2 rounded-full border border-amber-500/25 bg-amber-500/10 px-3 py-1.5 text-xs font-semibold text-amber-400">
                <span className="h-1.5 w-1.5 rounded-full bg-amber-400" />
                {heroBadgeText}
              </div>

              <h1 className="mt-6 text-4xl font-bold tracking-tight sm:text-5xl lg:text-[3.25rem] lg:leading-[1.1]">
                {heroHeadlinePart1}{" "}
                <span className="text-amber-400">{heroHeadlineHighlight}</span>
              </h1>

              <p className="mt-5 max-w-lg text-base leading-7 text-muted-foreground sm:text-lg">
                {heroDescription}
              </p>

              <div className="mt-8 flex flex-wrap gap-3">
                <Link
                  href="#final-cta"
                  className="inline-flex cursor-pointer items-center gap-2 rounded-xl bg-violet-600 px-6 py-3 text-sm font-semibold text-white shadow-lg shadow-violet-500/20 transition-all hover:bg-violet-500 hover:shadow-violet-500/30"
                >
                  {heroPrimaryCtaLabel}
                  <ArrowRight className="h-4 w-4" />
                </Link>
                <Link
                  href="#how-it-works"
                  className="inline-flex cursor-pointer items-center rounded-xl border border-border px-6 py-3 text-sm font-semibold text-foreground transition-colors hover:bg-muted"
                >
                  {heroSecondaryCtaLabel}
                </Link>
              </div>
            </div>

            {/* Right: latest articles */}
            <div className="p-1">
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
            </div>
          </div>

          {/* News ticker — visible above the fold */}
          <div className="mt-10 overflow-hidden py-2">
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
            {benefitsSectionLabel}
          </p>
          <h2 className="mt-3 text-2xl font-bold tracking-tight sm:text-3xl">
            {benefitsHeading}
          </h2>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-muted-foreground">
            {benefitsSubheading}
          </p>

          {/* Bento grid */}
          <div className="mt-10 grid gap-4 md:grid-cols-3">
            {benefitCards[0] && (() => {
              const Icon = resolveIcon(benefitCards[0].iconName, Newspaper);
              return (
                <article className="cursor-default p-2 md:col-span-2">
                  <div className="inline-flex h-10 w-10 items-center justify-center rounded-xl border border-border bg-background/80">
                    <Icon className="h-5 w-5 text-amber-400" />
                  </div>
                  <h3 className="mt-4 text-lg font-semibold tracking-tight">{benefitCards[0].title}</h3>
                  <p className="mt-2 text-sm leading-6 text-muted-foreground">
                    {benefitCards[0].description}
                  </p>
                </article>
              );
            })()}

            {benefitCards[1] && (() => {
              const Icon = resolveIcon(benefitCards[1].iconName, Target);
              return (
                <article className="cursor-default p-2">
                  <div className="inline-flex h-10 w-10 items-center justify-center rounded-xl border border-border bg-background/80">
                    <Icon className="h-5 w-5 text-amber-400" />
                  </div>
                  <h3 className="mt-4 text-base font-semibold tracking-tight">
                    {benefitCards[1].title}
                  </h3>
                  <p className="mt-2 text-sm leading-6 text-muted-foreground">
                    {benefitCards[1].description}
                  </p>
                </article>
              );
            })()}

            {benefitCards[2] && (() => {
              const Icon = resolveIcon(benefitCards[2].iconName, Workflow);
              return (
                <article className="cursor-default p-2 md:col-span-3 md:flex md:items-center md:gap-8">
                  <div className="shrink-0">
                    <div className="inline-flex h-10 w-10 items-center justify-center rounded-xl border border-border bg-background/80">
                      <Icon className="h-5 w-5 text-amber-400" />
                    </div>
                  </div>
                  <div className="mt-4 md:mt-0">
                    <h3 className="text-base font-semibold tracking-tight">{benefitCards[2].title}</h3>
                    <p className="mt-1 text-sm leading-6 text-muted-foreground">
                      {benefitCards[2].description}
                    </p>
                  </div>
                </article>
              );
            })()}
          </div>
        </div>
      </section>

      {/* ── HOW IT WORKS ─────────────────────────────────────────── */}
      <section id="how-it-works" className="py-16 md:py-24">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
          <p className="text-xs font-semibold uppercase tracking-widest text-amber-500">
            {howItWorksSectionLabel}
          </p>
          <h2 className="mt-3 text-2xl font-bold tracking-tight sm:text-3xl">{howItWorksHeading}</h2>

          <div className="relative mt-10">
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

      {/* ── PUBLISHERS ───────────────────────────────────────────── */}
      <PublishersMarquee />

      {/* ── PRODUCT VALUES ───────────────────────────────────────── */}
      <section className="py-16 md:py-24">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
          <p className="text-xs font-semibold uppercase tracking-widest text-amber-500">
            {productValuesSectionLabel}
          </p>
          <h2 className="mt-3 text-2xl font-bold tracking-tight sm:text-3xl">
            {productValuesHeading}
          </h2>
          <div className="mt-10 grid gap-4 sm:grid-cols-2 md:grid-cols-3">
            {productValueItems.map((item) => {
              const Icon = resolveIcon(item.iconName, BarChart3);
              return (
                <article key={item.title} className="cursor-default p-2">
                  <div className="inline-flex h-10 w-10 items-center justify-center rounded-xl border border-border bg-background/80">
                    <Icon className="h-5 w-5 text-amber-400" />
                  </div>
                  <h3 className="mt-4 text-base font-semibold">{item.title}</h3>
                  <p className="mt-2 text-sm leading-6 text-muted-foreground">{item.description}</p>
                </article>
              );
            })}
          </div>
        </div>
      </section>

      {/* ── STRAIGHT ANSWERS ─────────────────────────────────────── */}
      <section className="py-16 md:py-24">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
          <p className="text-xs font-semibold uppercase tracking-widest text-amber-500">
            {trustSectionLabel}
          </p>
          <h2 className="mt-3 text-2xl font-bold tracking-tight sm:text-3xl">
            {trustHeading}
          </h2>
          <div className="mt-10 grid gap-4 sm:grid-cols-2 md:grid-cols-3">
            {trustItems.map((item) => {
              const Icon = resolveIcon(item.iconName, Shield);
              return (
                <article key={item.title} className="p-2">
                  <div className="inline-flex h-10 w-10 items-center justify-center rounded-xl border border-border bg-background/80">
                    <Icon className="h-5 w-5 text-amber-400" />
                  </div>
                  <h3 className="mt-4 text-base font-semibold">{item.title}</h3>
                  <p className="mt-2 text-sm leading-6 text-muted-foreground">{item.description}</p>
                </article>
              );
            })}
          </div>
        </div>
      </section>

      {/* ── PRICING ──────────────────────────────────────────────── */}
      <section id="pricing" className="border-t border-border py-16 md:py-24">
        <div className="mx-auto max-w-3xl px-4 sm:px-6 lg:px-8">
          <p className="text-xs font-semibold uppercase tracking-widest text-amber-500">
            {pricingSectionLabel}
          </p>
          <h2 className="mt-3 text-2xl font-bold tracking-tight sm:text-3xl">
            {pricingHeading}
          </h2>
          {pricingSubheading && (
            <p className="mt-3 max-w-xl text-sm leading-6 text-muted-foreground">
              {pricingSubheading}
            </p>
          )}

          {/* Current phase — pill-switched tier card */}
          <PricingTierSwitcher
            freePlan={freePlan}
            currentPlans={currentPlans}
            finalPhasePlan={finalPhasePlan}
            spotsLeft={currentPlans[0]?.spotLimit ? Math.max(0, currentPlans[0].spotLimit - signupCount) : null}
            spotLimit={currentPlans[0]?.spotLimit ?? null}
            signupCount={signupCount}
            fillPct={currentPlans[0]?.spotLimit ? Math.min(100, (signupCount / currentPlans[0].spotLimit) * 100) : 0}
            founderNote={pricingFounderNote}
          />

        </div>
      </section>

      {/* ── OFFER ────────────────────────────────────────────────── */}
      {showOffer && (
        <section className="border-t border-border py-16 md:py-24">
          <div className="mx-auto max-w-3xl px-4 sm:px-6 lg:px-8">
            <div className="relative overflow-hidden rounded-2xl border border-amber-500/25 bg-amber-500/5 p-8 md:p-10">
              {/* Glow */}
              <div aria-hidden className="pointer-events-none absolute -right-16 -top-16 h-64 w-64 rounded-full bg-amber-500/10 blur-3xl" />

              <div className="relative">
                <div className="flex flex-wrap items-center gap-3">
                  {offerSectionLabel && (
                    <p className="text-xs font-semibold uppercase tracking-widest text-amber-500">
                      {offerSectionLabel}
                    </p>
                  )}
                  {offerBadge && (
                    <span className="inline-flex items-center rounded-full border border-amber-500/30 bg-amber-500/10 px-2.5 py-0.5 text-xs font-semibold text-amber-400">
                      {offerBadge}
                    </span>
                  )}
                </div>

                {offerHeading && (
                  <h2 className="mt-3 text-2xl font-bold tracking-tight sm:text-3xl">
                    {offerHeading}
                  </h2>
                )}
                {offerSubheading && (
                  <p className="mt-2 text-sm leading-6 text-muted-foreground">{offerSubheading}</p>
                )}

                <div className="mt-6 flex flex-wrap items-end gap-3">
                  {offerDiscountedPrice && (
                    <span className="text-5xl font-bold tracking-tight text-amber-400">
                      {offerDiscountedPrice}
                    </span>
                  )}
                  {offerOriginalPrice && (
                    <span className="mb-1 text-xl text-muted-foreground line-through">{offerOriginalPrice}</span>
                  )}
                  {offerSavingsText && (
                    <span className="mb-1 inline-flex items-center rounded-full bg-green-500/15 px-2.5 py-0.5 text-sm font-semibold text-green-400">
                      {offerSavingsText}
                    </span>
                  )}
                </div>

                {offerDescription && (
                  <p className="mt-4 text-sm leading-6 text-muted-foreground">{offerDescription}</p>
                )}

                {offerFeatures && offerFeatures.length > 0 && (
                  <ul className="mt-6 grid gap-2 sm:grid-cols-2">
                    {offerFeatures.map((f) => (
                      <li key={f} className="flex items-center gap-2.5 text-sm">
                        <Check className="h-4 w-4 shrink-0 text-amber-400" />
                        <span>{f}</span>
                      </li>
                    ))}
                  </ul>
                )}

                <div className="mt-8 flex flex-wrap items-center gap-4">
                  <Link
                    href="#final-cta"
                    className="inline-flex items-center gap-2 rounded-xl bg-amber-500 px-6 py-3 text-sm font-semibold text-black shadow-lg shadow-amber-500/20 transition-all hover:bg-amber-400"
                  >
                    {offerCtaLabel}
                    <ArrowRight className="h-4 w-4" />
                  </Link>
                  <div className="flex flex-col gap-0.5">
                    {offerUrgencyText && (
                      <p className="text-xs font-medium text-amber-400">{offerUrgencyText}</p>
                    )}
                    {offerExpiryText && (
                      <p className="text-xs text-muted-foreground">{offerExpiryText}</p>
                    )}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>
      )}

      {/* ── FINAL CTA ────────────────────────────────────────────── */}
      <section id="final-cta" className="border-t border-border py-20 md:py-28">
        <div className="mx-auto max-w-2xl px-4 text-center">
          <p className="text-xs font-semibold uppercase tracking-widest text-amber-500">
            {ctaSectionLabel}
          </p>
          <h2 className="mt-3 text-3xl font-bold tracking-tight sm:text-4xl">
            {ctaHeading}
          </h2>
          <p className="mt-4 text-base leading-7 text-muted-foreground">
            {ctaDescription}
          </p>

          <EarlyAccessSignupForm />
          <p className="mt-4 text-xs text-muted-foreground">
            {ctaFootnote}
          </p>
        </div>
      </section>
    </main>
  );
}
