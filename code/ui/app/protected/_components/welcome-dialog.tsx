"use client";

import { useCallback, useEffect, useId, useState, useTransition } from "react";
import { AlertTriangle, ArrowLeft, ArrowRight, Sparkles } from "lucide-react";

import { markWelcomed } from "@/app/actions/onboarding";
import { SUPPORT_EMAIL, SUPPORT_NAME, supportMailto } from "@/lib/support";
import { track } from "@/lib/analytics/events";
import { setPostWelcomeHighlight } from "./onboarding-highlight";
import { SetupAssistantChat } from "@/components/setup-assistant";
import { OnboardingPlanStep } from "@/components/onboarding-plan-step";
import { LanguageSelector } from "@/components/language-selector";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

// Signed by a person — it is the only thing in the dialog that speaks as an
// individual rather than as the product.
const FOUNDER_SIGNATURE = "Kasper - Founder";

type Props = {
  displayName: string | null;
};

// The ordered welcome-dialog steps — drives the funnel's step_index.
// NOTE: the first step was "video" until the tutorial was replaced with a
// written welcome. Renamed so the event name matches what is on screen; PostHog
// funnels filtered on step="video" need updating to "welcome".
const STEP_ORDER = ["welcome", "setup", "plan"] as const;
const STEP_LABELS: Record<(typeof STEP_ORDER)[number], string> = {
  welcome: "Welcome",
  setup: "Set up",
  plan: "Plan",
};

/**
 * The stacked confirmation both leave-paths share.
 *
 * Rendered as a SIBLING of the welcome dialog, never nested inside it: a Dialog
 * mounted within an open Dialog inherits the outer focus trap, and the confirm's
 * own buttons then can't be reached from the keyboard.
 *
 * `primary` is always the action that keeps the user in onboarding, and it is
 * the only one styled as such — the ghost button is the way out. Both are real
 * buttons: a prompt that can only be answered one way is a wall, not a prompt.
 */
function ConfirmLeaveDialog({
  open,
  onOpenChange,
  title,
  children,
  dismissLabel,
  onDismiss,
  primaryLabel,
  onPrimary,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  children: React.ReactNode;
  dismissLabel: string;
  onDismiss: () => void;
  primaryLabel: string;
  onPrimary: () => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {/* Stacked on the welcome dialog, which already dims the page — a second
          full-strength scrim would double the darkening. */}
      <DialogContent
        className="sm:max-w-md"
        overlayClassName="bg-black/25 backdrop-blur-none"
      >
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <AlertTriangle className="h-5 w-5 shrink-0 text-amber-500" aria-hidden />
            {title}
          </DialogTitle>
          <DialogDescription className="pt-2">{children}</DialogDescription>
        </DialogHeader>
        <DialogFooter className="gap-2 sm:gap-2">
          <Button variant="ghost" className="min-h-11" onClick={onDismiss}>
            {dismissLabel}
          </Button>
          <Button className="min-h-11" onClick={onPrimary}>
            {primaryLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/**
 * Three dots + a label, so an open-ended AI interview doesn't feel like an
 * unbounded commitment — the user can see it's three steps and where they are.
 */
function StepIndicator({ step }: { step: (typeof STEP_ORDER)[number] }) {
  const index = STEP_ORDER.indexOf(step);
  return (
    <div
      className="flex items-center gap-2"
      aria-label={`Step ${index + 1} of ${STEP_ORDER.length}: ${STEP_LABELS[step]}`}
    >
      <div className="flex items-center gap-1" aria-hidden>
        {STEP_ORDER.map((s, i) => (
          <span
            key={s}
            className={`h-1 rounded-full transition-all duration-300 ${
              i === index
                ? "w-5 bg-amber-500"
                : i < index
                  ? "w-1.5 bg-amber-500/50"
                  : "w-1.5 bg-muted-foreground/25"
            }`}
          />
        ))}
      </div>
      <span className="font-mono text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
        {index + 1}/{STEP_ORDER.length} · {STEP_LABELS[step]}
      </span>
    </div>
  );
}

export function WelcomeDialog({ displayName }: Props) {
  const [open, setOpen] = useState(true);
  const [step, setStep] = useState<"welcome" | "setup" | "plan">("welcome");
  const [confirmingExit, setConfirmingExit] = useState(false);
  const [confirmingSkip, setConfirmingSkip] = useState(false);
  const [isPending, startTransition] = useTransition();
  // How many of the agent's 5 setup tasks have actually landed. Drives whether
  // advancing to billing reads as "continue" or as "skip".
  const [tasksDone, setTasksDone] = useState(0);
  const languageId = useId();

  const greetingName = displayName?.trim() || "trader";

  // First-join funnel: emit a step-view each time a step becomes visible, so
  // PostHog can chart where new users drop off (welcome → setup → plan). Fires
  // on mount (welcome) and on every step change; guarded by `open` so closing the
  // dialog doesn't emit.
  useEffect(() => {
    if (!open) return;
    track("onboarding_step_viewed", {
      step,
      step_index: STEP_ORDER.indexOf(step) + 1,
      step_count: STEP_ORDER.length,
    });
  }, [step, open]);

  // Persist "welcomed" so the dialog doesn't reappear. Idempotent.
  function persistWelcomed() {
    startTransition(async () => {
      await markWelcomed();
    });
  }

  // Asking to leave at the welcome note. Every later step already warns before
  // it closes; this one used to be the single exit that took the user at their
  // word on the first click — including a stray Escape or a click on the scrim,
  // neither of which is a decision. It now confirms like the rest.
  function requestSkip() {
    track("onboarding_skip_prompted", { step });
    setConfirmingSkip(true);
  }

  // Skip onboarding entirely — close and highlight the Ask AI buttons.
  // Only ever reached through `requestSkip`'s confirmation.
  function skip() {
    track("onboarding_completed", { skipped: true });
    setConfirmingSkip(false);
    setPostWelcomeHighlight();
    persistWelcomed();
    setOpen(false);
  }

  // Read (or skipped) the welcome note → continue into AI onboarding here.
  // NB: this is step 1 of 3, not the end of onboarding — `onboarding_completed`
  // used to fire here, which made the funnel report ~100% completion.
  function startSetup() {
    track("onboarding_welcome_accepted", {});
    setConfirmingSkip(false);
    persistWelcomed();
    setStep("setup");
  }

  // Backed out of the skip prompt without choosing the agent — they stay on the
  // welcome note. Tracked separately from `startSetup` so the funnel can tell a
  // prompt that recovered someone from one they simply dismissed.
  function cancelSkip() {
    track("onboarding_skip_cancelled", { step });
    setConfirmingSkip(false);
  }

  // Setup → billing. Records how much the agent actually configured, so the
  // drop-off between "set nothing up" and "set everything up" is visible.
  function goToPlan() {
    track("onboarding_completed", { skipped: tasksDone === 0 });
    setStep("plan");
  }

  // Stable identity — SetupAssistantChat calls this from an effect.
  const handleProgress = useCallback((count: number) => {
    setTasksDone(count);
  }, []);

  // Confirmed they want to leave without setting up billing — close for good.
  function leaveAnyway() {
    track("onboarding_exit_without_billing", {});
    setConfirmingExit(false);
    setOpen(false);
  }

  // From the confirm box: go (back) to the plan/billing step instead of leaving.
  function goToBilling() {
    setConfirmingExit(false);
    setStep("plan");
  }

  function handleOpenChange(next: boolean) {
    if (next) return;
    // Nothing is configured yet at the welcome note, so there is nothing to
    // lose but the setup itself — which is the whole reason to ask.
    if (step === "welcome") {
      requestSkip();
      return;
    }
    // They've built a setup but haven't set up billing. Warn before leaving:
    // without a paid plan their agents won't run and they're limited to the
    // free Observer tier.
    setConfirmingExit(true);
  }

  return (
    <>
    <Dialog open={open} onOpenChange={handleOpenChange}>
      {/* Full-screen sheet below `sm` — this is the longest dialog in the
          product and a chat + composer does not fit in a centred modal on a
          phone. `dvh` (not `vh`) so mobile browser chrome can't push the
          composer and footer out of the visible viewport. */}
      <DialogContent
        className={
          step === "setup"
            ? "flex h-[100dvh] max-h-[100dvh] flex-col gap-4 overflow-hidden rounded-none p-4 sm:h-[85dvh] sm:max-w-2xl sm:rounded-lg sm:p-6"
            : step === "plan"
              ? "flex h-[100dvh] max-h-[100dvh] flex-col gap-4 overflow-hidden rounded-none p-4 sm:h-auto sm:max-h-[88dvh] sm:max-w-2xl sm:rounded-lg sm:p-6"
              : "max-h-[100dvh] overflow-y-auto p-4 sm:max-h-[90dvh] sm:max-w-xl sm:p-6"
        }
      >
        {step === "welcome" ? (
          <>
            <DialogHeader>
              <StepIndicator step={step} />
              <DialogTitle className="pt-3 text-2xl tracking-tight">
                Welcome, {greetingName}.
              </DialogTitle>
              <DialogDescription className="pt-2 text-base">
                News Impact Screener turns headlines into trade ideas.
              </DialogDescription>
            </DialogHeader>

            {/* A note in one voice, not the product's. The accent rail keeps it
                reading as a letter rather than another panel of UI copy. */}
            <div className="border-l-2 border-amber-500/60 pl-5">
              <p className="text-[15px] leading-relaxed text-foreground">
                Thanks for being here — genuinely. I built this because I wanted
                one place that connects the news to the stocks it actually moves,
                and it means a lot that you&apos;re trying it.
              </p>
              <p className="mt-3 text-[15px] leading-relaxed text-foreground">
                You don&apos;t have to work it out on your own. From here the
                onboarding agent takes over — it walks you through the rest of the
                setup and builds your first one with you. Just answer along.
              </p>
              {/* The invitation sits inside the letter, in the founder's voice,
                  because that is what makes it credible — the same sentence in a
                  grey support strip below reads as a ticket queue. */}
              <p className="mt-3 text-[15px] leading-relaxed text-foreground">
                And please write to me. If something is confusing, broken, or
                missing — or you just want a feature — email me directly at{" "}
                <a
                  href={supportMailto(
                    "News Impact Screener — feedback",
                    "onboarding / welcome",
                  )}
                  className="font-medium text-amber-500 underline underline-offset-4 hover:text-amber-400"
                >
                  {SUPPORT_EMAIL}
                </a>
                . It comes straight to me and I read every one.
              </p>
              <p className="mt-4 font-mono text-xs uppercase tracking-[0.2em] text-muted-foreground">
                {FOUNDER_SIGNATURE}
              </p>
            </div>

            {/* A divider, not another boxed panel — the letter above is the
                only thing on this screen that should read as a surface. */}
            <div className="flex flex-col gap-1.5 border-t border-border pt-4">
              <div className="flex items-center justify-between gap-3">
                <label
                  htmlFor={languageId}
                  className="text-sm font-medium text-foreground"
                >
                  Language
                </label>
                <LanguageSelector id={languageId} className="w-44 shrink-0" />
              </div>
              <p className="text-xs text-muted-foreground">
                Your agent alerts and Telegram messages will be delivered in this language.
              </p>
            </div>

            <DialogFooter className="gap-2 sm:gap-2">
              <Button
                variant="ghost"
                className="min-h-11"
                onClick={requestSkip}
                disabled={isPending}
              >
                Skip for now
              </Button>
              <Button className="min-h-11" onClick={startSetup} disabled={isPending}>
                Set up my account
                <ArrowRight className="ml-1.5 h-4 w-4" />
              </Button>
            </DialogFooter>
          </>
        ) : step === "setup" ? (
          <>
            <DialogHeader className="shrink-0">
              <StepIndicator step={step} />
              <DialogTitle className="flex items-center gap-2 pt-3 text-xl tracking-tight">
                <Sparkles className="h-4 w-4 shrink-0 text-amber-500" aria-hidden />
                Let&apos;s get you set up
              </DialogTitle>
              <DialogDescription>
                Answer along and I&apos;ll configure your strategy, screenings,
                Telegram, holdings, and first agent for you.
              </DialogDescription>
            </DialogHeader>

            <SetupAssistantChat
              className="min-h-0 flex-1"
              surface="welcome"
              onProgress={handleProgress}
            />

            {/* The step where people actually get stuck, so the human is offered
                here too — the letter on step 1 has usually scrolled out of mind
                by the time the agent misunderstands something. */}
            <p className="shrink-0 text-xs leading-5 text-muted-foreground">
              Agent not getting it, or something looks wrong?{" "}
              <a
                href={supportMailto(
                  "News Impact Screener — help with setup",
                  "onboarding / setup step",
                )}
                className="font-medium text-amber-500 underline underline-offset-4 hover:text-amber-400"
              >
                Email {SUPPORT_NAME} directly
              </a>{" "}
              — {SUPPORT_EMAIL}.
            </p>

            {/* Advancing with nothing configured is leaving, not continuing —
                so it isn't dressed as the primary action until the agent has
                actually written something. */}
            <DialogFooter className="shrink-0 sm:justify-between">
              <Button
                variant="ghost"
                className="min-h-11"
                onClick={() => setStep("welcome")}
              >
                <ArrowLeft className="mr-1.5 h-4 w-4" />
                Back
              </Button>
              <Button
                variant={tasksDone === 0 ? "outline" : "default"}
                className="min-h-11"
                onClick={goToPlan}
              >
                {tasksDone === 0 ? "Skip to plans" : "Continue"}
                <ArrowRight className="ml-1.5 h-4 w-4" />
              </Button>
            </DialogFooter>
          </>
        ) : (
          <>
            <DialogHeader className="shrink-0">
              <StepIndicator step={step} />
              <DialogTitle className="flex items-center gap-2 pt-3 text-xl tracking-tight">
                <Sparkles className="h-4 w-4 shrink-0 text-amber-500" aria-hidden />
                Choose your plan
              </DialogTitle>
              <DialogDescription>
                Pick the plan that supports the setup you just built. You can
                change or cancel anytime.
              </DialogDescription>
            </DialogHeader>

            <OnboardingPlanStep
              onBack={() => setStep("setup")}
              onClose={() => setConfirmingExit(true)}
            />
          </>
        )}
      </DialogContent>
    </Dialog>

      {/* Skip-the-setup confirmation — the welcome note's only exit. */}
      <ConfirmLeaveDialog
        open={confirmingSkip}
        onOpenChange={(o) => {
          if (!o) cancelSkip();
        }}
        title="Skip the setup?"
        dismissLabel="Skip anyway"
        onDismiss={skip}
        primaryLabel="Set up my account"
        onPrimary={startSetup}
      >
        It takes a couple of minutes: the agent configures your{" "}
        <span className="font-medium text-foreground">
          strategy, screenings, Telegram alerts, holdings and your first agent
        </span>{" "}
        by asking you a few questions. Skip and you start from an empty account
        and set each one up by hand. You can restart it any time from the Ask AI
        banner.
      </ConfirmLeaveDialog>

      {/* Exit-without-billing confirmation */}
      <ConfirmLeaveDialog
        open={confirmingExit}
        onOpenChange={(o) => {
          if (!o) setConfirmingExit(false);
        }}
        title="Leave without setting up billing?"
        dismissLabel="Leave anyway"
        onDismiss={leaveAnyway}
        primaryLabel="Set up billing"
        onPrimary={goToBilling}
      >
        Without an active plan your scheduled agents won&apos;t run — they&apos;ll
        only send a reminder to set up billing — and you&apos;ll be limited to the
        free <span className="font-medium text-foreground">Observer</span> tier.
        Set up billing now to keep everything you just configured. You can always
        do it later from your profile.
      </ConfirmLeaveDialog>
    </>
  );
}
