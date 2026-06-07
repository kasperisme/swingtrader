"use client";

/**
 * Shared building blocks for the action-capable AI chats (Setup Assistant +
 * Ask AI). Both render the same inline Telegram connect button and tool-status
 * confirmation chips emitted by the setup tools.
 */

import { useEffect, useRef, useState } from "react";
import { Check, Loader2, Send } from "lucide-react";
import { QRCodeSVG } from "qrcode.react";

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
  // Poll as soon as the connect UI is shown so the desktop → scan-on-phone flow
  // is detected without the user having to click the button first.
  const [polling, setPolling] = useState(true);
  const firedRef = useRef(false);

  useEffect(() => {
    if (!polling || connected) return;
    let cancelled = false;
    const started = Date.now();
    const id = setInterval(async () => {
      if (cancelled) return;
      // Match the 15-min token TTL with headroom for grabbing a phone to scan.
      if (Date.now() - started > 600_000) {
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
    <div className="mt-2 flex flex-col gap-3">
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

      {/* Desktop → phone: scan to open the bot in Telegram on mobile. */}
      <div className="flex items-center gap-3 rounded-md border border-border bg-card p-3">
        <div className="shrink-0 rounded-md bg-white p-2">
          <QRCodeSVG value={deepLink} size={104} marginSize={0} level="M" />
        </div>
        <div className="min-w-0 text-xs text-muted-foreground">
          <p className="font-medium text-foreground">On desktop?</p>
          <p className="mt-0.5">
            Scan this with your phone&apos;s camera to open Telegram and press
            <span className="font-medium text-foreground"> Start</span> — it
            connects automatically.
          </p>
        </div>
      </div>

      {polling && (
        <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
          <Loader2 className="h-3 w-3 animate-spin" />
          Waiting for you to connect in Telegram…
        </span>
      )}
    </div>
  );
}
