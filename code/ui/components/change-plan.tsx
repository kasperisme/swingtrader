"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { CalendarClock, Check, Loader2 } from "lucide-react";
import { UpgradeButton } from "@/components/upgrade-button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { track } from "@/lib/analytics/events";
import { PAID_PLAN_COPY } from "@/lib/plans";

type Plan = "investor" | "trader";
type Interval = "monthly" | "annual";
type Timing = "immediate" | "period_end";

interface Option {
  plan: Plan;
  interval: Interval;
  priceId: string;
  unitAmount: number | null;
  currency: string;
  current: boolean;
  timing: Timing | null;
}

interface Pending {
  plan: Plan;
  interval: Interval;
  effectiveAt: string | null;
}

interface ChangePlanInfo {
  /** `checkout` — nothing to switch, buy one of these prices. `change` — switch in place. */
  mode: "checkout" | "change";
  options: Option[];
  current: {
    plan: Plan;
    interval: Interval;
    status: string;
    cancelAtPeriodEnd: boolean;
    currentPeriodEnd: string | null;
  } | null;
  pending: Pending | null;
  changeable: boolean;
  reason: string | null;
}

const PLANS: Plan[] = ["investor", "trader"];
const PLAN_LABEL: Record<Plan, string> = { investor: "Investor", trader: "Trader" };

function formatMoney(amount: number, currency: string, fractionDigits?: number): string {
  const value = amount / 100;
  const digits = fractionDigits ?? (Number.isInteger(value) ? 0 : 2);
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: currency.toUpperCase(),
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value);
}

function formatPrice(amount: number | null, currency: string, interval: Interval): string {
  if (amount == null) return "—";
  return `${formatMoney(amount, currency)}/${interval === "annual" ? "yr" : "mo"}`;
}

function formatDate(iso: string | null): string {
  if (!iso) return "the next renewal";
  return new Date(iso).toLocaleDateString("en-US", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

function describe(option: Option): string {
  return `${PLAN_LABEL[option.plan]} · ${option.interval === "annual" ? "annual" : "monthly"}`;
}

/** What a year of the annual price saves against twelve monthly charges. */
function annualSaving(
  monthly: Option | undefined,
  annual: Option | undefined,
): { amount: number; percent: number; currency: string } | null {
  if (!monthly?.unitAmount || !annual?.unitAmount) return null;
  const twelveMonths = monthly.unitAmount * 12;
  const saved = twelveMonths - annual.unitAmount;
  if (saved <= 0) return null;
  return {
    amount: saved,
    percent: Math.round((saved / twelveMonths) * 100),
    currency: annual.currency,
  };
}

const BLOCKED_REASON: Record<string, string> = {
  canceling:
    "Your subscription is set to cancel at the end of the period. Resume it in Manage billing to change plan.",
  status_past_due:
    "Your last payment failed. Update your card in Manage billing, then you can change plan.",
};

/**
 * Plan picker on the profile page, in one of two modes the API decides:
 *
 * - **checkout** (free, or a lapsed subscription) — the same prices, bought
 *   through Stripe Checkout.
 * - **change** (live subscription) — switch in place. Upgrades take effect at
 *   once (Stripe prorates); downgrades are scheduled for the next renewal and
 *   stay cancellable until they land.
 *
 * Presented as one card per product with a yearly/monthly switch, yearly first
 * and its saving against twelve monthly charges spelled out.
 *
 * `hasSubscription` is what the server already knows, used only to pick a sane
 * fallback if the fetch fails — a free user must never be left without a way to pay.
 */
export function ChangePlan({ hasSubscription = false }: { hasSubscription?: boolean }) {
  const router = useRouter();
  const [info, setInfo] = useState<ChangePlanInfo | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  // Yearly leads — it's the better deal and the better retention.
  const [interval, setIntervalChoice] = useState<Interval>("annual");
  const [target, setTarget] = useState<Option | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await fetch("/api/stripe/change-plan");
      if (!res.ok) {
        setLoadFailed(true);
        return;
      }
      setInfo((await res.json()) as ChangePlanInfo);
    } catch {
      setLoadFailed(true);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  /** No subscription to modify — send them to Stripe Checkout for the chosen price. */
  async function startCheckout(option: Option) {
    setBusy(true);
    setError(null);
    track("upgrade_clicked", {
      from_plan: info?.current?.plan ?? "observer",
      to_plan: option.plan,
      surface: "profile_plan_grid",
    });
    try {
      const res = await fetch("/api/stripe/checkout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ plan: option.plan, interval: option.interval }),
      });
      const data = (await res.json()) as { url?: string; error?: string };
      if (data.url) {
        window.location.href = data.url; // → Stripe Checkout
        return;
      }
      setError(data.error ?? "Could not start checkout.");
      setBusy(false);
    } catch {
      setError("Could not reach Stripe. Try again in a moment.");
      setBusy(false);
    }
  }

  async function confirm() {
    if (!target || !info?.current) return;
    setBusy(true);
    setError(null);
    track("plan_change_requested", {
      from_plan: info.current.plan,
      from_interval: info.current.interval,
      to_plan: target.plan,
      to_interval: target.interval,
      timing: target.timing ?? "immediate",
    });
    try {
      const res = await fetch("/api/stripe/change-plan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ plan: target.plan, interval: target.interval }),
      });
      const data = (await res.json()) as {
        error?: string;
        timing?: Timing;
        effectiveAt?: string | null;
      };
      if (!res.ok) {
        setError(data.error ?? "Could not change plan.");
        return;
      }
      setNotice(
        data.timing === "period_end"
          ? `Scheduled — you move to ${describe(target)} on ${formatDate(data.effectiveAt ?? null)}.`
          : `You're on ${describe(target)}.`,
      );
      setTarget(null);
      await load();
      router.refresh();
    } catch {
      setError("Could not reach Stripe. Try again in a moment.");
    } finally {
      setBusy(false);
    }
  }

  async function cancelScheduled() {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch("/api/stripe/change-plan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "cancel_scheduled" }),
      });
      const data = (await res.json()) as { error?: string };
      if (!res.ok) {
        setError(data.error ?? "Could not cancel the scheduled change.");
        return;
      }
      track("plan_change_canceled");
      setNotice("Scheduled change cancelled — you stay on your current plan.");
      await load();
      router.refresh();
    } catch {
      setError("Could not reach Stripe. Try again in a moment.");
    } finally {
      setBusy(false);
    }
  }

  // Never strand a free user without a way to subscribe if the catalogue fetch
  // fails — fall back to the plain checkout button.
  if (loadFailed) {
    return hasSubscription ? null : (
      <div className="px-5 py-4">
        <UpgradeButton />
      </div>
    );
  }

  if (!info) {
    return <div className="px-5 py-4 text-xs text-muted-foreground">Loading plans…</div>;
  }

  const checkoutMode = info.mode === "checkout";
  const blocked = !checkoutMode && !info.changeable;

  const find = (plan: Plan, iv: Interval) =>
    info.options.find((o) => o.plan === plan && o.interval === iv);

  // Headline saving for the toggle hint — the best deal on offer.
  const bestSavingPercent = Math.max(
    0,
    ...PLANS.map((p) => annualSaving(find(p, "monthly"), find(p, "annual"))?.percent ?? 0),
  );

  return (
    <div className="flex flex-col gap-3 px-5 py-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-sm font-medium">{checkoutMode ? "Choose a plan" : "Change plan"}</p>
          <p className="text-xs text-muted-foreground">
            {checkoutMode
              ? "Cancel anytime"
              : "Upgrades apply now · downgrades at renewal"}
          </p>
        </div>

        {!blocked && (
          <div className="flex items-center gap-2">
            {interval === "annual" && bestSavingPercent > 0 && (
              <span className="font-mono text-[10px] font-semibold uppercase tracking-[0.1em] text-emerald-600 dark:text-emerald-400">
                Save {bestSavingPercent}%
              </span>
            )}
            <div className="inline-flex rounded-lg border border-border p-0.5">
              {(["annual", "monthly"] as Interval[]).map((iv) => (
                <button
                  key={iv}
                  onClick={() => setIntervalChoice(iv)}
                  className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                    interval === iv
                      ? "bg-amber-500 text-black"
                      : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {iv === "annual" ? "Yearly" : "Monthly"}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      {info.pending && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2">
          <p className="flex items-center gap-2 text-xs text-amber-600 dark:text-amber-400">
            <CalendarClock className="h-3.5 w-3.5 shrink-0" />
            Switching to {PLAN_LABEL[info.pending.plan]} ({info.pending.interval}) on{" "}
            {formatDate(info.pending.effectiveAt)}
          </p>
          <button
            onClick={cancelScheduled}
            disabled={busy}
            className="text-xs font-medium text-muted-foreground underline underline-offset-2 transition-colors hover:text-foreground disabled:opacity-60"
          >
            Cancel change
          </button>
        </div>
      )}

      {blocked ? (
        <p className="text-xs text-muted-foreground">
          {BLOCKED_REASON[info.reason ?? ""] ??
            "Plan changes aren't available for this subscription right now."}
        </p>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          {PLANS.map((plan) => {
            const option = find(plan, interval);
            if (!option) return null;

            const monthlyOption = find(plan, "monthly");
            const saving = annualSaving(monthlyOption, find(plan, "annual"));
            const copy = PAID_PLAN_COPY[plan];
            const isCurrentTier = info.current?.plan === plan;
            const isCurrentExactly = option.current;

            return (
              <div
                key={plan}
                className={`flex flex-col gap-3 rounded-xl border p-4 transition-colors ${
                  isCurrentExactly
                    ? "border-amber-500/40 bg-amber-500/5"
                    : "border-border bg-background"
                }`}
              >
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <p className="text-sm font-semibold">{PLAN_LABEL[plan]}</p>
                    <p className="text-[11px] text-muted-foreground">{copy.tagline}</p>
                  </div>
                  {isCurrentExactly ? (
                    <span className="flex shrink-0 items-center gap-1 font-mono text-[10px] font-semibold uppercase tracking-[0.1em] text-amber-600 dark:text-amber-400">
                      <Check className="h-3 w-3" />
                      Current
                    </span>
                  ) : (
                    isCurrentTier && (
                      <span className="shrink-0 font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
                        Your tier
                      </span>
                    )
                  )}
                </div>

                <div>
                  <p className="font-mono text-xl font-semibold tabular-nums">
                    {formatPrice(option.unitAmount, option.currency, option.interval)}
                  </p>
                  {interval === "annual" && option.unitAmount != null ? (
                    <p className="text-[11px] text-muted-foreground">
                      {formatMoney(option.unitAmount / 12, option.currency, 2)}/mo, billed yearly
                    </p>
                  ) : (
                    <p className="text-[11px] text-muted-foreground">billed monthly</p>
                  )}
                  {interval === "annual" && saving && (
                    <p className="mt-1 text-[11px] font-medium text-emerald-600 dark:text-emerald-400">
                      Save {formatMoney(saving.amount, saving.currency)} a year vs monthly (
                      {saving.percent}%)
                    </p>
                  )}
                  {interval === "monthly" && saving && (
                    <p className="mt-1 text-[11px] text-muted-foreground">
                      {formatMoney(saving.amount, saving.currency)} more per year than yearly
                    </p>
                  )}
                </div>

                <ul className="flex flex-col gap-1.5">
                  {copy.features.map((feature) => (
                    <li key={feature} className="flex items-start gap-2 text-xs text-muted-foreground">
                      <Check className="mt-0.5 h-3 w-3 shrink-0 text-amber-500" />
                      <span>{feature}</span>
                    </li>
                  ))}
                </ul>

                <button
                  onClick={() => {
                    setNotice(null);
                    if (checkoutMode) {
                      void startCheckout(option);
                    } else {
                      setTarget(option);
                    }
                  }}
                  disabled={isCurrentExactly || busy}
                  className={`mt-auto rounded-lg px-3.5 py-2 text-sm font-semibold transition-colors disabled:cursor-default disabled:opacity-60 ${
                    isCurrentExactly
                      ? "border border-border bg-transparent text-muted-foreground"
                      : plan === "trader"
                        ? "bg-amber-500 text-black hover:bg-amber-400"
                        : "border border-border hover:bg-muted"
                  }`}
                >
                  {isCurrentExactly
                    ? "Current plan"
                    : checkoutMode
                      ? `Choose ${PLAN_LABEL[plan]}`
                      : isCurrentTier
                        ? `Switch to ${interval === "annual" ? "yearly" : "monthly"}`
                        : `Switch to ${PLAN_LABEL[plan]}`}
                </button>
              </div>
            );
          })}
        </div>
      )}

      {checkoutMode && !blocked && (
        <div className="flex items-center justify-between gap-3">
          <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
            {busy && <Loader2 className="h-3 w-3 animate-spin" />}
            {busy ? "Redirecting to Stripe…" : "Secure checkout via Stripe"}
          </p>
          <Link
            href="/pricing"
            className="text-xs font-medium text-muted-foreground transition-colors hover:text-foreground"
          >
            Compare plans →
          </Link>
        </div>
      )}

      {notice && <p className="text-xs text-emerald-600 dark:text-emerald-400">{notice}</p>}
      {error && !target && <p className="text-xs text-destructive">{error}</p>}

      <Dialog
        open={target !== null}
        onOpenChange={(open) => {
          if (!open && !busy) {
            setTarget(null);
            setError(null);
          }
        }}
      >
        <DialogContent className="max-w-md">
          {target && info.current && (
            <>
              <DialogHeader>
                <DialogTitle>Switch to {describe(target)}?</DialogTitle>
                <DialogDescription>
                  {target.timing === "period_end" ? (
                    <>
                      You keep {PLAN_LABEL[info.current.plan]} ({info.current.interval})
                      until {formatDate(info.current.currentPeriodEnd)}. On that date your
                      subscription renews at{" "}
                      {formatPrice(target.unitAmount, target.currency, target.interval)} on{" "}
                      {describe(target)}. Nothing is charged today.
                    </>
                  ) : info.current.status === "trialing" ? (
                    <>
                      Your plan switches now and your trial keeps running. When the trial
                      ends you&apos;ll be billed{" "}
                      {formatPrice(target.unitAmount, target.currency, target.interval)}.
                    </>
                  ) : (
                    <>
                      Your plan switches now. Stripe charges the prorated difference for the
                      rest of this period today, then{" "}
                      {formatPrice(target.unitAmount, target.currency, target.interval)}{" "}
                      going forward.
                    </>
                  )}
                </DialogDescription>
              </DialogHeader>

              {error && <p className="text-xs text-destructive">{error}</p>}

              <DialogFooter className="gap-2">
                <button
                  onClick={() => setTarget(null)}
                  disabled={busy}
                  className="rounded-lg border border-border px-3.5 py-2 text-sm font-medium transition-colors hover:bg-muted disabled:opacity-60"
                >
                  Keep current plan
                </button>
                <button
                  onClick={confirm}
                  disabled={busy}
                  className="inline-flex items-center justify-center gap-2 rounded-lg bg-amber-500 px-3.5 py-2 text-sm font-semibold text-black transition-colors hover:bg-amber-400 disabled:opacity-60"
                >
                  {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                  {target.timing === "period_end" ? "Schedule change" : "Confirm change"}
                </button>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
