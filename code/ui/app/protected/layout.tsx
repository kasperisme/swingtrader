import { getOrCreateUserProfile } from "@/lib/user-profile";
import { createClient } from "@/lib/supabase/server";
import { getUserSubscription, getSignupTrialEnd } from "@/lib/subscription";
import { PAID_PLANS, type PlanTier } from "@/lib/plans";
import { PRELAUNCH_OPEN_ACCESS } from "@/lib/launch";
import { WelcomeDialog } from "./_components/welcome-dialog";
import { PostWelcomeHighlightTour } from "./_components/post-welcome-highlight-tour";
import { HelpChatRoot } from "@/components/help-chat";
import { SetupAssistantRoot } from "@/components/setup-assistant";
import { BillingBanner } from "@/components/billing-banner";

export default async function ProtectedLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const profile = await getOrCreateUserProfile();
  const showWelcome = profile !== null && profile.welcomed_at === null;

  const supabase = await createClient();
  const subscription = await getUserSubscription(supabase);

  // App-managed signup trial: when the user has no active paid subscription,
  // surface the 14-day-from-signup trial countdown (and the "trial ended" nudge
  // afterwards). Suppress it for anyone already on an active/trialing paid plan.
  const onPaidSub =
    subscription != null &&
    ["active", "trialing"].includes(subscription.status) &&
    PAID_PLANS.includes(subscription.plan as PlanTier);
  // Suppress the trial banner during the open beta — nothing is enforced yet,
  // so a countdown / "ended" nudge would be misleading.
  let trialEndsAt: string | null = null;
  if (!onPaidSub && !PRELAUNCH_OPEN_ACCESS) {
    const { data: userData } = await supabase.auth.getUser();
    trialEndsAt = await getSignupTrialEnd(userData.user?.created_at);
  }

  return (
    <main className="min-h-screen flex flex-col">
      <div className="mx-auto w-full min-w-0 max-w-7xl px-4 py-8 sm:px-6 lg:px-8 flex-1">
        <BillingBanner
          status={subscription?.status ?? null}
          currentPeriodEnd={subscription?.current_period_end ?? null}
          trialEndsAt={trialEndsAt}
        />
        {children}
      </div>
      {showWelcome && <WelcomeDialog displayName={profile?.display_name ?? null} />}
      <PostWelcomeHighlightTour />
      <HelpChatRoot />
      <SetupAssistantRoot />
    </main>
  );
}
