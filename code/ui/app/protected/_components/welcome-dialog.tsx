"use client";

import { useState, useTransition } from "react";
import { PlayCircle } from "lucide-react";

import { markWelcomed } from "@/app/actions/onboarding";
import { track } from "@/lib/analytics/events";
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

const TUTORIAL_VIDEO_EMBED_URL = process.env.NEXT_PUBLIC_TUTORIAL_VIDEO_URL ?? null;

type Props = {
  displayName: string | null;
};

export function WelcomeDialog({ displayName }: Props) {
  const [open, setOpen] = useState(true);
  const [showVideo, setShowVideo] = useState(false);
  const [isPending, startTransition] = useTransition();

  const greetingName = displayName?.trim() || "trader";

  function dismiss(skipped = false) {
    setOpen(false);
    track("onboarding_completed", { skipped });
    // Persist in the background; the dialog stays closed even if this fails
    // (worst case: user sees it again on next navigation).
    startTransition(async () => {
      await markWelcomed();
    });
  }

  function watchTutorial() {
    if (TUTORIAL_VIDEO_EMBED_URL) {
      setShowVideo(true);
    } else {
      window.open(TUTORIAL_PLAYLIST_URL, "_blank", "noopener,noreferrer");
    }
  }

  return (
    <Dialog open={open} onOpenChange={(next) => { if (!next) dismiss(true); }}>
      <DialogContent className="sm:max-w-xl">
        {!showVideo ? (
          <>
            <DialogHeader>
              <DialogTitle className="text-2xl">Welcome, {greetingName}.</DialogTitle>
              <DialogDescription className="pt-2 text-base">
                News Impact Screener turns headlines into trade ideas. The 90-second tutorial
                walks you through the screener, the news feed, and how to save an entry.
              </DialogDescription>
            </DialogHeader>

            <div className="rounded-lg border bg-muted/40 p-4 text-sm text-muted-foreground">
              <p className="font-medium text-foreground">Quick start</p>
              <ul className="mt-2 list-disc space-y-1 pl-5">
                <li>Pick a watchlist or run a fresh screen</li>
                <li>Click any ticker to open the chart + AI analysis</li>
                <li>Save an entry marker to track the trade</li>
              </ul>
            </div>

            <DialogFooter className="gap-2 sm:gap-2">
              <Button variant="ghost" onClick={() => dismiss(true)} disabled={isPending}>
                Skip for now
              </Button>
              <Button onClick={watchTutorial}>
                <PlayCircle className="mr-2 h-4 w-4" />
                Watch tutorial
              </Button>
            </DialogFooter>
          </>
        ) : (
          <>
            <DialogHeader>
              <DialogTitle>Tutorial</DialogTitle>
            </DialogHeader>
            <div className="aspect-video w-full overflow-hidden rounded-lg bg-black">
              <iframe
                src={TUTORIAL_VIDEO_EMBED_URL ?? ""}
                title="News Impact Screener tutorial"
                allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                allowFullScreen
                className="h-full w-full"
              />
            </div>
            <DialogFooter>
              <Button onClick={() => dismiss(false)} disabled={isPending}>
                Got it
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
