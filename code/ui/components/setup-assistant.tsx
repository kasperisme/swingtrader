"use client";

/**
 * Setup Assistant — the conversational onboarding agent. It interviews a new
 * user and actually performs their setup (trading strategy, market-screening
 * subscriptions, Telegram pairing, first scheduled agent) by calling the setup
 * tools server-side via /api/ai/onboarding.
 *
 * The chat itself (`SetupAssistantChat`) is chrome-less and embeddable — it's
 * dropped straight into the welcome dialog after the founder's welcome note,
 * and also rendered inside a centered modal (`SetupAssistantRoot`) for re-entry
 * from the profile page. It is never a sidebar.
 */

import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type FormEvent,
} from "react";
import {
  AlertCircle,
  Check,
  Loader2,
  Pencil,
  RotateCcw,
  Send,
  Sparkles,
  Wand2,
} from "lucide-react";

import { ChatMarkdown } from "@/components/chat-markdown";
import {
  StatusChips,
  TelegramConnectInline,
  type AssistantChatMessage,
} from "@/components/ai-chat-bits";
import { markAiOnboardingSeen } from "@/app/actions/onboarding";
import { track } from "@/lib/analytics/events";
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

// The assistant ends each question with a final line of tap-able quick replies:
//   ::options:: Option A | Option B | Option C
// Split that off the visible text so we can render it as buttons. While the
// line is still streaming in, hide the forming "::…" fragment so it never
// flickers in the bubble.
const OPTIONS_RE = /\n*::options::[ \t]*([^\n]*?)[ \t]*$/i;

function parseAssistant(content: string): { text: string; options: string[] } {
  const m = content.match(OPTIONS_RE);
  if (m && m.index !== undefined) {
    const options = m[1]
      .split("|")
      .map((s) => s.trim())
      .filter(Boolean)
      .slice(0, 4);
    return { text: content.slice(0, m.index).trimEnd(), options };
  }
  // A marker still streaming in (e.g. "::opt"). Hide the trailing fragment.
  const forming = content.match(/\n*::o[^\n]*$/i);
  if (forming && forming.index !== undefined) {
    return { text: content.slice(0, forming.index).trimEnd(), options: [] };
  }
  return { text: content, options: [] };
}

/**
 * Build the message history sent to the model. Drops broken assistant turns —
 * ones flagged `error` or with empty/whitespace content — so a failed step
 * never carries into later ones (an empty assistant turn also hard-fails the
 * Anthropic call, which previously broke every subsequent step). User turns are
 * always kept; content is trimmed and empty messages removed.
 */
function toApiHistory(
  msgs: AssistantChatMessage[],
): { role: "user" | "assistant"; content: string }[] {
  return msgs
    .filter((m) => !(m.role === "assistant" && (m.error || !m.content.trim())))
    .map((m) => ({ role: m.role, content: m.content.trim() }))
    .filter((m) => m.content.length > 0);
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
      <DialogContent className="flex h-[100dvh] max-h-[100dvh] flex-col gap-4 overflow-hidden rounded-none sm:h-[85dvh] sm:max-w-2xl sm:rounded-lg">
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
        {open && <SetupAssistantChat className="min-h-0 flex-1" surface="profile" />}
      </DialogContent>
    </Dialog>
  );
}

/**
 * The chrome-less conversation. Fills its parent (give it a height). Manages
 * its own message state, auto-kicks off the interview on mount, and renders the
 * progress strip + transcript + composer.
 */
export function SetupAssistantChat({
  className = "",
  surface = "welcome",
  onProgress,
}: {
  className?: string;
  /** Where the assistant was opened — "welcome" (first-join) | "profile" (re-entry). */
  surface?: string;
  /**
   * How many of the 5 setup tasks the agent has completed so far. Lets a host
   * (the welcome dialog) reflect real progress in its own chrome instead of
   * offering an always-primary "Next" that skips a setup nothing has been
   * written to yet.
   */
  onProgress?: (doneCount: number) => void;
}) {
  const [messages, setMessages] = useState<AssistantChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  // The chat can be mounted twice (welcome dialog + the standalone modal), so
  // the composer's label association can't use a hardcoded id.
  const inputId = useId();
  // Analytics refs (don't trigger renders): fire `opened` once, count user
  // messages, remember which of the 5 tasks are already done, and emit a
  // `finished` summary on unmount.
  const openedRef = useRef(false);
  const messagesSentRef = useRef(0);
  const doneRef = useRef<Record<string, boolean>>({});
  // When the latest question offers tap-able options, the free-text box stays
  // hidden until the user taps "Add note / comment".
  const [showComposer, setShowComposer] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const kickedOff = useRef(false);

  useEffect(() => {
    // Remember the user has now seen AI onboarding so it doesn't auto-open again.
    void markAiOnboardingSeen();
  }, []);

  useEffect(() => {
    if (!openedRef.current) {
      openedRef.current = true;
      track("setup_assistant_opened", { surface });
    }
    // On unmount (dialog closed / step advanced), emit a summary of how far the
    // agent got this user — the funnel's terminal event.
    return () => {
      track("setup_assistant_finished", {
        surface,
        tasks_completed: Object.values(doneRef.current).filter(Boolean).length,
        messages_sent: messagesSentRef.current,
      });
    };
  }, [surface]);

  // Fire a task_completed event the first time each of the 5 setup tasks flips
  // done (derived from the agent's status chips) — this is the utilization gold:
  // what the agent actually accomplished per user.
  useEffect(() => {
    const d = deriveDone(messages);
    for (const s of SETUP_STEPS) {
      if (d[s.key] && !doneRef.current[s.key]) {
        track("setup_assistant_task_completed", { surface, task: s.key });
      }
    }
    doneRef.current = d;
    onProgress?.(SETUP_STEPS.filter((s) => d[s.key]).length);
  }, [messages, surface, onProgress]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, loading]);

  // NB: we deliberately do NOT abort the in-flight request on unmount. React
  // strict-mode (dev) mounts → unmounts → remounts; an unmount-abort would
  // cancel the auto-kickoff request before it's resent, so the opening message
  // would never arrive. The `loading` guard below already prevents overlap.

  const runTurn = useCallback(
    // `baseOverride` replays on a history other than current state — used by
    // retry, which rewinds past the failed turn and can't wait for the setState
    // that does the rewinding to land.
    async (userText: string | null, baseOverride?: AssistantChatMessage[]) => {
      if (loading) return;
      const trimmed = userText?.trim() ?? null;

      // A null userText = kickoff (no user bubble).
      const base = baseOverride ?? messages;
      const withUser: AssistantChatMessage[] = trimmed
        ? [...base, { role: "user", content: trimmed }]
        : [...base];
      const next: AssistantChatMessage[] = [
        ...withUser,
        { role: "assistant", content: "" },
      ];
      setMessages(next);
      setInput("");
      setShowComposer(false);
      setLoading(true);

      const controller = new AbortController();
      abortRef.current = controller;

      const updateLast = (patch: Partial<AssistantChatMessage>) =>
        setMessages((prev) => {
          const copy = [...prev];
          copy[copy.length - 1] = { ...copy[copy.length - 1], ...patch };
          return copy;
        });

      let sawText = false;

      try {
        const res = await fetch("/api/ai/onboarding", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            // Only replay clean turns — a failed/empty step is dropped so it
            // can't break the steps after it.
            messages: toApiHistory(withUser),
            kickoff: !trimmed,
          }),
          signal: controller.signal,
        });

        if (!res.ok || !res.body) {
          const errText = await res.text().catch(() => res.statusText);
          updateLast({ content: `Error: ${errText || "request failed"}`, error: true });
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
              const content = typeof msg.content === "string" ? msg.content : "";
              if (content.trim()) sawText = true;
              updateLast({ content });
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
              sawText = true;
              updateLast({ content: `Error: ${String(msg.message)}`, error: true });
            }
          }
        }

        // The stream closed without any usable text (e.g. the server died mid
        // tool call). Surface a retryable note and flag the turn so it's not
        // replayed as an empty assistant message — which would 400 the next
        // request and break the following step.
        if (!sawText) {
          updateLast({
            content:
              "That step got interrupted before I could finish. Tap your last choice again, or tell me what you'd like to do next.",
            error: true,
          });
        }
      } catch (err) {
        if (err instanceof Error && err.name === "AbortError") return;
        updateLast({
          content: `Error: ${err instanceof Error ? err.message : String(err)}`,
          error: true,
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

  /**
   * Replay the last user turn after a failed step. Rewinds the transcript to
   * just before that turn so the broken assistant reply is discarded rather
   * than replayed — an errored/empty assistant turn hard-fails the next call.
   */
  const retryLast = useCallback(() => {
    if (loading) return;
    let idx = -1;
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === "user") {
        idx = i;
        break;
      }
    }
    track("setup_assistant_retried", { surface });
    // No user turn yet → the opening kickoff itself failed; re-kick it clean.
    if (idx === -1) {
      setMessages([]);
      void runTurn(null, []);
      return;
    }
    const text = messages[idx].content;
    const rewound = messages.slice(0, idx);
    setMessages(rewound);
    void runTurn(text, rewound);
  }, [loading, messages, runTurn, surface]);

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (input.trim()) {
      messagesSentRef.current += 1;
      track("setup_assistant_message_sent", { surface, via: "typed" });
    }
    void runTurn(input);
  }

  const done = deriveDone(messages);
  const doneCount = SETUP_STEPS.filter((s) => done[s.key]).length;

  // Tap-able quick replies from the latest answered question (only once the
  // turn has fully streamed in). When present, the free-text box is collapsed
  // behind an "Add note / comment" chip so the user mostly clicks.
  const lastMsg = messages[messages.length - 1];
  const latestOptions =
    !loading && lastMsg?.role === "assistant"
      ? parseAssistant(lastMsg.content).options
      : [];
  const optionsActive = latestOptions.length > 0;
  const composerVisible = !optionsActive || showComposer;

  function revealComposer() {
    setShowComposer(true);
    setTimeout(() => textareaRef.current?.focus(), 0);
  }

  return (
    <div className={`flex min-h-0 flex-col ${className}`}>
      {/* Progress strip. Done-state carries an icon as well as colour — colour
          alone is not an accessible indicator, and the old 1.5px dot was
          effectively invisible either way. */}
      <div
        className="flex shrink-0 flex-wrap items-center gap-x-2 gap-y-1 rounded-md border border-border bg-muted/30 px-3 py-2"
        aria-label={`Setup progress: ${doneCount} of ${SETUP_STEPS.length} complete`}
      >
        {SETUP_STEPS.map((step, i) => (
          <div key={step.key} className="flex items-center gap-2">
            <span
              className={`inline-flex items-center gap-1 text-xs font-medium transition-colors ${
                done[step.key]
                  ? "text-emerald-600 dark:text-emerald-400"
                  : "text-muted-foreground"
              }`}
            >
              {done[step.key] ? (
                <Check className="h-3 w-3 shrink-0" aria-hidden />
              ) : (
                <span className="h-1.5 w-1.5 shrink-0 rounded-full border border-muted-foreground/40" />
              )}
              {step.label}
              <span className="sr-only">
                {done[step.key] ? " — done" : " — not started"}
              </span>
            </span>
            {i < SETUP_STEPS.length - 1 && (
              <span aria-hidden className="text-muted-foreground/30">
                ·
              </span>
            )}
          </div>
        ))}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto py-3">
        {/* Replies stream in rather than navigating — announce them politely so
            screen-reader users hear each answer as it lands. */}
        <ul className="flex flex-col gap-3" aria-live="polite" aria-busy={loading}>
          {messages.map((m, i) => (
            <li
              key={i}
              className={
                m.role === "user"
                  ? "self-end max-w-[85%] animate-in fade-in slide-in-from-bottom-1 rounded-lg bg-foreground/10 px-3 py-2 text-sm duration-200"
                  : m.error
                    ? "self-start w-full max-w-[92%] animate-in fade-in slide-in-from-bottom-1 rounded-lg border border-destructive/40 bg-destructive/5 px-3 py-2 text-sm duration-200"
                    : "self-start w-full max-w-[92%] animate-in fade-in slide-in-from-bottom-1 rounded-lg border border-border bg-card px-3 py-2 text-sm duration-200"
              }
            >
              {m.role === "assistant" && !m.content && loading ? (
                <span className="inline-flex items-center gap-2 text-muted-foreground">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  Setting things up…
                </span>
              ) : m.role === "assistant" && m.error ? (
                // A failed step is a dead end unless we hand back a way out —
                // "tap your last choice again" only works if the choices are
                // still on screen, and after an error they are not.
                <div role="alert" className="flex flex-col gap-2">
                  <p className="flex items-start gap-1.5 text-foreground">
                    <AlertCircle
                      className="mt-0.5 h-3.5 w-3.5 shrink-0 text-destructive"
                      aria-hidden
                    />
                    <span>{m.content.replace(/^Error:\s*/i, "")}</span>
                  </p>
                  <button
                    type="button"
                    onClick={retryLast}
                    disabled={loading}
                    className="inline-flex min-h-9 w-fit cursor-pointer items-center gap-1.5 rounded-full border border-border bg-background px-3 text-xs font-medium transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:opacity-50"
                  >
                    <RotateCcw className="h-3.5 w-3.5" aria-hidden />
                    Try that step again
                  </button>
                </div>
              ) : m.role === "assistant" ? (
                <>
                  {(() => {
                    const { text } = parseAssistant(m.content);
                    return text ? <ChatMarkdown content={text} variant="help" /> : null;
                  })()}
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

      {optionsActive && (
        <div className="shrink-0 border-t border-border pt-3">
          <div className="flex flex-wrap gap-2">
            {latestOptions.map((opt) => (
              <button
                key={opt}
                type="button"
                onClick={() => {
                  messagesSentRef.current += 1;
                  track("setup_assistant_message_sent", { surface, via: "quick_reply" });
                  void runTurn(opt);
                }}
                className="inline-flex min-h-11 cursor-pointer items-center rounded-full border border-border bg-background px-4 text-sm font-medium text-foreground transition-colors hover:border-foreground/30 hover:bg-muted focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring active:scale-[0.98]"
              >
                {opt}
              </button>
            ))}
            {!showComposer && (
              <button
                type="button"
                onClick={revealComposer}
                className="inline-flex min-h-11 cursor-pointer items-center gap-1.5 rounded-full border border-dashed border-border px-4 text-sm font-medium text-muted-foreground transition-colors hover:border-foreground/30 hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              >
                <Pencil className="h-3.5 w-3.5" />
                Add note / comment
              </button>
            )}
          </div>
        </div>
      )}

      {composerVisible && (
        <form
          onSubmit={onSubmit}
          className={optionsActive ? "shrink-0 pt-2" : "shrink-0 border-t border-border pt-3"}
        >
          <label htmlFor={inputId} className="sr-only">
            Your answer to the setup assistant
          </label>
          <div className="flex items-end gap-2">
            <textarea
              id={inputId}
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void runTurn(input);
                }
              }}
              placeholder={optionsActive ? "Add a note or your own answer…" : "Type your answer…"}
              rows={1}
              disabled={loading}
              className="min-h-11 max-h-32 flex-1 resize-none rounded-md border border-input bg-background px-3 py-2.5 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring disabled:opacity-60"
            />
            <button
              type="submit"
              disabled={loading || !input.trim()}
              className="inline-flex h-11 w-11 shrink-0 cursor-pointer items-center justify-center rounded-md bg-foreground text-background transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-default disabled:opacity-40"
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
      )}
    </div>
  );
}
