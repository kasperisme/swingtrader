import Link from "next/link";
import { redirect } from "next/navigation";
import { unstable_noStore as noStore } from "next/cache";
import { createServiceClient } from "@/lib/supabase/service";
import {
  ArrowRight,
  BarChart3,
  Bell,
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
import { EarlyAccessSignupForm } from "@/components/early-access-signup-form";
import { InstagramSection } from "@/components/instagram-section";
import { PricingTierSwitcher } from "@/components/pricing-tier-switcher";
import { isSanityConfigured, sanityFetch } from "@/lib/sanity/client";
import { landingPageQuery } from "@/lib/sanity/queries";
import type { LandingPage, LandingCardItem, LandingStep, LandingPricingPlan } from "@/lib/sanity/types";
import { listMarketScreenings } from "@/app/actions/market-screenings";
import { humanizeCron } from "@/lib/cron-format";

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

  const supabase = await createClient();
  const { data: claims } = await supabase.auth.getClaims();
  if (claims?.claims?.sub) {
    redirect("/protected");
  }

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
  const heroSpotLimit = currentPlans[0]?.spotLimit ?? null;
  const heroSpotsLeft =
    heroSpotLimit != null ? Math.max(0, heroSpotLimit - signupCount) : null;
  const heroFillPct =
    heroSpotLimit ? Math.min(100, (signupCount / heroSpotLimit) * 100) : 0;

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

  // Market screenings preview — up to 3 to highlight on the landing page.
  let marketScreeningsPreview: Awaited<ReturnType<typeof listMarketScreenings>> = [];
  try {
    const all = await listMarketScreenings();
    marketScreeningsPreview = all.slice(0, 3);
  } catch {
    marketScreeningsPreview = [];
  }

  return (
    <main className="min-h-screen bg-background text-foreground">
      {/* ── HERO ─────────────────────────────────────────────────── */}
      <section className="relative overflow-hidden pb-0 pt-10 md:pt-16">
        {/* Ambient amber glow — single accent, soft, behind the choice panel. */}
        <div
          aria-hidden
          className="pointer-events-none absolute -top-32 right-[-10%] h-[34rem] w-[34rem] rounded-full bg-amber-500/10 blur-[120px]"
        />
        <div
          aria-hidden
          className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-amber-500/30 to-transparent"
        />

        <div className="relative mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
          <div className="grid items-center gap-x-12 gap-y-12 py-8 lg:grid-cols-12 lg:py-16">
            {/* ── Pitch (editorial, left) ───────────────────────────── */}
            <div className="lg:col-span-5">
              <div className="inline-flex items-center gap-2 rounded-full border border-amber-500/25 bg-amber-500/10 px-3 py-1.5 text-xs font-semibold text-amber-400">
                <span className="relative flex h-1.5 w-1.5">
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-amber-400 opacity-75" />
                  <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-amber-400" />
                </span>
                {heroBadgeText}
              </div>

              <h1 className="mt-6 text-balance text-4xl font-bold leading-[0.95] tracking-tighter sm:text-5xl lg:text-6xl">
                {heroHeadlinePart1}{" "}
                <span className="text-amber-500">{heroHeadlineHighlight}</span>
              </h1>
              <p className="mt-5 max-w-md text-base leading-7 text-muted-foreground">
                Two free tools, no account and no card. Subscribe once and the
                signals come to you — in your inbox and on Telegram.
              </p>

              <div className="mt-7 flex flex-wrap items-center gap-x-5 gap-y-2 text-xs">
                <span className="inline-flex items-center gap-2 font-semibold text-emerald-400">
                  <Check className="h-3.5 w-3.5" />
                  Free — no card required
                </span>
                <span className="inline-flex items-center gap-2 font-semibold text-foreground/80">
                  <Bell className="h-3.5 w-3.5" />
                  Telegram &amp; email delivery
                </span>
                <Link
                  href="#how-it-works"
                  className="font-medium text-muted-foreground underline-offset-4 transition-colors hover:text-foreground hover:underline"
                >
                  See how it works →
                </Link>
              </div>
            </div>

            {/* ── Choice panel (the decision, right) ────────────────── */}
            <div className="lg:col-span-7">
              <div className="rounded-3xl border border-border bg-card/40 p-5 shadow-[0_24px_80px_-32px_rgba(0,0,0,0.6)] backdrop-blur-sm sm:p-6">
                <p className="px-1 text-[11px] font-semibold uppercase tracking-[0.2em] text-muted-foreground">
                  Start free in seconds —{" "}
                  <span className="text-amber-500">pick one, or both</span>
                </p>

                <div className="mt-4 grid gap-3">
                  {/* Path A — Market screenings */}
                  <Link
                    href="/marketscreenings"
                    className="group relative block rounded-2xl border border-border bg-background/50 p-5 transition duration-300 hover:-translate-y-0.5 hover:border-amber-400/60 hover:bg-amber-500/[0.06] hover:shadow-[0_16px_50px_-20px_rgba(245,158,11,0.35)]"
                  >
                    <div className="flex items-start gap-4">
                      <span className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-border bg-background/80 transition-colors duration-300 group-hover:border-amber-400/50 group-hover:bg-amber-500/10">
                        <Filter className="h-5 w-5 text-amber-400" />
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <h2 className="text-[15px] font-semibold tracking-tight transition-colors group-hover:text-amber-400">
                            Free market screenings
                          </h2>
                          <span className="rounded-full border border-border px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                            Curated screeners
                          </span>
                        </div>
                        <p className="mt-1.5 text-sm leading-6 text-muted-foreground">
                          Platform-run Stage 2 setups, breakouts and
                          fundamentals. Subscribe once; results hit your inbox.
                        </p>
                        <span className="mt-3 inline-flex items-center gap-1.5 text-sm font-semibold text-amber-400">
                          Set up screenings
                          <ArrowRight className="h-4 w-4 transition-transform duration-300 group-hover:translate-x-1" />
                        </span>
                      </div>
                    </div>
                  </Link>

                  {/* OR — make the either/or unmistakable */}
                  <div className="relative flex items-center justify-center py-0.5">
                    <span aria-hidden className="absolute inset-x-2 h-px bg-border" />
                    <span className="relative rounded-full border border-border bg-card px-3 py-1 text-[10px] font-bold uppercase tracking-[0.25em] text-muted-foreground">
                      or
                    </span>
                  </div>

                  {/* Path B — News briefings */}
                  <Link
                    href="/briefings"
                    className="group relative block rounded-2xl border border-border bg-background/50 p-5 transition duration-300 hover:-translate-y-0.5 hover:border-amber-400/60 hover:bg-amber-500/[0.06] hover:shadow-[0_16px_50px_-20px_rgba(245,158,11,0.35)]"
                  >
                    <div className="flex items-start gap-4">
                      <span className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-border bg-background/80 transition-colors duration-300 group-hover:border-amber-400/50 group-hover:bg-amber-500/10">
                        <Newspaper className="h-5 w-5 text-amber-400" />
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <h2 className="text-[15px] font-semibold tracking-tight transition-colors group-hover:text-amber-400">
                            Free news briefings
                          </h2>
                          <span className="rounded-full border border-border px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                            Daily PDF · pre-open
                          </span>
                        </div>
                        <p className="mt-1.5 text-sm leading-6 text-muted-foreground">
                          Last 24h of news — summaries and market impact — for
                          your tickers and tags, an hour before the open.
                        </p>
                        <span className="mt-3 inline-flex items-center gap-1.5 text-sm font-semibold text-amber-400">
                          Set up briefings
                          <ArrowRight className="h-4 w-4 transition-transform duration-300 group-hover:translate-x-1" />
                        </span>
                      </div>
                    </div>
                  </Link>
                </div>
              </div>
            </div>
          </div>

          {/* News ticker — full-width band, visible above the fold */}
          <div className="overflow-hidden border-t border-border py-3">
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

      {/* ── INSTAGRAM ────────────────────────────────────────────── */}
      <InstagramSection />

      {/* ── HOW IT WORKS ─────────────────────────────────────────── */}
      <section id="how-it-works" className="border-t border-border py-16 md:py-24">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
          <p className="text-xs font-semibold uppercase tracking-widest text-amber-500">
            {howItWorksSectionLabel}
          </p>
          <h2 className="mt-3 text-2xl font-bold tracking-tight sm:text-3xl">{howItWorksHeading}</h2>

          <ol className="mt-12">
            {howItWorksSteps.map((step, index) => (
              <li
                key={step.label}
                className="group grid grid-cols-[3rem_1fr] items-baseline gap-x-5 gap-y-1 border-t border-border py-8 transition-colors last:border-b hover:bg-amber-500/[0.03] md:grid-cols-[6rem_minmax(0,16rem)_1fr] md:gap-x-10"
              >
                <span
                  aria-hidden
                  className="font-mono text-3xl font-semibold tabular-nums text-amber-500/35 transition-colors group-hover:text-amber-500/70 md:text-5xl"
                >
                  {String(index + 1).padStart(2, "0")}
                </span>
                <h3 className="col-start-2 self-baseline text-lg font-semibold tracking-tight md:text-xl">
                  {step.label}
                </h3>
                <p className="col-span-2 col-start-1 mt-1 max-w-prose text-sm leading-6 text-muted-foreground md:col-span-1 md:col-start-3 md:mt-0">
                  {step.detail}
                </p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* ── BENTO FEATURES ───────────────────────────────────────── */}
      <section className="py-16 md:py-24">
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

      {/* ── MARKET SCREENINGS ────────────────────────────────────── */}
      <section id="market-screenings" className="border-t border-border py-16 md:py-24">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
          <p className="text-xs font-semibold uppercase tracking-widest text-amber-500">
            Free market screenings
          </p>
          <h2 className="mt-3 text-2xl font-bold tracking-tight sm:text-3xl">
            Curated screenings, free to subscribe
          </h2>
          <p className="mt-3 max-w-xl text-sm leading-6 text-muted-foreground">
            Platform-managed screenings — Stage 2 setups, technicals, fundamentals — run on a schedule. Subscribe once and the results land in your inbox and Telegram, no setup required.
          </p>

          {marketScreeningsPreview.length > 0 ? (
            <div className="mt-10 grid gap-4 sm:grid-cols-2 md:grid-cols-3">
              {marketScreeningsPreview.map((s) => (
                <Link
                  key={s.id}
                  href={`/marketscreenings/${s.slug}`}
                  className="group flex flex-col rounded-2xl border border-border bg-background/60 p-5 transition-colors hover:border-amber-400/60 hover:bg-amber-500/5"
                >
                  <div className="flex items-center gap-2 text-xs text-muted-foreground">
                    {s.category && (
                      <span className="rounded-full border border-border px-2 py-0.5">
                        {s.category}
                      </span>
                    )}
                    <span className="truncate">
                      {humanizeCron(s.schedule, s.timezone)}
                    </span>
                  </div>
                  <h3 className="mt-3 text-base font-semibold leading-snug group-hover:text-amber-400">
                    {s.name}
                  </h3>
                  {s.description && (
                    <p className="mt-2 line-clamp-3 text-sm leading-6 text-muted-foreground">
                      {s.description}
                    </p>
                  )}
                  <span className="mt-4 text-xs font-medium text-amber-400">
                    View screening →
                  </span>
                </Link>
              ))}
            </div>
          ) : (
            <p className="mt-8 text-sm text-muted-foreground">
              New screenings publishing soon.
            </p>
          )}

          <div className="mt-10">
            <Link
              href="/marketscreenings"
              className="inline-flex items-center gap-1.5 text-sm font-medium text-amber-400 hover:underline"
            >
              Browse all market screenings →
            </Link>
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

          {/* Free-until-launch callout */}
          <div className="mt-6 flex items-start gap-3 rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-4">
            <span className="mt-0.5 inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-emerald-500/15">
              <Check className="h-3.5 w-3.5 text-emerald-400" />
            </span>
            <div className="text-sm leading-6">
              <span className="font-semibold text-emerald-300">Free to explore until launch.</span>{" "}
              <span className="text-muted-foreground">
                The full platform is free of charge while we&apos;re in early access. The rates
                below only kick in at launch — and founders who sign up now lock theirs in for life.
              </span>
            </div>
          </div>

          {/* Current phase — pill-switched tier card */}
          <PricingTierSwitcher
            freePlan={freePlan}
            currentPlans={currentPlans}
            finalPhasePlan={finalPhasePlan}
            spotsLeft={heroSpotsLeft}
            spotLimit={heroSpotLimit}
            signupCount={signupCount}
            fillPct={heroFillPct}
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
