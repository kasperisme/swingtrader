import { Suspense } from "react";
import { createClient } from "@/lib/supabase/server";
import { redirect } from "next/navigation";
import Link from "next/link";
import {
  AlertTriangle,
  ChevronRight,
  KeyRound,
  Lock,
  LogOut,
  Mail,
  Sparkles,
} from "lucide-react";
import { LogoutButton } from "@/components/logout-button";
import { TelegramConnect } from "@/components/telegram-connect";
import { ManageBillingButton } from "@/components/manage-billing-button";
import { ChangePlan } from "@/components/change-plan";
import { Badge } from "@/components/ui/badge";
import { TradingStrategyForm } from "@/components/trading-strategy-form";
import { getTradingStrategy } from "@/app/actions/trading-strategy";
import { LanguageSelector } from "@/components/language-selector";
import { getPreferredLanguage } from "@/app/actions/preferences";
import { getOnboardingProgress, getOnboardingTours } from "@/app/actions/onboarding";
import { PageTour } from "@/app/protected/_components/page-tour";
import { RestartOnboardingButton } from "@/app/protected/_components/restart-onboarding-button";
import { SetupAssistantTrigger } from "@/components/setup-assistant";

export const metadata = { title: "Profile" };

// One label style, defined once. It used to be pasted into six card headers,
// which is why every group on the page shouted at the same volume.
const SECTION_LABEL =
  "font-mono text-[11px] font-semibold uppercase tracking-[0.16em] text-amber-700 dark:text-amber-500";
const CARD = "rounded-2xl border border-border bg-card overflow-hidden";
const ROW = "flex items-center justify-between gap-4 px-5 py-3";
const DT = "text-sm text-muted-foreground";
const DD = "font-mono text-[13px] tabular-nums text-foreground";

function StatusBadge({ status, grandfathered }: { status: string; grandfathered: boolean }) {
  const label = status.replace(/_/g, " ");
  if (status === "active") {
    return (
      <Badge variant="default" className="bg-emerald-600/90 border-emerald-600/90 text-white">
        {grandfathered ? "Active (grandfathered)" : "Active"}
      </Badge>
    );
  }
  if (status === "trialing") {
    return <Badge variant="default" className="bg-amber-600/90 border-amber-600/90 text-white">Trial</Badge>;
  }
  if (status === "past_due") {
    return <Badge variant="destructive">Past due</Badge>;
  }
  if (status === "canceled") {
    return <Badge variant="secondary">Canceled</Badge>;
  }
  return <Badge variant="outline" className="capitalize">{label}</Badge>;
}

/** Section heading. These were `<p>` tags, so the page had an h1 and no other
 *  headings at all — no outline for screen readers, and no visual hierarchy
 *  between "Subscription" and "Preferences". */
function SectionHeading({ id, children }: { id: string; children: React.ReactNode }) {
  return (
    <h2 id={id} className={`${SECTION_LABEL} mb-3`}>
      {children}
    </h2>
  );
}

/** A destination. Chevron because it navigates — actions in the same list get a
 *  button instead, so affordance matches behaviour. */
function SettingsLink({
  href,
  icon,
  title,
  description,
  external,
  ...rest
}: {
  href: string;
  icon: React.ReactNode;
  title: string;
  description: string;
  external?: boolean;
  [key: string]: unknown;
}) {
  const inner = (
    <>
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-border bg-background">
        {icon}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-medium text-foreground">{title}</span>
        <span className="block truncate text-xs text-muted-foreground">{description}</span>
      </span>
      <ChevronRight
        className="h-4 w-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5"
        aria-hidden
      />
    </>
  );
  const className =
    "group flex min-h-[3.5rem] cursor-pointer items-center gap-3 px-5 py-3.5 transition-colors hover:bg-muted/60 focus-visible:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-amber-500/60";

  return external ? (
    <a href={href} className={className} {...rest}>
      {inner}
    </a>
  ) : (
    <Link href={href} className={className} {...rest}>
      {inner}
    </Link>
  );
}

/** An action. No chevron — nothing navigates; the control is the affordance. */
function SettingsAction({
  icon,
  title,
  description,
  control,
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
  control: React.ReactNode;
}) {
  return (
    <div className="flex min-h-[3.5rem] items-center gap-3 px-5 py-3.5">
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-border bg-background">
        {icon}
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-foreground">{title}</p>
        <p className="text-xs leading-relaxed text-muted-foreground">{description}</p>
      </div>
      {control}
    </div>
  );
}

async function ProfileContent() {
  const supabase = await createClient();
  const {
    data: { user },
    error,
  } = await supabase.auth.getUser();

  if (error || !user) redirect("/auth/login");

  const [{ data: subscription }, tradingStrategy, onboardingProgress, preferredLanguage] = await Promise.all([
    supabase
      .schema("swingtrader")
      .from("user_subscriptions")
      .select("plan, billing_interval, status, grandfathered, current_period_end, stripe_customer_id")
      .eq("user_id", user.id)
      .maybeSingle(),
    getTradingStrategy(),
    getOnboardingProgress(),
    getPreferredLanguage(),
  ]);

  const onboardingTotal = 8;
  const onboardingCompleted = Object.values(onboardingProgress).filter(Boolean).length;

  const joined = new Date(user.created_at).toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });

  const lastSignIn = user.last_sign_in_at
    ? new Date(user.last_sign_in_at).toLocaleDateString("en-US", {
        year: "numeric",
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : null;

  const monogram = (user.email ?? "?").trim().charAt(0).toUpperCase();
  const planLabel = subscription?.plan ?? "Free";
  // The two states that silently stop the product working. Worth an alert
  // rather than a badge three rows down a list.
  const needsAttention =
    subscription?.status === "past_due" || subscription?.status === "canceled";

  return (
    <div className="flex w-full flex-col gap-10">
      {/* ── Header ───────────────────────────────────────────────────────── */}
      <header className="flex flex-wrap items-end justify-between gap-4 border-b border-border/60 pb-6">
        <div className="min-w-0">
          <p className="mb-3 inline-flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.2em] text-amber-700 dark:text-amber-500/90">
            <span className="h-px w-6 bg-amber-500/60" />
            Account
          </p>
          <h1 className="text-3xl font-bold leading-[1.05] tracking-tighter sm:text-4xl">
            Profile
          </h1>
          <p className="mt-3 max-w-[58ch] text-sm leading-relaxed text-muted-foreground">
            Your account, your plan, and the settings that decide how the agents
            work for you.
          </p>
        </div>
        <SetupAssistantTrigger className="inline-flex shrink-0 cursor-pointer items-center gap-1.5 rounded-lg border border-amber-500/40 bg-amber-500/5 px-3.5 py-2 text-sm font-medium text-foreground transition-colors hover:bg-amber-500/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500/60" />
      </header>

      {/* ── Identity ─────────────────────────────────────────────────────────
          Absorbs what used to be a separate "Account details" card: who you are
          and what you're on, answered before anything asks you to scroll. */}
      <section aria-labelledby="identity">
        <h2 id="identity" className="sr-only">
          Account identity
        </h2>
        <div className="flex flex-wrap items-center gap-x-5 gap-y-4">
          <span
            aria-hidden
            className="grid h-14 w-14 shrink-0 place-items-center rounded-2xl border border-amber-500/30 bg-amber-500/10 font-mono text-xl font-semibold text-amber-600 dark:text-amber-400"
          >
            {monogram}
          </span>
          <div className="min-w-0 flex-1">
            <p className="truncate font-mono text-[15px] font-medium text-foreground">
              {user.email}
            </p>
            <dl className="mt-1.5 flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-muted-foreground">
              <div className="flex items-center gap-1.5">
                <dt>Member since</dt>
                <dd className="font-mono tabular-nums text-foreground">{joined}</dd>
              </div>
              {lastSignIn && (
                <div className="flex items-center gap-1.5">
                  <dt>Last sign-in</dt>
                  <dd className="font-mono tabular-nums text-foreground">{lastSignIn}</dd>
                </div>
              )}
            </dl>
          </div>
          {/* Own line on mobile: at 390px the avatar, email and badges were
              fighting over ~150px and the email truncated to nothing. */}
          <div className="flex w-full shrink-0 items-center gap-2 sm:w-auto">
            <span className="rounded-md border border-amber-500/30 bg-amber-500/5 px-2 py-1 font-mono text-[11px] font-semibold uppercase tracking-[0.1em] text-amber-600 dark:text-amber-400">
              {planLabel}
            </span>
            {subscription && (
              <StatusBadge
                status={subscription.status}
                grandfathered={subscription.grandfathered}
              />
            )}
          </div>
        </div>
      </section>

      {/* Only rendered when something is actually wrong. */}
      {needsAttention && (
        <div className="flex items-start gap-3 rounded-xl border border-destructive/40 bg-destructive/5 px-4 py-3.5">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" aria-hidden />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium text-foreground">
              {subscription?.status === "past_due"
                ? "Your last payment failed."
                : "Your subscription is cancelled."}
            </p>
            <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
              Scheduled agents don&apos;t run without an active plan — they only send a
              reminder. Update billing below to start them again.
            </p>
          </div>
          {subscription?.stripe_customer_id && <ManageBillingButton />}
        </div>
      )}

      {/* ── Two columns on desktop ───────────────────────────────────────────
          The page was pinned to max-w-2xl inside a max-w-7xl layout: six
          identical cards in a single narrow ribbon. What you act on sits in the
          main column; what you set once sits beside it. */}
      <div className="grid gap-10 lg:grid-cols-3 lg:gap-8">
        <div className="flex flex-col gap-8 lg:col-span-2">
          {/* Subscription */}
          <section data-tour="subscription" aria-labelledby="subscription-heading">
            <div className="mb-3 flex items-center justify-between gap-4">
              <h2 id="subscription-heading" className={SECTION_LABEL}>
                Subscription
              </h2>
              {subscription?.stripe_customer_id && !needsAttention && <ManageBillingButton />}
            </div>
            <div className={CARD}>
              <dl className="divide-y divide-border">
                {subscription ? (
                  <>
                    <div className={ROW}>
                      <dt className={DT}>Billing</dt>
                      <dd className={`${DD} capitalize`}>{subscription.billing_interval}</dd>
                    </div>
                    {subscription.current_period_end && (
                      <div className={ROW}>
                        <dt className={DT}>
                          {subscription.status === "canceled" ? "Access until" : "Renews"}
                        </dt>
                        <dd className={DD}>
                          {new Date(subscription.current_period_end).toLocaleDateString("en-US", {
                            year: "numeric",
                            month: "long",
                            day: "numeric",
                          })}
                        </dd>
                      </div>
                    )}
                  </>
                ) : (
                  <div className="px-5 py-4">
                    <p className="text-sm text-muted-foreground">
                      You&apos;re on the free tier. Pick a plan to run scheduled agents
                      and unlock the full impact history.
                    </p>
                  </div>
                )}
                {/* Checkout for free/lapsed accounts, in-place switch for live
                    subscriptions. The API decides which. */}
                <ChangePlan hasSubscription={Boolean(subscription?.stripe_customer_id)} />
              </dl>
            </div>
          </section>

          {/* Trading strategy */}
          <section data-tour="trading-strategy" aria-labelledby="strategy-heading">
            <SectionHeading id="strategy-heading">Trading strategy</SectionHeading>
            <div className={CARD}>
              <div className="flex flex-col gap-2 px-5 py-4">
                <p className="text-xs leading-relaxed text-muted-foreground">
                  Describe your trading approach. All AI agents — chart analysis,
                  screening, and synthesis — align their recommendations to it.
                </p>
                <TradingStrategyForm initialStrategy={tradingStrategy} />
              </div>
            </div>
          </section>

          {/* Telegram — brings its own card chrome. */}
          <section data-tour="telegram-connect" aria-labelledby="notifications-heading">
            <SectionHeading id="notifications-heading">Notifications</SectionHeading>
            <TelegramConnect />
          </section>
        </div>

        {/* ── Aside ────────────────────────────────────────────────────────── */}
        <div className="flex flex-col gap-8">
          <section aria-labelledby="preferences-heading">
            <SectionHeading id="preferences-heading">Preferences</SectionHeading>
            <div className={CARD}>
              <div className="flex flex-col gap-3 px-5 py-4">
                <div className="min-w-0">
                  <label
                    htmlFor="preferred-language"
                    className="text-sm font-medium text-foreground"
                  >
                    Language
                  </label>
                  <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
                    Used for agent alerts and Telegram messages.
                  </p>
                </div>
                <LanguageSelector id="preferred-language" initialValue={preferredLanguage} className="w-full" />
              </div>
            </div>
          </section>

          <section aria-labelledby="settings-heading">
            <SectionHeading id="settings-heading">Settings</SectionHeading>
            <div className={CARD}>
              <div className="divide-y divide-border">
                <SettingsLink
                  data-tour="api-keys"
                  href="/protected/api-keys"
                  icon={<KeyRound className="h-4 w-4 text-amber-500" />}
                  title="API keys"
                  description="Keys for the public REST API"
                />
                <SettingsLink
                  href="/auth/update-password"
                  icon={<Lock className="h-4 w-4 text-amber-500" />}
                  title="Change password"
                  description="Update your login password"
                />
                <SettingsLink
                  external
                  href={`mailto:k@newsimpactscreener.com?subject=${encodeURIComponent("News Impact Screener — feedback")}`}
                  icon={<Mail className="h-4 w-4 text-amber-500" />}
                  title="Feedback & support"
                  description="k@newsimpactscreener.com"
                />
                <SettingsAction
                  icon={<Sparkles className="h-4 w-4 text-amber-500" />}
                  title="Onboarding tour"
                  description={
                    onboardingCompleted === onboardingTotal
                      ? `All ${onboardingTotal} steps complete.`
                      : `${onboardingCompleted} of ${onboardingTotal} steps complete.`
                  }
                  control={
                    <RestartOnboardingButton
                      completedSteps={onboardingCompleted}
                      totalSteps={onboardingTotal}
                    />
                  }
                />
              </div>
            </div>
          </section>

          {/* Sign out — separated so it is never a mis-click inside the list. */}
          <section aria-labelledby="session-heading">
            <h2 id="session-heading" className="sr-only">
              Session
            </h2>
            <div className="flex items-center gap-3 rounded-2xl border border-border px-5 py-3.5">
              <LogOut className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-foreground">Sign out</p>
                <p className="text-xs text-muted-foreground">Sign out of this device</p>
              </div>
              <LogoutButton />
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}

async function ProfileTourMount() {
  const tours = await getOnboardingTours();
  return <PageTour tourKey="profile" autoStart={!tours.profile} />;
}

export default function ProfilePage() {
  return (
    <div className="w-full max-w-5xl flex-1">
      <Suspense
        fallback={
          <div className="animate-pulse text-sm text-muted-foreground">Loading profile…</div>
        }
      >
        <ProfileContent />
      </Suspense>
      <Suspense fallback={null}>
        <ProfileTourMount />
      </Suspense>
    </div>
  );
}
