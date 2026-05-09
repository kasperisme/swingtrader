"use client";

import { Sparkles } from "lucide-react";

import { openHelpChat } from "@/components/help-chat";
import { track } from "@/lib/analytics/events";
import { clearPostWelcomeHighlight } from "./onboarding-highlight";

/**
 * Persistent reminder rendered in place of the onboarding checklist when
 * the user has dismissed it or completed every step. Surfaces the Ask AI
 * button as the long-term answer to "where do I find X?" — the checklist
 * is for first-time orientation, the chat is for everything after.
 */
export function AskAiReminder() {
  return (
    <div className="rounded-lg border border-border/60 bg-muted/20 px-4 py-3 text-xs text-muted-foreground">
      <div className="flex items-center gap-2">
        <Sparkles className="h-3.5 w-3.5 shrink-0 text-amber-400" aria-hidden />
        <span>
          Looking for something on the platform?{" "}
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
          in the top bar — it knows the codebase, the data, and where every
          page lives.
        </span>
      </div>
    </div>
  );
}
