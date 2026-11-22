"use client";

import { useEffect, useId, useState, useTransition } from "react";
import { Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { captureAttribution, getAttribution } from "@/lib/attribution";
import { trackLead } from "@/lib/pixels";
import { track } from "@/lib/analytics/events";

const ERROR_COPY: Record<string, string> = {
  invalid_email: "That email doesn't look right. Check it and try again.",
  server_error: "Something went wrong on our end. Please try again.",
  invalid_request: "Something went wrong. Please try again.",
  network: "Something went wrong. Please try again.",
};

/** Remembered so the site-wide promo stops asking once someone has signed up. */
export const CORRECTION_SUBSCRIBED_KEY = "nis:correction-subscribed";

/**
 * Email-only signup for correction stress-test updates: one mail per new analysis.
 * Same funnel events as the other lead magnets (magnet "correction").
 */
export function CorrectionSubscribeForm({
  source,
  compact = false,
  onSubscribed,
}: {
  source: string;
  compact?: boolean;
  onSubscribed?: () => void;
}) {
  const emailId = useId();
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [isPending, startTransition] = useTransition();

  useEffect(() => {
    captureAttribution();
    track("lead_form_viewed", { magnet: "correction", utm_content: getAttribution().utm_content });
  }, []);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    const utm_content = getAttribution().utm_content;
    track("lead_form_submitted", { magnet: "correction", utm_content });
    startTransition(async () => {
      try {
        const res = await fetch("/api/correction/subscribe", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email, source, attribution: getAttribution() }),
        });
        const data = (await res.json().catch(() => ({}))) as { success?: boolean; error?: string };
        if (data.success) {
          trackLead({ content_name: "correction" });
          track("lead_subscribed", { magnet: "correction", utm_content });
          try {
            localStorage.setItem(CORRECTION_SUBSCRIBED_KEY, "1");
          } catch {
            /* storage blocked: the promo may ask again, nothing breaks */
          }
          setDone(true);
          onSubscribed?.();
          return;
        }
        const reason = data.error ?? "network";
        setError(ERROR_COPY[reason] ?? ERROR_COPY.network);
        track("lead_form_error", { magnet: "correction", reason });
      } catch {
        setError(ERROR_COPY.network);
        track("lead_form_error", { magnet: "correction", reason: "network" });
      }
    });
  };

  if (done) {
    return (
      <div className="flex items-start gap-2 text-sm text-foreground">
        <span className="mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-emerald-500/15 text-emerald-500">
          <Check className="h-3.5 w-3.5" />
        </span>
        <span>You&rsquo;re on the list. We&rsquo;ll email you when the next analysis is out.</span>
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="space-y-2">
      <label htmlFor={emailId} className="sr-only">
        Email
      </label>
      <div className={compact ? "flex gap-2" : "flex flex-col gap-2 sm:flex-row"}>
        <Input
          id={emailId}
          type="email"
          inputMode="email"
          placeholder="you@example.com"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          autoComplete="email"
          required
          disabled={isPending}
          aria-invalid={!!error}
          className="min-w-0 flex-1"
        />
        <Button type="submit" disabled={isPending} className="shrink-0">
          {isPending ? "Adding…" : compact ? "Notify me" : "Email me new analyses"}
        </Button>
      </div>
      {error ? (
        <p role="alert" className="text-xs text-destructive">
          {error}
        </p>
      ) : (
        <p className="text-xs text-muted-foreground">One email per new analysis. Unsubscribe in one click.</p>
      )}
    </form>
  );
}
