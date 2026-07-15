"use client";

import { useEffect, useId, useState, useTransition } from "react";
import { Check } from "lucide-react";
import { captureAttribution, getAttribution } from "@/lib/attribution";
import { trackLead } from "@/lib/pixels";
import { track } from "@/lib/analytics/events";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";

export type SubscribeScreeningOption = { slug: string; name: string };

type Props = {
  /** Trigger element (rendered via DialogTrigger asChild). */
  trigger: React.ReactNode;
  /**
   * Pre-scope the subscription to one screening. When omitted, the modal shows
   * a multi-select of `screenings`.
   */
  screeningSlug?: string;
  /** Display name for the pre-scoped screening (used in the copy). */
  screeningName?: string;
  /** Options for the multi-select when no `screeningSlug` is provided. */
  screenings?: SubscribeScreeningOption[];
  /** Attribution label persisted with the subscription. */
  source?: string;
};

type Status =
  | { kind: "idle" }
  | { kind: "error"; message: string }
  | { kind: "success" };

const ERROR_COPY: Record<string, string> = {
  invalid_email: "That email doesn't look right. Check it and try again.",
  invalid_request: "Pick at least one screening to follow.",
  send_failed: "We couldn't send the confirmation. Please try again.",
  network: "Something went wrong. Please try again.",
};

export function EmailSubscribeModal({
  trigger,
  screeningSlug,
  screeningName,
  screenings = [],
  source = "email_subscribe",
}: Props) {
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [selected, setSelected] = useState<string[]>(
    screeningSlug ? [screeningSlug] : [],
  );
  const [status, setStatus] = useState<Status>({ kind: "idle" });
  const [isPending, startTransition] = useTransition();

  const emailId = useId();
  const isMultiSelect = !screeningSlug;

  useEffect(() => captureAttribution(), []); // first-touch, from the ad URL

  const reset = () => {
    setEmail("");
    setSelected(screeningSlug ? [screeningSlug] : []);
    setStatus({ kind: "idle" });
  };

  const toggleScreening = (slug: string) => {
    setSelected((prev) =>
      prev.includes(slug) ? prev.filter((s) => s !== slug) : [...prev, slug],
    );
  };

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    setStatus({ kind: "idle" });

    const utm_content = getAttribution().utm_content;
    track("lead_form_submitted", { magnet: "market_screening", utm_content });

    const slugs = screeningSlug ? [screeningSlug] : selected;
    if (slugs.length === 0) {
      setStatus({ kind: "error", message: ERROR_COPY.invalid_request });
      track("lead_form_error", { magnet: "market_screening", reason: "no_screening_selected" });
      return;
    }

    startTransition(async () => {
      try {
        const res = await fetch("/api/subscribe", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            email,
            screeningSlugs: slugs,
            source,
            attribution: getAttribution(),
          }),
        });
        const data = (await res.json().catch(() => ({}))) as {
          success?: boolean;
          error?: string;
        };

        // already_subscribed is a success from the user's perspective.
        if (data.success || data.error === "already_subscribed") {
          trackLead({ content_name: "market_screening" });
          track("lead_subscribed", { magnet: "market_screening", utm_content });
          setStatus({ kind: "success" });
          return;
        }
        const message =
          ERROR_COPY[data.error ?? "network"] ?? ERROR_COPY.network;
        // Do not clear the email field on error.
        setStatus({ kind: "error", message });
        track("lead_form_error", { magnet: "market_screening", reason: data.error ?? "network" });
      } catch {
        setStatus({ kind: "error", message: ERROR_COPY.network });
        track("lead_form_error", { magnet: "market_screening", reason: "network" });
      }
    });
  };

  const title = screeningName
    ? `Get ${screeningName} results`
    : "Get results in your inbox";

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (next) {
          track("lead_form_viewed", {
            magnet: "market_screening",
            utm_content: getAttribution().utm_content,
            preset: Boolean(screeningSlug),
          });
        } else {
          reset();
        }
      }}
    >
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>
            {screeningName ? (
              <>
                Drop your email and we&rsquo;ll send{" "}
                <span className="font-medium text-foreground">
                  {screeningName}
                </span>{" "}
                results on schedule — plus the latest run right now.
              </>
            ) : (
              "Choose the screenings to follow. We'll email results on schedule, with the latest run attached."
            )}
          </DialogDescription>
        </DialogHeader>

        {status.kind === "success" ? (
          <div className="space-y-4 py-2">
            <div className="flex items-center gap-2 text-sm text-foreground">
              <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-emerald-500/15 text-emerald-400">
                <Check className="h-3.5 w-3.5" />
              </span>
              Check your inbox — first results land on schedule.
            </div>
            <DialogFooter>
              <Button variant="secondary" onClick={() => setOpen(false)}>
                Close
              </Button>
            </DialogFooter>
          </div>
        ) : (
          <form className="space-y-4" onSubmit={submit}>
            {isMultiSelect && (
              <fieldset className="space-y-2">
                <legend className="text-sm font-medium text-foreground">
                  Screenings
                </legend>
                <div className="max-h-52 space-y-1 overflow-y-auto rounded-md border border-border/70 p-1">
                  {screenings.length === 0 ? (
                    <p className="px-2 py-3 text-sm text-muted-foreground">
                      No screenings available right now.
                    </p>
                  ) : (
                    screenings.map((s) => {
                      const checked = selected.includes(s.slug);
                      return (
                        <label
                          key={s.slug}
                          className="flex cursor-pointer items-center gap-2.5 rounded-md px-2 py-2 text-sm transition-colors hover:bg-muted/50"
                        >
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={() => toggleScreening(s.slug)}
                            className="h-4 w-4 shrink-0 accent-primary"
                          />
                          <span className="text-foreground">{s.name}</span>
                        </label>
                      );
                    })
                  )}
                </div>
              </fieldset>
            )}

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
                aria-label="Email address"
                aria-invalid={status.kind === "error"}
                required
                disabled={isPending}
              />
            </div>

            {status.kind === "error" && (
              <p role="alert" className="text-sm text-destructive">
                {status.message}
              </p>
            )}

            <DialogFooter>
              <Button type="submit" disabled={isPending || !email}>
                {isPending ? "Sending…" : "Send me the results →"}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
