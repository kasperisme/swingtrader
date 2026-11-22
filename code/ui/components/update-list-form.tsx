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
export const ARENA_SUBSCRIBED_KEY = "nis:arena-subscribed";

type ListConfig = {
  magnet: "correction" | "arena";
  endpoint: string;
  storageKey: string;
  button: string;
  compactButton: string;
  done: string;
  hint: string;
};

const LISTS: Record<ListConfig["magnet"], ListConfig> = {
  correction: {
    magnet: "correction",
    endpoint: "/api/correction/subscribe",
    storageKey: CORRECTION_SUBSCRIBED_KEY,
    button: "Email me new analyses",
    compactButton: "Notify me",
    done: "You\u2019re on the list. We\u2019ll email you when the next analysis is out.",
    hint: "One email per new analysis. Unsubscribe in one click.",
  },
  arena: {
    magnet: "arena",
    endpoint: "/api/arena/subscribe",
    storageKey: ARENA_SUBSCRIBED_KEY,
    button: "Email me the daily table",
    compactButton: "Subscribe",
    done: "You\u2019re on the list. The standings and trades land after the next session.",
    hint: "One email per trading session. Unsubscribe in one click.",
  },
};

/** Correction stress-test updates: one mail per new analysis. */
export function CorrectionSubscribeForm(props: { source: string; compact?: boolean; onSubscribed?: () => void }) {
  return <UpdateListForm list="correction" {...props} />;
}

/** The Arena daily digest: standings + the day's trades, after each session. */
export function ArenaSubscribeForm(props: { source: string; compact?: boolean; onSubscribed?: () => void }) {
  return <UpdateListForm list="arena" {...props} />;
}

/**
 * Email-only signup for an update list. Same funnel events as the other lead
 * magnets (magnet = the list).
 */
function UpdateListForm({
  list,
  source,
  compact = false,
  onSubscribed,
}: {
  list: ListConfig["magnet"];
  source: string;
  compact?: boolean;
  onSubscribed?: () => void;
}) {
  const cfg = LISTS[list];
  const magnet = cfg.magnet;
  const emailId = useId();
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [isPending, startTransition] = useTransition();

  useEffect(() => {
    captureAttribution();
    track("lead_form_viewed", { magnet, utm_content: getAttribution().utm_content });
  }, [magnet]);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    const utm_content = getAttribution().utm_content;
    track("lead_form_submitted", { magnet, utm_content });
    startTransition(async () => {
      try {
        const res = await fetch(cfg.endpoint, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email, source, attribution: getAttribution() }),
        });
        const data = (await res.json().catch(() => ({}))) as { success?: boolean; error?: string };
        if (data.success) {
          trackLead({ content_name: magnet });
          track("lead_subscribed", { magnet, utm_content });
          try {
            localStorage.setItem(cfg.storageKey, "1");
          } catch {
            /* storage blocked: the promo may ask again, nothing breaks */
          }
          setDone(true);
          onSubscribed?.();
          return;
        }
        const reason = data.error ?? "network";
        setError(ERROR_COPY[reason] ?? ERROR_COPY.network);
        track("lead_form_error", { magnet, reason });
      } catch {
        setError(ERROR_COPY.network);
        track("lead_form_error", { magnet, reason: "network" });
      }
    });
  };

  if (done) {
    return (
      <div className="flex items-start gap-2 text-sm text-foreground">
        <span className="mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-emerald-500/15 text-emerald-500">
          <Check className="h-3.5 w-3.5" />
        </span>
        <span>{cfg.done}</span>
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
          {isPending ? "Adding…" : compact ? cfg.compactButton : cfg.button}
        </Button>
      </div>
      {error ? (
        <p role="alert" className="text-xs text-destructive">
          {error}
        </p>
      ) : (
        <p className="text-xs text-muted-foreground">{cfg.hint}</p>
      )}
    </form>
  );
}
