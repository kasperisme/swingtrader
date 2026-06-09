"use client";

import { useState, useTransition } from "react";
import { Check } from "lucide-react";

/**
 * Soft, low-friction email capture aimed at cold organic (SEO) arrivals — shown
 * just before the early-access gate. Posts to /api/subscribe with the momentum
 * screening as the default list, so a single email both captures the lead and
 * starts the scheduled-results email. Email-only, no account required.
 *
 * The parent only renders this for logged-out visitors (authenticated users
 * already have the data), so there's no auth check here.
 */
const ERROR_COPY: Record<string, string> = {
  invalid_email: "That email doesn't look right. Check it and try again.",
  invalid_request: "Something went wrong. Please try again.",
  network: "Network error. Please try again.",
};

export function MidPageEmailCapture({
  screeningSlugs = ["nis-momentum"],
  source = "article_mid_capture",
}: {
  screeningSlugs?: string[];
  source?: string;
}) {
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<"idle" | "success" | "error">("idle");
  const [message, setMessage] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    setStatus("idle");
    setMessage(null);
    startTransition(async () => {
      try {
        const res = await fetch("/api/subscribe", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email: email.trim(), screeningSlugs, source }),
        });
        const data = (await res.json().catch(() => ({}))) as {
          success?: boolean;
          error?: string;
        };
        // already_subscribed reads as success from the visitor's perspective.
        if (data.success || data.error === "already_subscribed") {
          setStatus("success");
          setEmail("");
          return;
        }
        setStatus("error");
        setMessage(ERROR_COPY[data.error ?? "network"] ?? ERROR_COPY.network);
      } catch {
        setStatus("error");
        setMessage(ERROR_COPY.network);
      }
    });
  };

  return (
    <section className="rounded-2xl border border-border/60 bg-card/30 p-6 sm:p-7">
      <h3 className="max-w-2xl text-lg font-semibold leading-snug tracking-tight text-foreground">
        Get the impacted ticker list for every major market story
      </h3>
      <p className="mt-1 text-sm text-muted-foreground">Free. No credit card.</p>

      {status === "success" ? (
        <div className="mt-4 flex items-center gap-2 text-sm text-foreground">
          <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-emerald-500/15 text-emerald-400">
            <Check className="h-3.5 w-3.5" />
          </span>
          Check your inbox — the list is on its way.
        </div>
      ) : (
        <form onSubmit={submit} className="mt-4 flex flex-col gap-3 sm:flex-row">
          <label htmlFor="mid-page-capture-email" className="sr-only">
            Email address
          </label>
          <input
            id="mid-page-capture-email"
            name="email"
            type="email"
            inputMode="email"
            required
            autoComplete="email"
            disabled={isPending}
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.com"
            aria-invalid={status === "error"}
            className="h-11 w-full rounded-xl border border-border bg-card px-4 text-sm outline-none transition focus-visible:border-primary disabled:opacity-60 sm:max-w-xs"
          />
          <button
            type="submit"
            disabled={isPending || !email}
            className="inline-flex h-11 cursor-pointer items-center justify-center rounded-xl bg-violet-600 px-5 text-sm font-semibold text-white transition-colors hover:bg-violet-500 disabled:pointer-events-none disabled:opacity-60"
          >
            {isPending ? "Sending…" : "Send me the list →"}
          </button>
        </form>
      )}

      {status === "error" && message ? (
        <p role="alert" className="mt-3 text-sm text-destructive">
          {message}
        </p>
      ) : null}
    </section>
  );
}
