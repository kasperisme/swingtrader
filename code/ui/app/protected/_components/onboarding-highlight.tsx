"use client";

import { useEffect, useState } from "react";

const FLAG_KEY = "npm_post_welcome_highlight";
const CHANGE_EVENT = "npm:post-welcome-highlight-changed";
const AUTO_CLEAR_MS = 30_000;

/**
 * Set after the welcome dialog dismisses so the onboarding checklist and
 * the Ask AI button briefly pulse on first arrival, drawing the user's
 * attention to the two places they're most likely to need next.
 *
 * Persisted to localStorage so the pulse survives navigation; auto-clears
 * after 30s or on first user interaction with either highlighted element.
 */
export function setPostWelcomeHighlight() {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(FLAG_KEY, "1");
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

export function clearPostWelcomeHighlight() {
  if (typeof window === "undefined") return;
  if (window.localStorage.getItem(FLAG_KEY) === null) return;
  window.localStorage.removeItem(FLAG_KEY);
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

/**
 * Returns true while the post-welcome highlight flag is set. Subscribes
 * to same-tab and cross-tab changes, and auto-clears the flag after
 * AUTO_CLEAR_MS so the pulse doesn't follow the user forever.
 */
export function usePostWelcomeHighlight(): boolean {
  const [active, setActive] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const sync = () => {
      setActive(window.localStorage.getItem(FLAG_KEY) === "1");
    };
    sync();
    window.addEventListener(CHANGE_EVENT, sync);
    window.addEventListener("storage", sync);

    const timeout = window.setTimeout(() => {
      clearPostWelcomeHighlight();
    }, AUTO_CLEAR_MS);

    return () => {
      window.removeEventListener(CHANGE_EVENT, sync);
      window.removeEventListener("storage", sync);
      window.clearTimeout(timeout);
    };
  }, []);

  return active;
}
