import { Suspense } from "react";
import { createClient } from "@/lib/supabase/server";
import { redirect } from "next/navigation";
import Link from "next/link";
import { KeyRound, Lock, LogOut, CreditCard } from "lucide-react";
import { LogoutButton } from "@/components/logout-button";
import { TelegramConnect } from "@/components/telegram-connect";
import { ManageBillingButton } from "@/components/manage-billing-button";
import { Badge } from "@/components/ui/badge";

export const metadata = { title: "Profile" };

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

async function ProfileContent() {
  const supabase = await createClient();
  const {
    data: { user },
    error,
  } = await supabase.auth.getUser();

  if (error || !user) redirect("/auth/login");

  const { data: subscription } = await supabase
    .schema("swingtrader")
    .from("user_subscriptions")
    .select("plan, billing_interval, status, grandfathered, current_period_end, stripe_customer_id")
    .eq("user_id", user.id)
    .maybeSingle();

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

      {/* Subscription */}
      <section className="rounded-2xl border border-border bg-card overflow-hidden">
        <div className="border-b border-border px-5 py-3 flex items-center justify-between">
          <p className="text-xs font-semibold uppercase tracking-widest text-amber-500">
            Subscription
          </p>
          {subscription?.stripe_customer_id && <ManageBillingButton />}
        </div>
        <dl className="divide-y divide-border">
          <div className="flex items-center justify-between gap-4 px-5 py-3">
            <dt className="text-sm text-muted-foreground">Plan</dt>
            <dd>
              {subscription ? (
                <span className="text-sm font-medium capitalize">{subscription.plan}</span>
              ) : (
                <span className="text-sm text-muted-foreground">Free</span>
              )}
            </dd>
          </div>
          {subscription && (
            <>
              <div className="flex items-center justify-between gap-4 px-5 py-3">
                <dt className="text-sm text-muted-foreground">Billing</dt>
                <dd className="text-sm capitalize">{subscription.billing_interval}</dd>
              </div>
              <div className="flex items-center justify-between gap-4 px-5 py-3">
                <dt className="text-sm text-muted-foreground">Status</dt>
                <dd>
                  <StatusBadge status={subscription.status} grandfathered={subscription.grandfathered} />
                </dd>
              </div>
              {subscription.current_period_end && (
                <div className="flex items-center justify-between gap-4 px-5 py-3">
                  <dt className="text-sm text-muted-foreground">
                    {subscription.status === "canceled" ? "Access until" : "Renews"}
                  </dt>
                  <dd className="text-sm">
                    {new Date(subscription.current_period_end).toLocaleDateString("en-US", {
                      year: "numeric",
                      month: "long",
                      day: "numeric",
                    })}
                  </dd>
                </div>
              )}
            </>
          )}
          {!subscription && (
            <div className="px-5 py-4">
              <Link
                href="/pricing"
                className="inline-flex items-center gap-2 text-sm font-medium text-amber-500 hover:text-amber-400 transition-colors"
              >
                <CreditCard className="h-4 w-4" />
                Upgrade plan
              </Link>
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
