import { getOrCreateUserProfile } from "@/lib/user-profile";
import { WelcomeDialog } from "./_components/welcome-dialog";

export default async function ProtectedLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const profile = await getOrCreateUserProfile();
  const showWelcome = profile !== null && profile.welcomed_at === null;

  return (
    <main className="min-h-screen flex flex-col">
      <div className="mx-auto w-full min-w-0 max-w-7xl px-4 py-8 sm:px-6 lg:px-8 flex-1">
        {children}
      </div>
      {showWelcome && <WelcomeDialog displayName={profile?.display_name ?? null} />}
    </main>
  );
}
