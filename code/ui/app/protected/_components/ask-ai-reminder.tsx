"use client";

import { Sparkles } from "lucide-react";

import { openHelpChat } from "@/components/help-chat";
import { track } from "@/lib/analytics/events";
import { clearPostWelcomeHighlight } from "./onboarding-highlight";

/**
 * Persistent Ask AI prompt rendered at the top of the dashboard. It replaces
 * the old step-by-step onboarding checklist: the chat is the single entry
 * point for both orientation ("where do I find X?") and getting set up — it can
 * configure the user's strategy, screenings, Telegram, and agents directly.
 */
export function AskAiReminder() {
  return (
    <div
      data-tour="onboarding-checklist"
      className="rounded-lg border border-border/60 bg-muted/20 px-4 py-3 text-xs text-muted-foreground"
    >
      <div className="flex items-center gap-2">
        <Sparkles className="h-3.5 w-3.5 shrink-0 text-amber-400" aria-hidden />
        <span>
          Need to find something or set up your account?{" "}
          <button
            type="button"
            onClick={() => {
              track("ask_ai_reminder_clicked", {});
              clearPostWelcomeHighlight();
              openHelpChat();
            }}
            className="font-medium text-foreground underline-offset-2 hover:underline"
          >
            Ask AI
          </button>{" "}
          in the top bar — it knows where every page lives and can set up your
          strategy, screenings, Telegram, and agents for you.
        </span>
      </div>
    </div>
  );
}
