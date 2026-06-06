"use client";

import { useState, useTransition } from "react";
import { ArrowRight, PlayCircle, Sparkles } from "lucide-react";

import { markWelcomed } from "@/app/actions/onboarding";
import { track } from "@/lib/analytics/events";
import { setPostWelcomeHighlight } from "./onboarding-highlight";
import { SetupAssistantChat } from "@/components/setup-assistant";
import { OnboardingPlanStep } from "@/components/onboarding-plan-step";
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

export function WelcomeDialog({ displayName }: Props) {
  const [open, setOpen] = useState(true);
  const [step, setStep] = useState<"video" | "setup" | "plan">("video");
  const [isPending, startTransition] = useTransition();

  const greetingName = displayName?.trim() || "trader";

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

  // Closing while on the setup step (X / overlay / Finish) — already welcomed.
  function finishSetup() {
    setOpen(false);
  }

  function handleOpenChange(next: boolean) {
    if (next) return;
    if (step === "video") skip();
    else finishSetup();
  }

  return (
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

            <SetupAssistantChat className="min-h-0 flex-1" />

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
              onClose={finishSetup}
            />
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
