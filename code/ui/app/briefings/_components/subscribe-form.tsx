"use client";

import { useEffect, useId, useState, useTransition } from "react";
import { Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { WatchlistPicker } from "./watchlist-picker";
import { captureAttribution, getAttribution } from "@/lib/attribution";
import { trackLead } from "@/lib/pixels";
import { track } from "@/lib/analytics/events";

const ERROR_COPY: Record<string, string> = {
  invalid_email: "That email doesn't look right. Check it and try again.",
  empty_watchlist: "Add at least one ticker or tag to follow.",
  server_error: "Something went wrong on our end. Please try again.",
  invalid_request: "Something went wrong. Please try again.",
  network: "Something went wrong. Please try again.",
};

type Status =
  | { kind: "idle" }
  | { kind: "error"; message: string }
  | { kind: "success" };

export function SubscribeForm({
  source = "briefings_page",
  initialTickers = [],
  initialTags = [],
}: {
  source?: string;
  initialTickers?: string[];
  initialTags?: string[];
}) {
  const emailId = useId();
  const [email, setEmail] = useState("");
  const [tickers, setTickers] = useState<string[]>(initialTickers);
  const [tags, setTags] = useState<string[]>(initialTags);
  const [status, setStatus] = useState<Status>({ kind: "idle" });
  const [isPending, startTransition] = useTransition();

  useEffect(() => {
    captureAttribution(); // first-touch, from the ad URL
    track("lead_form_viewed", {
      magnet: "news_briefing",
      utm_content: getAttribution().utm_content,
      preset: initialTickers.length > 0 || initialTags.length > 0,
    });
  }, [initialTickers.length, initialTags.length]);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    setStatus({ kind: "idle" });
    const utm_content = getAttribution().utm_content;
    track("lead_form_submitted", { magnet: "news_briefing", utm_content });
    if (tickers.length === 0 && tags.length === 0) {
      setStatus({ kind: "error", message: ERROR_COPY.empty_watchlist });
      track("lead_form_error", { magnet: "news_briefing", reason: "empty_watchlist" });
      return;
    }
    startTransition(async () => {
      try {
        const res = await fetch("/api/briefings/subscribe", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            email,
            tickers,
            tags,
            source,
            attribution: getAttribution(),
          }),
        });
        const data = (await res.json().catch(() => ({}))) as {
          success?: boolean;
          error?: string;
        };
        if (data.success) {
          trackLead({ content_name: "news_briefing" });
          track("lead_subscribed", { magnet: "news_briefing", utm_content });
          setStatus({ kind: "success" });
          return;
        }
        setStatus({
          kind: "error",
          message: ERROR_COPY[data.error ?? "network"] ?? ERROR_COPY.network,
        });
        track("lead_form_error", { magnet: "news_briefing", reason: data.error ?? "network" });
      } catch {
        setStatus({ kind: "error", message: ERROR_COPY.network });
        track("lead_form_error", { magnet: "news_briefing", reason: "network" });
      }
    });
  };

  if (status.kind === "success") {
    return (
      <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-6">
        <div className="flex items-center gap-2 text-foreground">
          <span className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-emerald-500/15 text-emerald-400">
            <Check className="h-4 w-4" />
          </span>
          <span className="font-medium">You&rsquo;re in — check your inbox.</span>
        </div>
        <p className="mt-3 text-sm text-muted-foreground">
          Your first briefing PDF is being generated right now and lands in a
          minute or two. After that you&rsquo;ll get one every weekday, an hour
          before the market opens. Use the link in any email to edit your
          tickers and tags or unsubscribe — no account needed.
        </p>
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="space-y-5">
      <WatchlistPicker
        tickers={tickers}
        tags={tags}
        onChange={({ tickers: t, tags: g }) => {
          setTickers(t);
          setTags(g);
        }}
      />

      <div className="space-y-2">
        <Label htmlFor={emailId}>Email</Label>
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
          aria-invalid={status.kind === "error"}
        />
      </div>

      {status.kind === "error" && (
        <p role="alert" className="text-sm text-destructive">
          {status.message}
        </p>
      )}

      <Button type="submit" className="w-full sm:w-auto" disabled={isPending || !email}>
        {isPending ? "Setting up…" : "Send my first briefing →"}
      </Button>
      <p className="text-xs text-muted-foreground">
        Free forever. One email a day, max. Unsubscribe in one click.
      </p>
    </form>
  );
}
