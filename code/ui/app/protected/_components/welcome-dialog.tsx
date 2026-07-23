"use client";

import { useEffect, useState, useTransition } from "react";
import { AlertTriangle, ArrowRight, PlayCircle, Sparkles } from "lucide-react";

import { markWelcomed } from "@/app/actions/onboarding";
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

const TUTORIAL_PLAYLIST_URL =
  process.env.NEXT_PUBLIC_TUTORIAL_PLAYLIST_URL ?? "https://www.youtube.com/@newsimpactscreener";

// The welcome tutorial is hosted in Supabase Storage. Override with a full URL
// via NEXT_PUBLIC_TUTORIAL_VIDEO_URL; otherwise fall back to the conventional
// public object path in the project's storage bucket.
const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL ?? "";
const TUTORIAL_VIDEO_URL =
  process.env.NEXT_PUBLIC_TUTORIAL_VIDEO_URL ??
  (SUPABASE_URL
    ? `${SUPABASE_URL}/storage/v1/object/public/tutorials/welcome.mp4`
    : null);

type Props = {
  displayName: string | null;
};

// The ordered welcome-dialog steps — drives the funnel's step_index.
const STEP_ORDER = ["video", "setup", "plan"] as const;

export function WelcomeDialog({ displayName }: Props) {
  const [open, setOpen] = useState(true);
  const [step, setStep] = useState<"video" | "setup" | "plan">("video");
  const [confirmingExit, setConfirmingExit] = useState(false);
  const [isPending, startTransition] = useTransition();

  const greetingName = displayName?.trim() || "trader";

  // First-join funnel: emit a step-view each time a step becomes visible, so
  // PostHog can chart where new users drop off (video → setup → plan). Fires on
  // mount (video) and on every step change; guarded by `open` so closing the
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

  // Skip the tutorial entirely — close and highlight the Ask AI buttons.
  function skip() {
    track("onboarding_completed", { skipped: true });
    setPostWelcomeHighlight();
    persistWelcomed();
    setOpen(false);
  }

  // Watched (or skipped) the video → continue into AI onboarding in this dialog.
  function startSetup() {
    track("onboarding_completed", { skipped: false });
    persistWelcomed();
    setStep("setup");
  }

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
    // Skipping the tutorial up front is fine — nothing has been configured yet.
    if (step === "video") {
      skip();
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
      <DialogContent
        className={
          step === "setup"
            ? "flex h-[85vh] flex-col gap-4 overflow-hidden sm:max-w-2xl"
            : step === "plan"
              ? "flex max-h-[88vh] flex-col gap-4 overflow-hidden sm:max-w-2xl"
              : "sm:max-w-xl"
        }
      >
        {step === "video" ? (
          <>
            <DialogHeader>
              <DialogTitle className="text-2xl">Welcome, {greetingName}.</DialogTitle>
              <DialogDescription className="pt-2 text-base">
                News Impact Screener turns headlines into trade ideas. Watch the
                90-second tour of the screener, the news feed, and how to save an entry.
              </DialogDescription>
            </DialogHeader>

            {TUTORIAL_VIDEO_URL ? (
              <div className="aspect-video w-full overflow-hidden rounded-lg bg-black">
                <video
                  src={TUTORIAL_VIDEO_URL}
                  controls
                  autoPlay
                  playsInline
                  className="h-full w-full"
                >
                  <track kind="captions" />
                </video>
              </div>
            ) : (
              <div className="flex aspect-video w-full items-center justify-center rounded-lg border bg-muted/40">
                <Button asChild variant="outline">
                  <a href={TUTORIAL_PLAYLIST_URL} target="_blank" rel="noopener noreferrer">
                    <PlayCircle className="mr-2 h-4 w-4" />
                    Watch on YouTube
                  </a>
                </Button>
              </div>
            )}

            <div className="flex flex-col gap-1.5 rounded-lg border border-border bg-muted/30 px-4 py-3">
              <div className="flex items-center justify-between gap-3">
                <span className="text-sm font-medium text-foreground">Language</span>
                <LanguageSelector className="w-44 shrink-0" />
              </div>
              <p className="text-xs text-muted-foreground">
                Your agent alerts and Telegram messages will be delivered in this language.
              </p>
            </div>

            <DialogFooter className="gap-2 sm:gap-2">
              <Button variant="ghost" onClick={skip} disabled={isPending}>
                Skip for now
              </Button>
              <Button onClick={startSetup} disabled={isPending}>
                Set up my account
              </Button>
            </DialogFooter>
          </>
        ) : step === "setup" ? (
          <>
            <DialogHeader className="shrink-0">
              <DialogTitle className="flex items-center gap-2 text-xl">
                <Sparkles className="h-4 w-4 text-amber-500" />
                Let&apos;s get you set up
              </DialogTitle>
              <DialogDescription>
                Answer along and I&apos;ll configure your strategy, screenings,
                Telegram, holdings, and first agent for you.
              </DialogDescription>
            </DialogHeader>

            <SetupAssistantChat className="min-h-0 flex-1" surface="welcome" />

            <DialogFooter className="shrink-0">
              <Button onClick={() => setStep("plan")}>
                Next
                <ArrowRight className="ml-1.5 h-4 w-4" />
              </Button>
            </DialogFooter>
          </>
        ) : (
          <>
            <DialogHeader className="shrink-0">
              <DialogTitle className="flex items-center gap-2 text-xl">
                <Sparkles className="h-4 w-4 text-amber-500" />
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

      {/* Exit-without-billing confirmation */}
      <Dialog
        open={confirmingExit}
        onOpenChange={(o) => {
          if (!o) setConfirmingExit(false);
        }}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <AlertTriangle className="h-5 w-5 text-amber-500" />
              Leave without setting up billing?
            </DialogTitle>
            <DialogDescription className="pt-2">
              Without an active plan your scheduled agents won&apos;t run — they&apos;ll
              only send a reminder to set up billing — and you&apos;ll be limited to
              the free <span className="font-medium text-foreground">Observer</span>{" "}
              tier. Set up billing now to keep everything you just configured. You
              can always do it later from your profile.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="gap-2 sm:gap-2">
            <Button variant="ghost" onClick={leaveAnyway}>
              Leave anyway
            </Button>
            <Button onClick={goToBilling}>Set up billing</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
