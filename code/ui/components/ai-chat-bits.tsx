"use client";

/**
 * Shared building blocks for the action-capable AI chats (Setup Assistant +
 * Ask AI). Both render the same inline Telegram connect button and tool-status
 * confirmation chips emitted by the setup tools.
 */

import { useEffect, useRef, useState } from "react";
import { Check, Loader2, Send } from "lucide-react";

export type AssistantChatMessage = {
  role: "user" | "assistant";
  content: string;
  /** Inline confirmation chips from tool `status` events (e.g. "Saved …"). */
  statuses?: string[];
  /** Set when a `telegram_link` event arrives — renders the connect button. */
  telegram?: { deep_link: string } | null;
};

/** Small green ✓ confirmations for actions the agent performed this turn. */
export function StatusChips({ statuses }: { statuses?: string[] }) {
  if (!statuses?.length) return null;
  return (
    <ul className="mt-2 flex flex-col gap-1">
      {statuses.map((s, i) => (
        <li
          key={i}
          className="inline-flex items-center gap-1.5 text-xs font-medium text-emerald-600 dark:text-emerald-400"
        >
          <Check className="h-3 w-3 shrink-0" />
          {s}
        </li>
      ))}
    </ul>
  );
}

/**
 * Telegram connect button + auto-poll. Tapping opens the deep link in a new
 * tab and begins polling /api/user/telegram; once the webhook records the
 * pairing we flip to "connected" and call onConnected (which the chat uses to
 * auto-tell the agent so it can continue).
 */
export function TelegramConnectInline({
  deepLink,
  onConnected,
}: {
  deepLink: string;
  onConnected?: () => void;
}) {
  const [connected, setConnected] = useState(false);
  const [polling, setPolling] = useState(false);
  const firedRef = useRef(false);

  useEffect(() => {
    if (!polling || connected) return;
    let cancelled = false;
    const started = Date.now();
    const id = setInterval(async () => {
      if (cancelled) return;
      if (Date.now() - started > 150_000) {
        setPolling(false);
        clearInterval(id);
        return;
      }
      try {
        const r = await fetch("/api/user/telegram");
        const d = (await r.json()) as { connected?: boolean };
        if (d?.connected) {
          setConnected(true);
          setPolling(false);
          clearInterval(id);
          if (!firedRef.current) {
            firedRef.current = true;
            onConnected?.();
          }
        }
      } catch {
        // transient — keep polling until the deadline.
      }
    }, 3000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [polling, connected, onConnected]);

  if (connected) {
    return (
      <div className="mt-2 inline-flex items-center gap-1.5 rounded-md border border-emerald-500/40 bg-emerald-500/5 px-3 py-2 text-xs font-medium text-emerald-600 dark:text-emerald-400">
        <Check className="h-3.5 w-3.5" />
        Telegram connected
      </div>
    );
  }

  return (
    <div className="mt-2 flex flex-col gap-1.5">
      <a
        href={deepLink}
        target="_blank"
        rel="noopener noreferrer"
        onClick={() => setPolling(true)}
        className="inline-flex w-fit items-center gap-2 rounded-md bg-[#229ED9] px-3 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90"
      >
        <Send className="h-4 w-4" />
        Open Telegram to connect
      </a>
      {polling && (
        <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
          <Loader2 className="h-3 w-3 animate-spin" />
          Waiting for you to press Start in Telegram…
        </span>
      )}
    </div>
  );
}
