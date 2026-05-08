"use client";

/**
 * Always-available help chat. A header trigger opens a side panel that talks
 * to /api/ai/help; the AI answers conceptual questions in markdown and drives
 * tours via show_how_to (which the server emits as `navigate` events).
 *
 * Mount once globally (in the protected header). The trigger lives in the
 * header; the panel is portal-style fixed-positioned.
 */

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { createPortal } from "react-dom";
import { useRouter } from "next/navigation";
import { Bot, Loader2, Send, Sparkles, X } from "lucide-react";
import ReactMarkdown from "react-markdown";

import {
  RUN_TOUR_EVENT,
  type RunTourEventDetail,
} from "@/app/protected/_components/page-tour";
import { TOURS } from "@/app/protected/_components/tour-configs";
import type { TourKey } from "@/app/actions/onboarding";

type ChatMessage = { role: "user" | "assistant"; content: string };

const PROMPT_CHIPS = [
  "How do I create a screening?",
  "How do I add a ticker to a screening?",
  "How do I schedule an AI agent?",
  "How do I connect Telegram?",
];

/**
 * Module-level pub/sub so HelpChatTrigger (which may live inside a transient
 * surface like the mobile nav drawer) can open the panel without owning the
 * panel's mount. The panel is mounted by HelpChatRoot at the layout level and
 * survives the trigger being unmounted.
 */
type Listener = (open: boolean) => void;
const helpChatListeners = new Set<Listener>();
function emitHelpChat(open: boolean) {
  helpChatListeners.forEach((l) => l(open));
}
export function openHelpChat() {
  emitHelpChat(true);
}
export function closeHelpChat() {
  emitHelpChat(false);
}

export function HelpChatTrigger({ className = "" }: { className?: string }) {
  return (
    <button
      type="button"
      onClick={() => {
        // Don't stop propagation — the mobile nav drawer wraps the trigger
        // in <li onClick={close}> and we want that to fire too so the drawer
        // collapses while the help panel opens.
        openHelpChat();
      }}
      className={
        className ||
        "inline-flex items-center gap-1.5 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground cursor-pointer"
      }
      aria-label="Open help chat"
    >
      <Sparkles className="h-3.5 w-3.5" />
      Ask AI
    </button>
  );
}

/**
 * Mount once at the protected layout level. Owns the panel state and renders
 * the panel via portal regardless of where the trigger fired from.
 */
export function HelpChatRoot() {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const listener: Listener = (next) => setOpen(next);
    helpChatListeners.add(listener);
    return () => {
      helpChatListeners.delete(listener);
    };
  }, []);

  // Keep <body> from scrolling while the panel is open.
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  // Esc closes the panel.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  if (!open) return null;
  return <HelpChatPanel onClose={() => setOpen(false)} />;
}

function HelpChatPanel({ onClose }: { onClose: () => void }) {
  const router = useRouter();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [mounted, setMounted] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Portal target only exists in the browser; gate rendering on mount so SSR
  // doesn't try to access document.body.
  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, loading]);

  useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

  const send = useCallback(
    async (prompt: string) => {
      const trimmed = prompt.trim();
      if (!trimmed || loading) return;

      const next: ChatMessage[] = [
        ...messages,
        { role: "user", content: trimmed },
        { role: "assistant", content: "" },
      ];
      setMessages(next);
      setInput("");
      setLoading(true);

      const controller = new AbortController();
      abortRef.current = controller;

      try {
        const res = await fetch("/api/ai/help", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            messages: next.slice(0, -1).map((m) => ({
              role: m.role,
              content: m.content,
            })),
            currentRoute:
              typeof window !== "undefined"
                ? window.location.pathname + window.location.search
                : undefined,
          }),
          signal: controller.signal,
        });

        if (!res.ok || !res.body) {
          const errText = await res.text().catch(() => res.statusText);
          setMessages((prev) => {
            const copy = [...prev];
            copy[copy.length - 1] = {
              role: "assistant",
              content: `Error: ${errText || "request failed"}`,
            };
            return copy;
          });
          return;
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buf = "";
        let assistantContent = "";

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
              assistantContent =
                typeof msg.content === "string" ? msg.content : "";
              setMessages((prev) => {
                const copy = [...prev];
                copy[copy.length - 1] = {
                  role: "assistant",
                  content: assistantContent,
                };
                return copy;
              });
            } else if (msg.type === "navigate") {
              const url = typeof msg.url === "string" ? msg.url : "";
              const reply =
                typeof msg.reply === "string" && msg.reply.trim()
                  ? msg.reply.trim()
                  : `Highlighting it now.`;
              assistantContent = reply;
              setMessages((prev) => {
                const copy = [...prev];
                copy[copy.length - 1] = {
                  role: "assistant",
                  content: assistantContent,
                };
                return copy;
              });
              if (url.startsWith("/")) {
                // Resolve the destination tourKey by matching the URL pathname
                // against TOURS[*].route. If we're already on that page, skip
                // navigation and dispatch a run-tour event so PageTour can
                // re-highlight in place. Otherwise, navigate.
                const dest = new URL(url, window.location.origin);
                const stepStr = dest.searchParams.get("step");
                const endStr = dest.searchParams.get("end");
                const fromStep = stepStr
                  ? Math.max(0, parseInt(stepStr, 10))
                  : undefined;
                const toStep = endStr
                  ? Math.max(0, parseInt(endStr, 10))
                  : undefined;
                const matchedKey = (Object.values(TOURS).find(
                  (t) => t.route === dest.pathname,
                )?.key ?? null) as TourKey | null;
                const samePathname =
                  dest.pathname === window.location.pathname;

                if (samePathname && matchedKey) {
                  const detail: RunTourEventDetail = {
                    tourKey: matchedKey,
                    fromStep,
                    toStep,
                  };
                  setTimeout(() => {
                    window.dispatchEvent(
                      new CustomEvent(RUN_TOUR_EVENT, { detail }),
                    );
                    onClose();
                  }, 400);
                } else {
                  // Defer slightly so the user reads the reply before the
                  // route change yanks them away.
                  setTimeout(() => {
                    router.push(url);
                    onClose();
                  }, 400);
                }
              }
            } else if (msg.type === "error") {
              setMessages((prev) => {
                const copy = [...prev];
                copy[copy.length - 1] = {
                  role: "assistant",
                  content: `Error: ${String(msg.message)}`,
                };
                return copy;
              });
            }
          }
        }
      } catch (err) {
        if (err instanceof Error && err.name === "AbortError") return;
        setMessages((prev) => {
          const copy = [...prev];
          copy[copy.length - 1] = {
            role: "assistant",
            content: `Error: ${err instanceof Error ? err.message : String(err)}`,
          };
          return copy;
        });
      } finally {
        setLoading(false);
      }
    },
    [loading, messages, router, onClose],
  );

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void send(input);
  }

  if (!mounted) return null;

  return createPortal(
    <>
      {/* Backdrop — sits above the sticky header (z-50) so the chat surface
          is the dominant focus, not the page chrome. */}
      <div
        className="fixed inset-0 z-[60] bg-black/40 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden
      />

      {/* Side panel — desktop right rail / mobile full-screen.
          Rendered via portal directly under <body> so the header's stacking
          context can't trap it underneath. */}
      <aside
        role="dialog"
        aria-label="Help chat"
        className="fixed inset-y-0 right-0 z-[70] flex w-full max-w-md flex-col border-l border-border bg-background shadow-2xl"
      >
        <header className="flex shrink-0 items-center justify-between border-b border-border px-4 py-3">
          <div className="flex items-center gap-2">
            <Bot className="h-4 w-4 text-amber-500" />
            <span className="text-sm font-semibold">Ask AI</span>
            <span className="text-[10px] font-mono uppercase tracking-[0.14em] text-muted-foreground">
              Help
            </span>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close help"
            className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
          <div className="flex-1 overflow-y-auto px-4 py-4">
            {messages.length === 0 && (
              <div className="flex flex-col gap-3">
                <p className="text-sm text-muted-foreground">
                  Ask how to do anything in the platform — I'll walk you through it.
                </p>
                <div className="flex flex-col gap-1.5">
                  {PROMPT_CHIPS.map((chip) => (
                    <button
                      key={chip}
                      type="button"
                      onClick={() => void send(chip)}
                      className="rounded-md border border-border bg-card px-3 py-2 text-left text-xs text-foreground/90 transition-colors hover:border-foreground/40 hover:bg-muted"
                    >
                      {chip}
                    </button>
                  ))}
                </div>
              </div>
            )}

            <ul className="flex flex-col gap-3">
              {messages.map((m, i) => (
                <li
                  key={i}
                  className={
                    m.role === "user"
                      ? "self-end max-w-[85%] rounded-lg bg-foreground/10 px-3 py-2 text-sm"
                      : "self-start max-w-[90%] rounded-lg border border-border bg-card px-3 py-2 text-sm"
                  }
                >
                  {m.role === "assistant" && !m.content && loading ? (
                    <span className="inline-flex items-center gap-2 text-muted-foreground">
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      Thinking…
                    </span>
                  ) : m.role === "assistant" ? (
                    <div className="prose prose-sm dark:prose-invert max-w-none [&_p]:my-1 [&_ul]:my-1 [&_li]:my-0">
                      <ReactMarkdown>{m.content}</ReactMarkdown>
                    </div>
                  ) : (
                    <p className="whitespace-pre-wrap">{m.content}</p>
                  )}
                </li>
              ))}
            </ul>
            <div ref={bottomRef} />
          </div>

          <form
            onSubmit={onSubmit}
            className="shrink-0 border-t border-border bg-background px-3 py-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]"
          >
            <div className="flex items-end gap-2">
              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    void send(input);
                  }
                }}
                placeholder="How do I…"
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
      </aside>
    </>,
    document.body,
  );
}
