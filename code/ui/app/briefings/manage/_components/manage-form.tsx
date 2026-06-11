"use client";

import { useState, useTransition } from "react";
import { Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { WatchlistPicker } from "../../_components/watchlist-picker";

type Status =
  | { kind: "idle" }
  | { kind: "saved" }
  | { kind: "unsubscribed" }
  | { kind: "error"; message: string };

export function ManageForm({
  token,
  email,
  initialTickers,
  initialTags,
  initialStatus,
}: {
  token: string;
  email: string;
  initialTickers: string[];
  initialTags: string[];
  initialStatus: "active" | "unsubscribed";
}) {
  const [tickers, setTickers] = useState<string[]>(initialTickers);
  const [tags, setTags] = useState<string[]>(initialTags);
  const [status, setStatus] = useState<Status>({ kind: "idle" });
  const [isPending, startTransition] = useTransition();

  const post = (body: Record<string, unknown>, onOk: () => void) => {
    startTransition(async () => {
      try {
        const res = await fetch("/api/briefings/manage", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ token, ...body }),
        });
        const data = (await res.json().catch(() => ({}))) as {
          success?: boolean;
          error?: string;
        };
        if (data.success) onOk();
        else
          setStatus({
            kind: "error",
            message:
              data.error === "empty_watchlist"
                ? "Add at least one ticker or tag."
                : data.error === "invalid_token"
                  ? "This link has expired. Open the link from your latest email."
                  : "Something went wrong. Please try again.",
          });
      } catch {
        setStatus({ kind: "error", message: "Something went wrong. Please try again." });
      }
    });
  };

  const save = () => {
    if (tickers.length === 0 && tags.length === 0) {
      setStatus({ kind: "error", message: "Add at least one ticker or tag." });
      return;
    }
    post({ action: "update", tickers, tags }, () => setStatus({ kind: "saved" }));
  };

  const unsubscribe = () =>
    post({ action: "unsubscribe" }, () => setStatus({ kind: "unsubscribed" }));

  if (status.kind === "unsubscribed") {
    return (
      <div className="rounded-xl border border-border bg-card p-6">
        <p className="font-medium text-foreground">You&rsquo;ve been unsubscribed.</p>
        <p className="mt-2 text-sm text-muted-foreground">
          You won&rsquo;t get the daily briefing anymore. Changed your mind? Add
          your tickers back and hit save.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="text-sm text-muted-foreground">
        Editing the briefing for{" "}
        <span className="font-medium text-foreground">{email}</span>
        {initialStatus === "unsubscribed" && (
          <span className="ml-2 rounded-full bg-muted px-2 py-0.5 text-xs">
            currently unsubscribed — saving re-activates it
          </span>
        )}
      </div>

      <WatchlistPicker
        tickers={tickers}
        tags={tags}
        onChange={({ tickers: t, tags: g }) => {
          setTickers(t);
          setTags(g);
          if (status.kind === "saved") setStatus({ kind: "idle" });
        }}
      />

      {status.kind === "error" && (
        <p role="alert" className="text-sm text-destructive">
          {status.message}
        </p>
      )}
      {status.kind === "saved" && (
        <p className="flex items-center gap-2 text-sm text-emerald-500">
          <Check className="h-4 w-4" /> Saved. Your next briefing uses the new list.
        </p>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <Button onClick={save} disabled={isPending}>
          {isPending ? "Saving…" : "Save changes"}
        </Button>
        <Button
          variant="ghost"
          onClick={unsubscribe}
          disabled={isPending}
          className="text-muted-foreground hover:text-destructive"
        >
          Unsubscribe
        </Button>
      </div>
    </div>
  );
}
