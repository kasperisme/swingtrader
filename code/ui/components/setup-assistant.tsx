"use client";

/**
 * Setup Assistant — the conversational onboarding agent. It interviews a new
 * user and actually performs their setup (trading strategy, market-screening
 * subscriptions, Telegram pairing, first scheduled agent) by calling the setup
 * tools server-side via /api/ai/onboarding.
 *
 * The chat itself (`SetupAssistantChat`) is chrome-less and embeddable — it's
 * dropped straight into the welcome dialog right after the tutorial video, and
 * also rendered inside a centered modal (`SetupAssistantRoot`) for re-entry
 * from the profile page. It is never a sidebar.
 */

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { Loader2, Send, Sparkles, Wand2 } from "lucide-react";

import { ChatMarkdown } from "@/components/chat-markdown";
import {
  StatusChips,
  TelegramConnectInline,
  type AssistantChatMessage,
} from "@/components/ai-chat-bits";
import { markAiOnboardingSeen } from "@/app/actions/onboarding";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

// ── Module-level pub/sub so any trigger can open the modal assistant ─────────
type Listener = (open: boolean) => void;
const listeners = new Set<Listener>();
export function openSetupAssistant() {
  listeners.forEach((l) => l(true));
}
export function closeSetupAssistant() {
  listeners.forEach((l) => l(false));
}

const SETUP_STEPS = [
  { key: "strategy", label: "Strategy" },
  { key: "holdings", label: "Holdings" },
  { key: "screenings", label: "Screenings" },
  { key: "telegram", label: "Telegram" },
  { key: "agent", label: "First agent" },
] as const;

/** Heuristically light up the progress strip from the agent's status chips. */
function deriveDone(messages: AssistantChatMessage[]): Record<string, boolean> {
  const text = messages
    .flatMap((m) => m.statuses ?? [])
    .join(" ")
    .toLowerCase();
  return {
    strategy: text.includes("trading strategy"),
    holdings: text.includes("added holding"),
    screenings: text.includes("subscribed to"),
    telegram: text.includes("telegram connected"),
    agent: text.includes("created agent"),
  };
}

export function SetupAssistantTrigger({ className = "" }: { className?: string }) {
  return (
    <button
      type="button"
      onClick={() => openSetupAssistant()}
      className={
        className ||
        "inline-flex items-center gap-1.5 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground cursor-pointer"
      }
      aria-label="Open the Setup Assistant"
    >
      <Wand2 className="h-3.5 w-3.5" />
      Set up with AI
    </button>
  );
}

/**
 * Standalone modal entry point (re-entry from profile etc.). Mounted once in
 * the protected layout; opened via openSetupAssistant(). Renders the chat in a
 * centered dialog — not a sidebar.
 */
export function SetupAssistantRoot() {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const listener: Listener = (next) => setOpen(next);
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  }, []);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="flex h-[85vh] flex-col gap-4 overflow-hidden sm:max-w-2xl">
        <DialogHeader className="shrink-0">
          <DialogTitle className="flex items-center gap-2 text-xl">
            <Sparkles className="h-4 w-4 text-amber-500" />
            Set up with AI
          </DialogTitle>
          <DialogDescription>
            Tell me how you trade and I&apos;ll configure your strategy,
            screenings, Telegram, and first agent.
          </DialogDescription>
        </DialogHeader>
        {open && <SetupAssistantChat className="min-h-0 flex-1" />}
      </DialogContent>
    </Dialog>
  );
}

/**
 * The chrome-less conversation. Fills its parent (give it a height). Manages
 * its own message state, auto-kicks off the interview on mount, and renders the
 * progress strip + transcript + composer.
 */
export function SetupAssistantChat({ className = "" }: { className?: string }) {
  const [messages, setMessages] = useState<AssistantChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const kickedOff = useRef(false);

  useEffect(() => {
    // Remember the user has now seen AI onboarding so it doesn't auto-open again.
    void markAiOnboardingSeen();
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, loading]);

  // NB: we deliberately do NOT abort the in-flight request on unmount. React
  // strict-mode (dev) mounts → unmounts → remounts; an unmount-abort would
  // cancel the auto-kickoff request before it's resent, so the opening message
  // would never arrive. The `loading` guard below already prevents overlap.

  const runTurn = useCallback(
    async (userText: string | null) => {
      if (loading) return;
      const trimmed = userText?.trim() ?? null;

      // A null userText = kickoff (no user bubble).
      const base = messages;
      const withUser: AssistantChatMessage[] = trimmed
        ? [...base, { role: "user", content: trimmed }]
        : [...base];
      const next: AssistantChatMessage[] = [
        ...withUser,
        { role: "assistant", content: "" },
      ];
      setMessages(next);
      setInput("");
      setLoading(true);

      const controller = new AbortController();
      abortRef.current = controller;

      const updateLast = (patch: Partial<AssistantChatMessage>) =>
        setMessages((prev) => {
          const copy = [...prev];
          copy[copy.length - 1] = { ...copy[copy.length - 1], ...patch };
          return copy;
        });

      try {
        const res = await fetch("/api/ai/onboarding", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            messages: withUser.map((m) => ({ role: m.role, content: m.content })),
            kickoff: !trimmed,
          }),
          signal: controller.signal,
        });

        if (!res.ok || !res.body) {
          const errText = await res.text().catch(() => res.statusText);
          updateLast({ content: `Error: ${errText || "request failed"}` });
          return;
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buf = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buf += decoder.decode(value, { stream: true });
          const lines = buf.split("\n");
          buf = lines.pop() ?? "";
          for (const line of lines) {
            if (!line.trim()) continue;
            let msg: Record<string, unknown>;
            try {
              msg = JSON.parse(line) as Record<string, unknown>;
            } catch {
              continue;
            }

            if (msg.type === "text") {
              updateLast({
                content: typeof msg.content === "string" ? msg.content : "",
              });
            } else if (msg.type === "status") {
              const label = typeof msg.label === "string" ? msg.label : "";
              if (label) {
                setMessages((prev) => {
                  const copy = [...prev];
                  const last = copy[copy.length - 1];
                  copy[copy.length - 1] = {
                    ...last,
                    statuses: [...(last.statuses ?? []), label],
                  };
                  return copy;
                });
              }
            } else if (msg.type === "telegram_link") {
              const deepLink =
                typeof msg.deep_link === "string" ? msg.deep_link : "";
              if (deepLink) updateLast({ telegram: { deep_link: deepLink } });
            } else if (msg.type === "error") {
              updateLast({ content: `Error: ${String(msg.message)}` });
            }
          }
        }
      } catch (err) {
        if (err instanceof Error && err.name === "AbortError") return;
        updateLast({
          content: `Error: ${err instanceof Error ? err.message : String(err)}`,
        });
      } finally {
        setLoading(false);
      }
    },
    [loading, messages],
  );

  // Auto-kick off the interview once on mount.
  useEffect(() => {
    if (kickedOff.current) return;
    kickedOff.current = true;
    void runTurn(null);
  }, [runTurn]);

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void runTurn(input);
  }

  const done = deriveDone(messages);

  return (
    <div className={`flex min-h-0 flex-col ${className}`}>
      {/* Progress strip */}
      <div className="flex shrink-0 flex-wrap items-center gap-1.5 rounded-md border border-border bg-muted/30 px-3 py-2">
        {SETUP_STEPS.map((step, i) => (
          <div key={step.key} className="flex items-center gap-1.5">
            <span
              className={
                done[step.key]
                  ? "inline-flex items-center gap-1 text-[11px] font-medium text-emerald-600 dark:text-emerald-400"
                  : "inline-flex items-center gap-1 text-[11px] font-medium text-muted-foreground"
              }
            >
              <span
                className={
                  done[step.key]
                    ? "h-1.5 w-1.5 rounded-full bg-emerald-500"
                    : "h-1.5 w-1.5 rounded-full bg-muted-foreground/30"
                }
              />
              {step.label}
            </span>
            {i < SETUP_STEPS.length - 1 && (
              <span className="text-muted-foreground/30">·</span>
            )}
          </div>
        ))}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto py-3">
        <ul className="flex flex-col gap-3">
          {messages.map((m, i) => (
            <li
              key={i}
              className={
                m.role === "user"
                  ? "self-end max-w-[85%] rounded-lg bg-foreground/10 px-3 py-2 text-sm"
                  : "self-start w-full max-w-[92%] rounded-lg border border-border bg-card px-3 py-2 text-sm"
              }
            >
              {m.role === "assistant" && !m.content && loading ? (
                <span className="inline-flex items-center gap-2 text-muted-foreground">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  Setting things up…
                </span>
              ) : m.role === "assistant" ? (
                <>
                  {m.content && <ChatMarkdown content={m.content} variant="help" />}
                  <StatusChips statuses={m.statuses} />
                  {m.telegram?.deep_link && (
                    <TelegramConnectInline
                      deepLink={m.telegram.deep_link}
                      onConnected={() => void runTurn("I've connected Telegram.")}
                    />
                  )}
                </>
              ) : (
                <p className="whitespace-pre-wrap">{m.content}</p>
              )}
            </li>
          ))}
        </ul>
        <div ref={bottomRef} />
      </div>

      <form onSubmit={onSubmit} className="shrink-0 border-t border-border pt-3">
        <div className="flex items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void runTurn(input);
              }
            }}
            placeholder="Type your answer…"
            rows={1}
            disabled={loading}
            className="min-h-[40px] max-h-32 flex-1 resize-none rounded-md border border-input bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring disabled:opacity-60"
          />
          <button
            type="submit"
            disabled={loading || !input.trim()}
            className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-foreground text-background transition-opacity hover:opacity-90 disabled:opacity-40"
            aria-label="Send"
          >
            {loading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Send className="h-4 w-4" />
            )}
          </button>
        </div>
      </form>
    </div>
  );
}
