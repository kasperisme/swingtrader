import { Suspense } from "react";
import { createClient } from "@/lib/supabase/server";
import { redirect } from "next/navigation";
import Link from "next/link";
import { KeyRound, Lock, LogOut } from "lucide-react";
import { LogoutButton } from "@/components/logout-button";
import { TelegramConnect } from "@/components/telegram-connect";

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
        <p className="text-xs font-semibold uppercase tracking-widest text-amber-500">Account</p>
        <h1 className="mt-1 text-2xl font-bold tracking-tight">Profile</h1>
        <p className="mt-1 text-sm text-muted-foreground">Your account details and settings.</p>
      </div>

      {/* Account info */}
      <section className="rounded-2xl border border-border bg-card overflow-hidden">
        <div className="border-b border-border px-5 py-3">
          <p className="text-xs font-semibold uppercase tracking-widest text-amber-500">
            Account details
          </p>
        </div>
        <dl className="divide-y divide-border">
          <div className="flex items-center justify-between gap-4 px-5 py-3">
            <dt className="text-sm text-muted-foreground">Email</dt>
            <dd className="text-sm font-medium truncate">{user.email}</dd>
          </div>
          <div className="flex items-center justify-between gap-4 px-5 py-3">
            <dt className="text-sm text-muted-foreground">User ID</dt>
            <dd className="font-mono text-xs text-muted-foreground truncate">{user.id}</dd>
          </div>
          <div className="flex items-center justify-between gap-4 px-5 py-3">
            <dt className="text-sm text-muted-foreground">Member since</dt>
            <dd className="text-sm">{joined}</dd>
          </div>
          {lastSignIn && (
            <div className="flex items-center justify-between gap-4 px-5 py-3">
              <dt className="text-sm text-muted-foreground">Last sign-in</dt>
              <dd className="text-sm">{lastSignIn}</dd>
            </div>
          )}
        </dl>
      </section>

      {/* Telegram — pair account for Daily Narrative delivery */}
      <section>
        <div className="mb-3">
          <p className="text-xs font-semibold uppercase tracking-widest text-amber-500">
            Notifications
          </p>
        </div>
        <TelegramConnect />
      </section>

      {/* Settings links */}
      <section className="rounded-2xl border border-border bg-card overflow-hidden">
        <div className="border-b border-border px-5 py-3">
          <p className="text-xs font-semibold uppercase tracking-widest text-amber-500">
            Settings
          </p>
        </div>
        <div className="divide-y divide-border">
          <Link
            href="/protected/api-keys"
            className="flex cursor-pointer items-center gap-3 px-5 py-4 transition-colors hover:bg-muted/50"
          >
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-border bg-background">
              <KeyRound className="h-4 w-4 text-amber-400" />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium">API Keys</p>
              <p className="text-xs text-muted-foreground">Manage keys for the public REST API</p>
            </div>
          </Link>
          <Link
            href="/auth/update-password"
            className="flex cursor-pointer items-center gap-3 px-5 py-4 transition-colors hover:bg-muted/50"
          >
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-border bg-background">
              <Lock className="h-4 w-4 text-amber-400" />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium">Change password</p>
              <p className="text-xs text-muted-foreground">Update your login password</p>
            </div>
          </Link>
          <div className="flex items-center gap-3 px-5 py-4">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-border bg-background">
              <LogOut className="h-4 w-4 text-muted-foreground" />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium">Sign out</p>
              <p className="text-xs text-muted-foreground">Sign out of this device</p>
            </div>
            <LogoutButton />
          </div>
        </div>
      </section>
    </div>
  );
}

export default function ProfilePage() {
  return (
    <div className="flex-1 w-full max-w-2xl">
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
