"use client";

/**
 * Reusable per-page guided tour. One component for all 8 tours — the only
 * thing that varies is `tourKey`. Per-tour content (selectors, copy) lives in
 * tour-configs.ts so editing UX never touches React code.
 *
 * Usage:
 *   <PageTour tourKey="articles" autoStart={!alreadyToured} />
 *
 * - Auto-starts the tour once on first mount when autoStart is true OR when
 *   the URL carries `?tour=1` (the entry point from the onboarding checklist).
 * - On completion, marks the tour done and refreshes the route so server
 *   state (checklist, autoStart prop) reflects the new state.
 * - Renders nothing visible — the only way to (re)start a tour is from the
 *   onboarding guide on /protected.
 */

import { useCallback, useEffect, useRef, useState, useTransition } from "react";
import { useRouter } from "next/navigation";

import { markTourComplete, type TourKey } from "@/app/actions/onboarding";
import { TOURS, type TourStep } from "./tour-configs";

import "driver.js/dist/driver.css";

/**
 * Custom DOM event other surfaces (the help chat, future Cmd-K, etc.) can
 * dispatch on `window` to re-fire a tour without a navigation.
 *
 * Detail: `{ tourKey, fromStep?, toStep? }` — fromStep/toStep are 0-based and
 * inclusive, matching the URL contract.
 */
export const RUN_TOUR_EVENT = "swingtrader:run-tour";

export type RunTourEventDetail = {
  tourKey: TourKey;
  fromStep?: number;
  toStep?: number;
};

type Props = {
  tourKey: TourKey;
  autoStart?: boolean;
};

type DriverStepConfig = {
  element?: string;
  popover?: {
    title?: string;
    description?: string;
    side?: TourStep["side"];
    align?: TourStep["align"];
  };
};

export function PageTour({ tourKey, autoStart = false }: Props) {
  const config = TOURS[tourKey];
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [, startTransition] = useTransition();
  const autoStartedRef = useRef(false);
  const runTourRef = useRef<
    | ((override?: { fromStep?: number; toStep?: number }) => Promise<void>)
    | null
  >(null);

  const runTour = useCallback(async (override?: { fromStep?: number; toStep?: number }) => {
    if (busy) return;
    setBusy(true);
    try {
      const mod = await import("driver.js");
      const driverFactory = mod.driver;

      // Default to the full tour. The step range can come from either:
      // - the override param (custom event from another surface)
      // - the URL `?step=N&end=M` (entry from a link)
      // - or default to all steps.
      let stepsSource: ReadonlyArray<TourStep> = config.steps;
      let start = 0;
      let end = config.steps.length - 1;

      if (typeof override?.fromStep === "number") {
        start = Math.max(0, override.fromStep);
      }
      if (typeof override?.toStep === "number") {
        end = Math.min(config.steps.length - 1, override.toStep);
      }

      if (typeof window !== "undefined") {
        const url = new URL(window.location.href);
        if (override === undefined) {
          const startStr = url.searchParams.get("step");
          const endStr = url.searchParams.get("end");
          if (startStr) start = Math.max(0, parseInt(startStr, 10));
          if (endStr)
            end = Math.min(config.steps.length - 1, parseInt(endStr, 10));
        }

        // Strip ?tour/?step/?end only once we've truly committed to running.
        // Doing this inside the start effect tripped up React Strict Mode's
        // double-mount in dev: mount 1 stripped the URL, and on mount 2 the
        // params were gone so the tour never fired.
        let mutated = false;
        for (const key of ["tour", "step", "end"]) {
          if (url.searchParams.has(key)) {
            url.searchParams.delete(key);
            mutated = true;
          }
        }
        if (mutated) {
          window.history.replaceState(
            window.history.state,
            "",
            url.pathname + url.search + url.hash,
          );
        }
      }

      if (Number.isFinite(start) && Number.isFinite(end) && start <= end) {
        stepsSource = config.steps.slice(start, end + 1);
      }

      const steps: DriverStepConfig[] = stepsSource.map((step) => {
        // If the selector doesn't match anything, fall back to a centered
        // popover so a missing anchor degrades to a normal step instead of
        // crashing the tour. Pages can ship anchors incrementally.
        const exists = step.selector ? document.querySelector(step.selector) !== null : false;
        return {
          element: exists ? step.selector : undefined,
          popover: {
            title: step.title,
            description: step.description,
            side: step.side,
            align: step.align,
          },
        };
      });

      let completed = false;
      const driverObj = driverFactory({
        showProgress: true,
        allowClose: true,
        steps,
        onDestroyed: () => {
          // Driver fires onDestroyed both on natural completion and on close.
          // Treat both as "user has seen the tour" — we don't need to enforce
          // completion to mark it done.
          if (completed) return;
          completed = true;
          startTransition(async () => {
            await markTourComplete(tourKey);
            router.refresh();
          });
        },
      });

      driverObj.drive();
    } finally {
      setBusy(false);
    }
  }, [busy, config.steps, tourKey, router]);

  // Keep runTour reachable from the timeout without re-running the start
  // effect every time runTour's identity changes (which happens whenever
  // `busy` flips after we kick the tour off).
  runTourRef.current = runTour;

  useEffect(() => {
    if (typeof window === "undefined") return;

    // Read the tour flag from the live URL rather than via useSearchParams —
    // the hook is reactive, and any change to it during the 400ms window
    // (e.g. from a sibling Suspense resolving) would re-run this effect.
    const url = new URL(window.location.href);
    const wantsByQuery = url.searchParams.get("tour") === "1";
    if (!autoStart && !wantsByQuery) return;

    // Schedule the tour. The ref guard is INSIDE the timer callback so that
    // React Strict Mode's setup→cleanup→setup retry in dev still ends with a
    // live, scheduled timer (each run cancels the prior timer; the surviving
    // one fires after 400ms and this guard ensures we only ever drive once).
    const id = window.setTimeout(() => {
      if (autoStartedRef.current) return;
      autoStartedRef.current = true;
      void runTourRef.current?.();
    }, 400);
    return () => window.clearTimeout(id);
  }, [autoStart]);

  // Listen for explicit "run this tour now" events from other surfaces (the
  // help chat, future Cmd-K, etc.) so the AI can re-highlight components on
  // the page the user is already on — no navigation needed.
  useEffect(() => {
    if (typeof window === "undefined") return;
    function onRunTour(e: Event) {
      const detail = (e as CustomEvent<RunTourEventDetail>).detail;
      if (!detail || detail.tourKey !== tourKey) return;
      // Allow re-running on demand: bypass the auto-start guard but defer
      // briefly so the calling surface (e.g. help panel) can finish its own
      // close animation first.
      window.setTimeout(() => {
        void runTourRef.current?.({
          fromStep: detail.fromStep,
          toStep: detail.toStep,
        });
      }, 150);
    }
    window.addEventListener(RUN_TOUR_EVENT, onRunTour as EventListener);
    return () =>
      window.removeEventListener(RUN_TOUR_EVENT, onRunTour as EventListener);
  }, [tourKey]);

  return null;
}
