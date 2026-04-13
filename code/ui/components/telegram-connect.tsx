"use client";

import { useEffect, useRef, useState } from "react";

type Status = {
  connected: boolean;
  chat_id: string | null;
  delivery_method: string;
  is_enabled: boolean;
  delivery_time: string;
  lookback_hours: number;
};

type LinkState =
  | { phase: "idle" }
  | { phase: "loading" }
  | { phase: "awaiting"; deep_link: string; expires_at: string }
  | { phase: "connected" }
  | { phase: "error"; message: string };

export function TelegramConnect() {
  const [status, setStatus] = useState<Status | null>(null);
  const [link, setLink] = useState<LinkState>({ phase: "idle" });
  const [copied, setCopied] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Load current connection status on mount
  useEffect(() => {
    fetch("/api/user/telegram")
      .then((r) => r.json())
      .then((data) => setStatus(data))
      .catch(() => {});
  }, []);

  // Poll for connection confirmation while awaiting
  useEffect(() => {
    if (link.phase !== "awaiting") {
      if (pollRef.current) clearInterval(pollRef.current);
      return;
    }
    pollRef.current = setInterval(async () => {
      try {
        const r = await fetch("/api/user/telegram");
        const data: Status = await r.json();
        if (data.connected) {
          setStatus(data);
          setLink({ phase: "connected" });
        }
      } catch {}
    }, 3000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [link.phase]);

  async function handleConnect() {
    setLink({ phase: "loading" });
    try {
      const r = await fetch("/api/user/telegram", { method: "POST" });
      const data = await r.json();
      if (!r.ok) throw new Error(data.error ?? "Failed to generate link");
      setLink({ phase: "awaiting", deep_link: data.deep_link, expires_at: data.expires_at });
    } catch (err: unknown) {
      setLink({ phase: "error", message: err instanceof Error ? err.message : "Unknown error" });
    }
  }

  async function handleDisconnect() {
    await fetch("/api/user/telegram", { method: "DELETE" });
    setStatus((s) => s ? { ...s, connected: false, chat_id: null, delivery_method: "in_app" } : null);
    setLink({ phase: "idle" });
  }

  function handleCopy(text: string) {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  const isConnected = status?.connected || link.phase === "connected";

  return (
    <div className="rounded-2xl border border-border bg-card p-5 flex flex-col gap-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="text-sm font-semibold">Telegram</h3>
          <p className="text-xs text-muted-foreground mt-0.5">
            Pair your account to receive the Daily Narrative by message at 08:30 ET on weekdays.
          </p>
        </div>
        {/* Status badge */}
        <span
          className={`shrink-0 inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold ${
            isConnected
              ? "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300"
              : "bg-muted text-muted-foreground"
          }`}
        >
          <span
            className={`h-1.5 w-1.5 rounded-full ${isConnected ? "bg-green-500" : "bg-zinc-400"}`}
          />
          {isConnected ? "Connected" : "Not connected"}
        </span>
      </div>

      {/* Connected state */}
      {isConnected && (
        <div className="flex items-center justify-between gap-4">
          <p className="text-xs text-muted-foreground">
            Messages go to chat ID{" "}
            <code className="font-mono text-[11px] bg-muted rounded px-1">
              {status?.chat_id ?? "…"}
            </code>
          </p>
          <button
            type="button"
            onClick={handleDisconnect}
            className="text-xs text-muted-foreground hover:text-red-500 transition-colors cursor-pointer"
          >
            Disconnect
          </button>
        </div>
      )}

      {/* Idle — show connect button */}
      {!isConnected && link.phase === "idle" && (
        <button
          type="button"
          onClick={handleConnect}
          className="self-start rounded-lg bg-blue-500 hover:bg-blue-600 text-white text-sm font-semibold px-4 py-2 transition-colors cursor-pointer"
        >
          Connect Telegram
        </button>
      )}

      {/* Loading */}
      {link.phase === "loading" && (
        <p className="text-sm text-muted-foreground animate-pulse">Generating link…</p>
      )}

      {/* Awaiting — show deep link */}
      {link.phase === "awaiting" && (
        <div className="flex flex-col gap-3">
          <p className="text-sm">
            <span className="font-medium">1.</span> Tap the link below to open Telegram and press{" "}
            <span className="font-semibold">START</span>.
          </p>
          <div className="flex items-center gap-2">
            <a
              href={link.deep_link}
              target="_blank"
              rel="noopener noreferrer"
              className="flex-1 truncate rounded-lg border border-border bg-muted px-3 py-2 font-mono text-xs text-blue-500 hover:underline"
            >
              {link.deep_link}
            </a>
            <button
              type="button"
              onClick={() => handleCopy(link.deep_link)}
              className="shrink-0 rounded-lg border border-border bg-card px-3 py-2 text-xs font-medium hover:bg-muted transition-colors cursor-pointer"
            >
              {copied ? "Copied!" : "Copy"}
            </button>
          </div>
          <p className="text-xs text-muted-foreground animate-pulse">
            Waiting for confirmation from Telegram…
          </p>
          <p className="text-xs text-muted-foreground">
            Link expires at{" "}
            {new Date(link.expires_at).toLocaleTimeString("en-US", {
              hour: "2-digit",
              minute: "2-digit",
            })}
            .{" "}
            <button type="button" onClick={handleConnect} className="underline cursor-pointer">
              Regenerate
            </button>
          </p>
        </div>
      )}

      {/* Success flash */}
      {link.phase === "connected" && (
        <p className="text-sm text-green-600 dark:text-green-400 font-medium">
          ✓ Telegram connected. You&apos;ll receive your first narrative tomorrow at 08:30 ET.
        </p>
      )}

      {/* Error */}
      {link.phase === "error" && (
        <div className="flex items-center gap-3">
          <p className="text-sm text-red-500">{link.message}</p>
          <button
            type="button"
            onClick={() => setLink({ phase: "idle" })}
            className="text-xs underline cursor-pointer text-muted-foreground hover:text-foreground"
          >
            Retry
          </button>
        </div>
      )}
    </div>
  );
}
