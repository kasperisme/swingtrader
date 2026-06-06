import { getOrCreateUserProfile } from "@/lib/user-profile";
import { createClient } from "@/lib/supabase/server";
import { getUserSubscription } from "@/lib/subscription";
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

  return (
    <main className="min-h-screen flex flex-col">
      <div className="mx-auto w-full min-w-0 max-w-7xl px-4 py-8 sm:px-6 lg:px-8 flex-1">
        <BillingBanner
          status={subscription?.status ?? null}
          currentPeriodEnd={subscription?.current_period_end ?? null}
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
