"use client";

import { useEffect, useMemo, useState, useTransition } from "react";
import Link from "next/link";
import {
  Check,
  X,
  Sparkles,
  ArrowRight,
  ChevronDown,
  ChevronUp,
  ChevronLeft,
  ChevronRight,
  RotateCcw,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { track } from "@/lib/analytics/events";
import {
  dismissOnboardingChecklist,
  markOnboardingVisited,
  restartOnboardingChecklist,
  type OnboardingProgress,
  type OnboardingStepKey,
  type VisitStepKey,
} from "@/app/actions/onboarding";
import {
  clearPostWelcomeHighlight,
  usePostWelcomeHighlight,
} from "./onboarding-highlight";
import { AskAiReminder } from "./ask-ai-reminder";

type Step = {
  key: OnboardingStepKey;
  group: "Setup" | "Research" | "Operations";
  title: string;
  description: string;
  href: string;
  cta: string;
  visitKey?: VisitStepKey;
};

const STEPS: ReadonlyArray<Step> = [
  {
    key: "profile",
    group: "Setup",
    title: "Set up your profile, strategy & Telegram",
    description:
      "Tell the platform your trading style and connect Telegram. Your strategy is the lens every screen and AI agent uses to score ideas — without it, the system grades every ticker the same. Telegram is how alerts and agent triggers reach you when you're not on the site.",
    href: "/protected/profile",
    cta: "Open profile",
    visitKey: "profile",
  },
  {
    key: "articles",
    group: "Research",
    title: "Learn how news gets scored",
    description:
      "Every headline is broken down across multiple dimensions — sentiment, novelty, magnitude, and ticker relevance — and combined into an impact score. Knowing how the score is built means you can trust (or override) it instead of treating it as a black box.",
    href: "/protected/articles",
    cta: "Open articles",
    visitKey: "articles",
  },
  {
    key: "news_trends",
    group: "Research",
    title: "Zoom out to news trends",
    description:
      "The same dimensions that score a single article also cluster across the day's news. News Trends shows which themes are accumulating impact — so you stop reacting to one headline and start reading the regime the market is in.",
    href: "/protected/news-trends",
    cta: "Open trends",
    visitKey: "news_trends",
  },
  {
    key: "relations",
    group: "Research",
    title: "Map who's exposed",
    description:
      "The other half of the article breakdown: every story is linked to the tickers, sectors, and entities it touches. The relationship graph turns one headline into a list of who actually gets hit — second-order moves you'd otherwise miss.",
    href: "/protected/relations",
    cta: "Open relations",
    visitKey: "relations",
  },
  {
    key: "charts",
    group: "Research",
    title: "Read the chart with AI context",
    description:
      "Pull up any ticker with technicals plus an AI analyst that explains what the price is reacting to — pinning the news and impact scores you just learned to the candles in front of you.",
    href: "/protected/charts",
    cta: "Open charts",
    visitKey: "charts",
  },
  {
    key: "screenings",
    group: "Operations",
    title: "Run your first screen",
    description:
      "Filter the universe by the dimensions you've now learned — impact, sentiment, fundamentals, trend templates. Turn passive reading into a shortlist of names worth a closer look today.",
    href: "/protected/screenings",
    cta: "Open screener",
    visitKey: "screenings",
  },
  {
    key: "trade",
    group: "Operations",
    title: "Log your first trade",
    description:
      "Once you've taken a position, log entries and exits here. Doing so turns on the portfolio table, equity curve, and P&L on your dashboard — your scoreboard for whether the system is working for you.",
    href: "/protected/trades",
    cta: "Log a trade",
  },
  {
    key: "agent",
    group: "Operations",
    title: "Schedule an AI agent",
    description:
      "Describe a setup in plain English and the agent runs it on a cron, pinging your Telegram only when it triggers. This is the payoff of every prior step — the platform watching the market for you while you do everything else.",
    href: "/protected/agents",
    cta: "Create agent",
  },
];

const COLLAPSED_STORAGE_KEY = "onboarding_checklist_collapsed";

export function OnboardingChecklist({ initialProgress }: { initialProgress: OnboardingProgress }) {
  const [progress, setProgress] = useState<OnboardingProgress>(initialProgress);
  const [hidden, setHidden] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [currentStepIndex, setCurrentStepIndex] = useState(() => {
    const firstIncomplete = STEPS.findIndex((s) => !initialProgress[s.key]);
    return firstIncomplete === -1 ? 0 : firstIncomplete;
  });
  const highlight = usePostWelcomeHighlight();
  const [, startTransition] = useTransition();

  useEffect(() => {
    if (typeof window === "undefined") return;
    if (window.localStorage.getItem(COLLAPSED_STORAGE_KEY) === "1") {
      setCollapsed(true);
    }
  }, []);

  function toggleCollapsed() {
    setCollapsed((prev) => {
      const next = !prev;
      if (typeof window !== "undefined") {
        window.localStorage.setItem(COLLAPSED_STORAGE_KEY, next ? "1" : "0");
      }
      track("onboarding_collapsed_toggled", { collapsed: next });
      return next;
    });
  }

  const { completedCount, allComplete } = useMemo(() => {
    const done = STEPS.filter((s) => progress[s.key]).length;
    return { completedCount: done, allComplete: done === STEPS.length };
  }, [progress]);

  if (hidden) return null;

  function handleStepClick(step: Step) {
    track("onboarding_step_clicked", { step: step.key });
    // First click anywhere in the checklist clears the post-welcome pulse —
    // the user got the message.
    clearPostWelcomeHighlight();
    if (!step.visitKey) return;
    const visitKey = step.visitKey;
    if (progress[step.key]) return;
    setProgress((prev) => ({ ...prev, [step.key]: true }));
    startTransition(async () => {
      await markOnboardingVisited(visitKey);
    });
  }

  function handleDismiss() {
    setHidden(true);
    track("onboarding_dismissed", {
      completed_steps: completedCount,
      total_steps: STEPS.length,
    });
    startTransition(async () => {
      await dismissOnboardingChecklist();
    });
  }

  function handleRestart() {
    track("onboarding_restarted", {
      completed_steps: completedCount,
      total_steps: STEPS.length,
    });
    // Clear visit-based flags optimistically. Action-based flags (trade,
    // agent) stay true because they reflect real data — wiping the trade
    // history just to re-do the tour is the wrong tradeoff.
    setProgress((prev) => ({
      ...prev,
      profile: false,
      articles: false,
      news_trends: false,
      relations: false,
      charts: false,
      screenings: false,
    }));
    setCurrentStepIndex(0);
    setHidden(false);
    setCollapsed(false);
    if (typeof window !== "undefined") {
      window.localStorage.setItem(COLLAPSED_STORAGE_KEY, "0");
    }
    startTransition(async () => {
      await restartOnboardingChecklist();
    });
  }

  if (allComplete) {
    return (
      <div className="space-y-2">
        <div
          className={`rounded-lg border border-emerald-500/30 bg-emerald-500/5 px-4 py-3 text-sm transition-shadow ${
            highlight ? "ring-2 ring-amber-400 ring-offset-2 ring-offset-background animate-pulse" : ""
          }`}
        >
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-emerald-500" aria-hidden />
              <span className="font-medium">You're set up.</span>
              <span className="text-muted-foreground">
                All eight steps complete — happy hunting.
              </span>
            </div>
            <div className="flex items-center gap-3">
              <button
                type="button"
                onClick={handleRestart}
                className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                <RotateCcw className="h-3 w-3" aria-hidden />
                Restart tour
              </button>
              <button
                type="button"
                onClick={handleDismiss}
                className="text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                Hide
              </button>
            </div>
          </div>
        </div>
        <AskAiReminder />
      </div>
    );
  }

  const currentStep = STEPS[currentStepIndex];
  const currentDone = progress[currentStep.key];
  const canPrev = currentStepIndex > 0;
  const canNext = currentStepIndex < STEPS.length - 1;

  return (
    <div
      className={`rounded-lg border border-border bg-card transition-shadow ${
        highlight ? "ring-2 ring-amber-400 ring-offset-2 ring-offset-background animate-pulse" : ""
      }`}
    >
      <div
        className={`flex items-start justify-between gap-3 px-4 py-3 ${
          collapsed ? "" : "border-b border-border"
        }`}
      >
        <button
          type="button"
          onClick={toggleCollapsed}
          aria-expanded={!collapsed}
          aria-controls="onboarding-checklist-body"
          className="min-w-0 flex-1 text-left rounded-md -mx-1 px-1 hover:bg-muted/40 transition-colors"
        >
          <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground/60">
            Get started
          </p>
          <h2 className="mt-0.5 text-sm font-medium">
            Walk through the platform, one step at a time
          </h2>
          {!collapsed && (
            <p className="mt-1 text-xs text-muted-foreground">
              Setup → Research → Operations. Each step opens a page and explains what you'll get from it. Use the arrows to navigate.
            </p>
          )}
        </button>
        <div className="flex shrink-0 items-center gap-3">
          <span className="tabular-nums text-xs text-muted-foreground">
            {completedCount} / {STEPS.length}
          </span>
          {completedCount > 0 && (
            <button
              type="button"
              onClick={handleRestart}
              aria-label="Restart tour"
              title="Restart tour"
              className="rounded-md p-1 text-muted-foreground/60 hover:bg-muted hover:text-foreground transition-colors"
            >
              <RotateCcw className="h-4 w-4" />
            </button>
          )}
          <button
            type="button"
            onClick={toggleCollapsed}
            aria-label={collapsed ? "Expand checklist" : "Collapse checklist"}
            className="rounded-md p-1 text-muted-foreground/60 hover:bg-muted hover:text-foreground transition-colors"
          >
            {collapsed ? (
              <ChevronDown className="h-4 w-4" />
            ) : (
              <ChevronUp className="h-4 w-4" />
            )}
          </button>
          <button
            type="button"
            onClick={handleDismiss}
            aria-label="Dismiss checklist"
            className="rounded-md p-1 text-muted-foreground/60 hover:bg-muted hover:text-foreground transition-colors"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>

      {collapsed ? null : (
      <div id="onboarding-checklist-body">
        <div className="flex items-start gap-3 px-4 py-4">
          <div
            aria-hidden
            className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border ${
              currentDone
                ? "border-emerald-500 bg-emerald-500 text-white"
                : "border-border bg-background text-transparent"
            }`}
          >
            <Check className="h-3 w-3" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground/60">
              {currentStep.group} · Step {currentStepIndex + 1} of {STEPS.length}
            </p>
            <p
              className={`mt-1 text-sm font-medium ${
                currentDone ? "text-muted-foreground line-through" : ""
              }`}
            >
              {currentStep.title}
            </p>
            <p className="mt-1 text-xs text-muted-foreground leading-relaxed">
              {currentStep.description}
            </p>
            <div className="mt-3">
              <Button
                asChild
                size="sm"
                variant={currentDone ? "ghost" : "outline"}
              >
                <Link
                  href={`${currentStep.href}?tour=1`}
                  onClick={() => handleStepClick(currentStep)}
                >
                  {currentDone ? "Retake tour" : currentStep.cta}
                  <ArrowRight className="ml-1 h-3 w-3" />
                </Link>
              </Button>
            </div>
          </div>
        </div>

        <div className="flex items-center justify-between gap-3 border-t border-border px-4 py-2">
          <button
            type="button"
            onClick={() => setCurrentStepIndex((i) => Math.max(0, i - 1))}
            disabled={!canPrev}
            aria-label="Previous step"
            className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs text-muted-foreground hover:bg-muted hover:text-foreground transition-colors disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-muted-foreground"
          >
            <ChevronLeft className="h-3.5 w-3.5" />
            Prev
          </button>

          <div
            className="flex items-center gap-1.5"
            role="tablist"
            aria-label="Onboarding steps"
          >
            {STEPS.map((step, i) => {
              const done = progress[step.key];
              const isCurrent = i === currentStepIndex;
              const baseClasses =
                "h-2 rounded-full transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-ring";
              const stateClasses = isCurrent
                ? "w-6 bg-foreground"
                : done
                ? "w-2 bg-emerald-500"
                : "w-2 bg-muted-foreground/30 hover:bg-muted-foreground/60";
              return (
                <button
                  key={step.key}
                  type="button"
                  role="tab"
                  aria-selected={isCurrent}
                  aria-label={`Step ${i + 1}: ${step.title}${done ? " (complete)" : ""}`}
                  onClick={() => setCurrentStepIndex(i)}
                  className={`${baseClasses} ${stateClasses}`}
                />
              );
            })}
          </div>

          <button
            type="button"
            onClick={() =>
              setCurrentStepIndex((i) => Math.min(STEPS.length - 1, i + 1))
            }
            disabled={!canNext}
            aria-label="Next step"
            className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs text-muted-foreground hover:bg-muted hover:text-foreground transition-colors disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-muted-foreground"
          >
            Next
            <ChevronRight className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
      )}
    </div>
  );
}
