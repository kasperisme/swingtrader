"use client";

/**
 * Post-welcome highlight tour. Fires once after the welcome dialog
 * dismisses and points the user at the two surfaces they'll need next:
 * the Ask AI reminder banner (the way back into setup) and the Ask AI
 * button in the top bar (for everything after).
 *
 * Uses the same Driver.js mechanic as the per-page tours so the visual
 * treatment is identical — popover with title + description, spotlight
 * cutout, progress dots. Falls back to a centered modal step when an
 * anchor isn't on screen.
 *
 * Mount once in the protected layout. The tour is gated on the
 * post-welcome highlight flag (set by WelcomeDialog dismiss); on
 * Driver.js destroy the flag clears so it never re-fires.
 */

import { useEffect, useRef } from "react";

import {
  clearPostWelcomeHighlight,
  usePostWelcomeHighlight,
} from "./onboarding-highlight";

import "driver.js/dist/driver.css";

type DriverStepConfig = {
  element?: string;
  popover?: {
    title?: string;
    description?: string;
    side?: "top" | "bottom" | "left" | "right";
    align?: "start" | "center" | "end";
  };
};

const STEPS: ReadonlyArray<DriverStepConfig> = [
  {
    element: '[data-tour="ask-ai-reminder"]',
    popover: {
      title: "Start here",
      description:
        "This banner is your shortcut back into setup. Whatever you skipped — strategy, holdings, screenings, Telegram, your first agent — the AI can still configure it for you from here.",
      side: "bottom",
      align: "start",
    },
  },
  {
    element: '[data-tour="ask-ai"]',
    popover: {
      title: "Need help finding something?",
      description:
        "Ask AI is always one click away in the top bar. It knows the platform, the data, and where every page lives. If a tour ends and you still have questions — start here.",
      side: "bottom",
      align: "end",
    },
  },
];

export function PostWelcomeHighlightTour() {
  const active = usePostWelcomeHighlight();
  const firedRef = useRef(false);

  useEffect(() => {
    if (!active) return;
    if (firedRef.current) return;
    if (typeof window === "undefined") return;

    firedRef.current = true;
    let driverObj: { drive: () => void; destroy?: () => void } | null = null;

    // Defer briefly so the welcome dialog's close animation is finished
    // before the spotlight kicks in — otherwise Driver.js highlights an
    // element that's still under the dialog backdrop.
    const timeoutId = window.setTimeout(async () => {
      // Verify at least one anchor is mounted; if neither is, skip the
      // tour rather than running in a degraded centered-modal state.
      const anyAnchor = STEPS.some(
        (s) => s.element && document.querySelector(s.element),
      );
      if (!anyAnchor) {
        clearPostWelcomeHighlight();
        return;
      }

      const mod = await import("driver.js");
      driverObj = mod.driver({
        showProgress: true,
        allowClose: true,
        steps: STEPS.map((step) => ({
          element: step.element && document.querySelector(step.element)
            ? step.element
            : undefined,
          popover: step.popover,
        })),
        onDestroyed: () => {
          // Driver fires onDestroyed both on natural completion and on
          // close — either way the user has seen the hint. Clear the
          // flag so navigating around doesn't re-trigger it.
          clearPostWelcomeHighlight();
        },
      });
      driverObj.drive();
    }, 600);

    return () => {
      window.clearTimeout(timeoutId);
      if (driverObj?.destroy) {
        try {
          driverObj.destroy();
        } catch {
          /* already torn down */
        }
      }
    };
  }, [active]);

  return null;
}
