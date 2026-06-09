"use client";

import { useId, useState, useTransition } from "react";
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
} from "@/components/ui/dialog";

type Props = {
  href: string;
  screeningSlug: string;
  screeningName: string;
  download?: boolean;
  external?: boolean;
  className?: string;
  title?: string;
  source?: string;
  children: React.ReactNode;
};

type Status =
  | { kind: "idle" }
  | { kind: "error"; message: string }
  | { kind: "success" };

const ERROR_COPY: Record<string, string> = {
  invalid_email: "That email doesn't look right. Check it and try again.",
  invalid_request: "Something went wrong. Please try again.",
  send_failed: "We couldn't send the confirmation. Please try again.",
  network: "Something went wrong. Please try again.",
};

/**
 * A download/JSON link that first asks the user whether they'd like the
 * results delivered by email whenever a new run is ready. They can subscribe
 * inline or proceed straight to the download.
 */
export function DeliveryPromptLink({
  href,
  screeningSlug,
  screeningName,
  download,
  external,
  className,
  title,
  source = "download_prompt",
  children,
}: Props) {
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<Status>({ kind: "idle" });
  const [isPending, startTransition] = useTransition();
  const emailId = useId();

  const proceedToDownload = () => {
    setOpen(false);
    if (external) {
      window.open(href, "_blank", "noopener,noreferrer");
      return;
    }
    const a = document.createElement("a");
    a.href = href;
    if (download) a.setAttribute("download", "");
    document.body.appendChild(a);
    a.click();
    a.remove();
  };

  const subscribe = (e: React.FormEvent) => {
    e.preventDefault();
    setStatus({ kind: "idle" });
    startTransition(async () => {
      try {
        const res = await fetch("/api/subscribe", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            email,
            screeningSlugs: [screeningSlug],
            source,
          }),
        });
        const data = (await res.json().catch(() => ({}))) as {
          success?: boolean;
          error?: string;
        };
        if (data.success || data.error === "already_subscribed") {
          setStatus({ kind: "success" });
          return;
        }
        setStatus({
          kind: "error",
          message: ERROR_COPY[data.error ?? "network"] ?? ERROR_COPY.network,
        });
      } catch {
        setStatus({ kind: "error", message: ERROR_COPY.network });
      }
    });
  };

  const downloadLabel = external ? "Just open JSON" : "Just download";

  return (
    <>
      <a
        href={href}
        title={title}
        aria-label={title}
        className={className}
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          setStatus({ kind: "idle" });
          setOpen(true);
        }}
      >
        {children}
      </a>

      <Dialog
        open={open}
        onOpenChange={(next) => {
          setOpen(next);
          if (!next) {
            setEmail("");
            setStatus({ kind: "idle" });
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Get it automatically?</DialogTitle>
            <DialogDescription>
              Want{" "}
              <span className="font-medium text-foreground">
                {screeningName}
              </span>{" "}
              delivered by email whenever a new run is ready? We&rsquo;ll attach
              the latest results each time.
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
                <Button onClick={proceedToDownload}>
                  {external ? "Open JSON now" : "Download now"}
                </Button>
              </DialogFooter>
            </div>
          ) : (
            <form className="space-y-4" onSubmit={subscribe}>
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
                  disabled={isPending}
                />
              </div>

              {status.kind === "error" && (
                <p role="alert" className="text-sm text-destructive">
                  {status.message}
                </p>
              )}

              <DialogFooter className="gap-2 sm:gap-2">
                <Button
                  type="button"
                  variant="secondary"
                  onClick={proceedToDownload}
                >
                  {downloadLabel}
                </Button>
                <Button type="submit" disabled={isPending || !email}>
                  {isPending ? "Sending…" : "Email me new runs →"}
                </Button>
              </DialogFooter>
            </form>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
