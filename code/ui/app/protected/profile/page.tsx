import { Suspense } from "react";
import { createClient } from "@/lib/supabase/server";
import { redirect } from "next/navigation";
import Link from "next/link";
import { KeyRound, Lock, LogOut } from "lucide-react";
import { LogoutButton } from "@/components/logout-button";

export const metadata = { title: "Profile" };

async function ProfileContent() {
  const supabase = await createClient();
  const {
    data: { user },
    error,
  } = await supabase.auth.getUser();

  if (error || !user) redirect("/auth/login");

  const joined = new Date(user.created_at).toLocaleDateString("en-US", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });

  const lastSignIn = user.last_sign_in_at
    ? new Date(user.last_sign_in_at).toLocaleDateString("en-US", {
        year: "numeric",
        month: "long",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : null;

  return (
    <div className="flex flex-col gap-8 w-full">
      <div>
        <h1 className="text-2xl font-bold">Profile</h1>
        <p className="text-sm text-muted-foreground mt-1">Your account details and settings.</p>
      </div>

      {/* Account info */}
      <section className="rounded-lg border divide-y">
        <div className="px-4 py-3">
          <p className="text-xs text-muted-foreground uppercase tracking-wide font-medium mb-3">
            Account
          </p>
          <dl className="space-y-3 text-sm">
            <div className="flex justify-between gap-4">
              <dt className="text-muted-foreground">Email</dt>
              <dd className="font-medium truncate">{user.email}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-muted-foreground">User ID</dt>
              <dd className="font-mono text-xs text-muted-foreground truncate">{user.id}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-muted-foreground">Member since</dt>
              <dd>{joined}</dd>
            </div>
            {lastSignIn && (
              <div className="flex justify-between gap-4">
                <dt className="text-muted-foreground">Last sign-in</dt>
                <dd>{lastSignIn}</dd>
              </div>
            )}
          </dl>
        </div>
      </section>

      {/* Settings links */}
      <section className="rounded-lg border divide-y">
        <Link
          href="/protected/api-keys"
          className="flex items-center gap-3 px-4 py-3 hover:bg-muted/50 transition-colors"
        >
          <KeyRound className="h-4 w-4 text-muted-foreground shrink-0" />
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium">API Keys</p>
            <p className="text-xs text-muted-foreground">Manage keys for the public REST API</p>
          </div>
        </Link>
        <Link
          href="/auth/update-password"
          className="flex items-center gap-3 px-4 py-3 hover:bg-muted/50 transition-colors"
        >
          <Lock className="h-4 w-4 text-muted-foreground shrink-0" />
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium">Change password</p>
            <p className="text-xs text-muted-foreground">Update your login password</p>
          </div>
        </Link>
        <div className="flex items-center gap-3 px-4 py-3">
          <LogOut className="h-4 w-4 text-muted-foreground shrink-0" />
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium">Sign out</p>
            <p className="text-xs text-muted-foreground">Sign out of this device</p>
          </div>
          <LogoutButton />
        </div>
      </section>
    </div>
  );
}

export default function ProfilePage() {
  return (
    <div className="flex-1 w-full max-w-lg">
      <Suspense
        fallback={
          <div className="text-sm text-muted-foreground animate-pulse">Loading profile…</div>
        }
      >
        <ProfileContent />
      </Suspense>
    </div>
  );
}
