"use client";

import { useState, useTransition } from "react";
import { Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { EmailSubscribeModal } from "@/components/EmailSubscribeModal";
import {
  importLatestMarketScreeningResultForMe,
  subscribeToMarketScreening,
  unsubscribeFromMarketScreening,
} from "@/app/actions/market-screenings";

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
    // Anonymous visitors get the lightweight email-delivery subscription:
    // email-only, persisted + a confirmation with the latest results. No
    // "early access" waitlist messaging.
    return (
      <EmailSubscribeModal
        screeningSlug={screeningSlug}
        screeningName={screeningName}
        source="screening_detail_subscribe"
        trigger={<Button size="lg">Subscribe</Button>}
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

type ImportStatus =
  | { kind: "idle" }
  | { kind: "pending" }
  | {
      kind: "done";
      rowCount: number;
      chatTurns: number;
      runAt: string | null;
    }
  | { kind: "no_results" }
  | { kind: "error"; message: string };

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
  const [importPromptOpen, setImportPromptOpen] = useState(false);
  const [importStatus, setImportStatus] = useState<ImportStatus>({
    kind: "idle",
  });

  const toggle = () => {
    setError(null);
    // Optimistic flip.
    const next = !subscribed;
    setSubscribed(next);
    startTransition(async () => {
      if (next) {
        const res = await subscribeToMarketScreening(screeningSlug);
        if (!res.ok) {
          setSubscribed(false);
          setError(res.error);
          return;
        }
        // Only prompt to import after a fresh subscribe (not a duplicate).
        // Re-subscribers see the prompt again on purpose — accepting writes
        // a new scan_run and chat turns.
        if (!res.data.alreadySubscribed) {
          setImportStatus({ kind: "idle" });
          setImportPromptOpen(true);
        }
      } else {
        const res = await unsubscribeFromMarketScreening(screeningSlug);
        if (!res.ok) {
          setSubscribed(true);
          setError(res.error);
        }
      }
    });
  };

  const confirmImport = () => {
    setImportStatus({ kind: "pending" });
    startTransition(async () => {
      try {
        const res = await importLatestMarketScreeningResultForMe(screeningSlug);
        if (!res.ok) {
          setImportStatus({ kind: "error", message: res.error });
          return;
        }
        if (!res.data.imported) {
          setImportStatus({ kind: "no_results" });
          return;
        }
        setImportStatus({
          kind: "done",
          rowCount: res.data.rowCount,
          chatTurns: res.data.chatTurns,
          runAt: res.data.runAt,
        });
      } catch (e) {
        // If the server action throws (e.g. serverless timeout) the dialog
        // would otherwise hang at "pending" forever. Surface an error so
        // the user can retry or close.
        setImportStatus({
          kind: "error",
          message:
            e instanceof Error && e.message
              ? e.message
              : "Import did not complete. Your subscription is saved — try again or close.",
        });
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

      <Dialog
        open={importPromptOpen}
        onOpenChange={(next) => {
          setImportPromptOpen(next);
          if (!next) setImportStatus({ kind: "idle" });
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add the latest results to your screenings?</DialogTitle>
            <DialogDescription>
              You can import the most recent run of this screening into your
              screenings view (and AI chat where analysis is available) so
              you’re caught up immediately. Otherwise you’ll get the next
              scheduled run automatically.
            </DialogDescription>
          </DialogHeader>

          {importStatus.kind === "idle" && (
            <DialogFooter className="gap-2 sm:gap-2">
              <Button
                variant="secondary"
                onClick={() => setImportPromptOpen(false)}
                disabled={isPending}
              >
                No thanks
              </Button>
              <Button onClick={confirmImport} disabled={isPending}>
                Yes, import latest
              </Button>
            </DialogFooter>
          )}

          {importStatus.kind === "pending" && (
            <p className="py-2 text-sm text-muted-foreground">
              Importing the latest run…
            </p>
          )}

          {importStatus.kind === "done" && (
            <div className="space-y-3 py-2">
              <p className="text-sm">
                Imported {importStatus.rowCount} ticker
                {importStatus.rowCount === 1 ? "" : "s"}
                {importStatus.chatTurns > 0
                  ? ` and ${importStatus.chatTurns} AI chat update${importStatus.chatTurns === 1 ? "" : "s"}`
                  : ""}
                {importStatus.runAt
                  ? ` from ${new Date(importStatus.runAt).toLocaleString()}`
                  : ""}
                .
              </p>
              <DialogFooter>
                <Button onClick={() => setImportPromptOpen(false)}>Done</Button>
              </DialogFooter>
            </div>
          )}

          {importStatus.kind === "no_results" && (
            <div className="space-y-3 py-2">
              <p className="text-sm">
                No completed runs yet — you’ll receive the next scheduled run
                automatically.
              </p>
              <DialogFooter>
                <Button onClick={() => setImportPromptOpen(false)}>OK</Button>
              </DialogFooter>
            </div>
          )}

          {importStatus.kind === "error" && (
            <div className="space-y-3 py-2">
              <p className="text-sm text-destructive">{importStatus.message}</p>
              <DialogFooter className="gap-2 sm:gap-2">
                <Button
                  variant="secondary"
                  onClick={() => setImportPromptOpen(false)}
                >
                  Close
                </Button>
                <Button onClick={confirmImport} disabled={isPending}>
                  Retry
                </Button>
              </DialogFooter>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
