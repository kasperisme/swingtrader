"use client";

import { useState, useTransition } from "react";
import { Check } from "lucide-react";
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
import {
  submitEarlyAccessSignup,
  subscribeToPublicScreening,
  unsubscribeFromPublicScreening,
} from "@/app/actions/public-screenings";

type Props = {
  screeningSlug: string;
  screeningName: string;
  isAuthed: boolean;
  initialSubscribed: boolean;
};

export function SubscribeButton({
  screeningSlug,
  screeningName,
  isAuthed,
  initialSubscribed,
}: Props) {
  if (!isAuthed) {
    return (
      <EarlyAccessButton
        screeningSlug={screeningSlug}
        screeningName={screeningName}
      />
    );
  }
  return (
    <AuthedSubscribeButton
      screeningSlug={screeningSlug}
      initialSubscribed={initialSubscribed}
    />
  );
}

// ── Authed: one-click subscribe / unsubscribe ───────────────────────────────

function AuthedSubscribeButton({
  screeningSlug,
  initialSubscribed,
}: {
  screeningSlug: string;
  initialSubscribed: boolean;
}) {
  const [subscribed, setSubscribed] = useState(initialSubscribed);
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  const toggle = () => {
    setError(null);
    // Optimistic flip.
    const next = !subscribed;
    setSubscribed(next);
    startTransition(async () => {
      const res = next
        ? await subscribeToPublicScreening(screeningSlug)
        : await unsubscribeFromPublicScreening(screeningSlug);
      if (!res.ok) {
        setSubscribed(!next);
        setError(res.error);
      }
    });
  };

  return (
    <div className="space-y-2">
      <Button
        size="lg"
        variant={subscribed ? "secondary" : "default"}
        onClick={toggle}
        disabled={isPending}
      >
        {subscribed ? (
          <>
            <Check className="mr-2 h-4 w-4" />
            Subscribed
          </>
        ) : (
          "Subscribe"
        )}
      </Button>
      {subscribed && (
        <p className="text-xs text-muted-foreground">
          You’ll receive results via Telegram (if connected) and in-app.
          Click again to unsubscribe.
        </p>
      )}
      {error && <p className="text-sm text-destructive">{error}</p>}
    </div>
  );
}

// ── Anonymous: early-access email capture ───────────────────────────────────

type EarlyAccessStatus =
  | { kind: "idle" }
  | { kind: "error"; message: string }
  | { kind: "success"; alreadySignedUp: boolean };

function EarlyAccessButton({
  screeningSlug,
  screeningName,
}: {
  screeningSlug: string;
  screeningName: string;
}) {
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<EarlyAccessStatus>({ kind: "idle" });
  const [isPending, startTransition] = useTransition();

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    setStatus({ kind: "idle" });
    startTransition(async () => {
      const res = await submitEarlyAccessSignup({
        email,
        screeningSlug,
        source: "gallery_subscribe",
      });
      if (res.ok) {
        setStatus({
          kind: "success",
          alreadySignedUp: res.data.alreadySignedUp,
        });
      } else {
        setStatus({ kind: "error", message: res.error });
      }
    });
  };

  const reset = () => {
    setEmail("");
    setStatus({ kind: "idle" });
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) reset();
      }}
    >
      <DialogTrigger asChild>
        <Button size="lg">Subscribe</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Request early access</DialogTitle>
          <DialogDescription>
            Public screenings are in early access. Drop your email and
            we’ll notify you when subscriptions to{" "}
            <span className="font-medium text-foreground">{screeningName}</span>{" "}
            open.
          </DialogDescription>
        </DialogHeader>

        {status.kind === "success" ? (
          <div className="space-y-3 py-2">
            <p className="text-sm">
              {status.alreadySignedUp
                ? "You’re already on the list — we’ll be in touch."
                : "You’re on the list. We’ll be in touch when access opens."}
            </p>
            <DialogFooter>
              <Button variant="secondary" onClick={() => setOpen(false)}>
                Close
              </Button>
            </DialogFooter>
          </div>
        ) : (
          <form className="space-y-4" onSubmit={submit}>
            <div className="space-y-2">
              <Label htmlFor="early-access-email">Email</Label>
              <Input
                id="early-access-email"
                type="email"
                placeholder="you@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="email"
                required
                disabled={isPending}
              />
            </div>

            {status.kind === "error" && (
              <p className="text-sm text-destructive">{status.message}</p>
            )}

            <DialogFooter>
              <Button type="submit" disabled={isPending || !email}>
                {isPending ? "Submitting…" : "Request early access"}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
