"use client";

import { useId, useMemo, useState, useTransition } from "react";
import Link from "next/link";
import { ArrowUpRight, Check, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

/**
 * The sole article-page CTA: subscribe to the free daily news-briefing service,
 * pre-seeded with the tickers and tags this story touches. No account needed.
 * Anchored at #early-access so existing in-page "unlock" links still scroll
 * here. Posts to /api/briefings/subscribe; the first PDF is generated + emailed
 * within a minute.
 */
export function ArticleBriefingCTA({
  tickers,
  tags,
  source = "article_briefing",
}: {
  tickers: string[];
  tags: string[];
  /** Signup attribution channel (e.g. "quote_page"). Defaults to article CTA. */
  source?: string;
}) {
  const emailId = useId();
  const [email, setEmail] = useState("");
  const [selTickers, setSelTickers] = useState<string[]>(tickers.slice(0, 6));
  const [selTags, setSelTags] = useState<string[]>(tags.slice(0, 4));
  const [status, setStatus] = useState<"idle" | "error" | "success">("idle");
  const [message, setMessage] = useState("");
  const [isPending, startTransition] = useTransition();

  const hasWatchlist = selTickers.length > 0 || selTags.length > 0;
  const watchlistLabel = useMemo(
    () =>
      [...selTickers.map((t) => `$${t}`), ...selTags.map((t) => `#${t}`)].join(
        " · ",
      ),
    [selTickers, selTags],
  );

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    setStatus("idle");
    if (!hasWatchlist) {
      setStatus("error");
      setMessage("Keep at least one ticker or tag to follow.");
      return;
    }
    startTransition(async () => {
      try {
        const res = await fetch("/api/briefings/subscribe", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            email,
            tickers: selTickers,
            tags: selTags,
            source,
          }),
        });
        const data = (await res.json().catch(() => ({}))) as {
          success?: boolean;
          error?: string;
        };
        if (data.success) {
          setStatus("success");
          return;
        }
        setStatus("error");
        setMessage(
          data.error === "invalid_email"
            ? "That email doesn't look right. Check it and try again."
            : "Something went wrong. Please try again.",
        );
      } catch {
        setStatus("error");
        setMessage("Something went wrong. Please try again.");
      }
    });
  };

  return (
    <section
      id="early-access"
      className="scroll-mt-24 overflow-hidden rounded-2xl border border-amber-500/30 bg-gradient-to-b from-amber-500/[0.07] to-transparent p-6 sm:p-8"
    >
      <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-amber-500">
        Free · No account
      </p>

      {status === "success" ? (
        <div className="mt-3">
          <div className="flex items-center gap-2 text-foreground">
            <span className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-emerald-500/15 text-emerald-400">
              <Check className="h-4 w-4" />
            </span>
            <span className="text-lg font-semibold">
              You&rsquo;re in — check your inbox.
            </span>
          </div>
          <p className="mt-3 max-w-prose text-sm leading-relaxed text-muted-foreground">
            Your first briefing PDF is being generated now and lands in a minute
            or two. After that you&rsquo;ll get one every weekday, an hour before
            the market opens. Edit your tickers and tags or unsubscribe from any
            email — no account needed.
          </p>
        </div>
      ) : (
        <>
          <h2 className="mt-3 text-2xl font-bold leading-tight tracking-tight">
            Track {watchlistLabel ? "these names" : "the news"} every morning.
          </h2>
          <p className="mt-2 max-w-prose text-sm leading-relaxed text-muted-foreground">
            Get a free daily PDF briefing — the last 24 hours of news, with
            summaries and the market-impact score for each story, delivered an
            hour before the open.
          </p>

          {hasWatchlist ? (
            <div className="mt-5">
              <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                We&rsquo;ll watch
              </p>
              <div className="flex flex-wrap gap-2">
                {selTickers.map((t) => (
                  <Chip
                    key={`tk-${t}`}
                    label={`$${t}`}
                    onRemove={() =>
                      setSelTickers((prev) => prev.filter((x) => x !== t))
                    }
                  />
                ))}
                {selTags.map((t) => (
                  <Chip
                    key={`tg-${t}`}
                    label={`#${t}`}
                    onRemove={() =>
                      setSelTags((prev) => prev.filter((x) => x !== t))
                    }
                  />
                ))}
              </div>
              <p className="mt-2.5 text-xs leading-relaxed text-muted-foreground">
                Pre-filled from this story — remove any you don&rsquo;t want.{" "}
                <Link
                  href="/briefings"
                  className="text-amber-500 underline-offset-2 hover:underline"
                >
                  Add more tickers &amp; tags
                </Link>{" "}
                or fine-tune your watchlist anytime — every email has an edit
                link, no account needed.
              </p>
            </div>
          ) : (
            <p className="mt-5 text-sm text-muted-foreground">
              Pick the tickers and tags you want on the{" "}
              <Link
                href="/briefings"
                className="text-amber-500 underline-offset-2 hover:underline"
              >
                briefings page
              </Link>
              .
            </p>
          )}

          {hasWatchlist && (
            <form
              onSubmit={submit}
              className="mt-5 flex flex-col gap-3 sm:flex-row sm:items-center"
            >
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
                aria-invalid={status === "error"}
                className="sm:max-w-xs"
              />
              <Button type="submit" disabled={isPending || !email}>
                {isPending ? "Setting up…" : "Send my first briefing →"}
              </Button>
            </form>
          )}

          {status === "error" && (
            <p role="alert" className="mt-2 text-sm text-destructive">
              {message}
            </p>
          )}

          <p className="mt-3 flex items-center gap-3 text-xs text-muted-foreground">
            <span>Free forever · one email a day, max · unsubscribe in one click.</span>
            <Link
              href="/briefings"
              className="inline-flex items-center gap-0.5 text-muted-foreground/80 hover:text-foreground"
            >
              How it works <ArrowUpRight size={11} />
            </Link>
          </p>
        </>
      )}
    </section>
  );
}

function Chip({ label, onRemove }: { label: string; onRemove: () => void }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-border/70 bg-background/60 py-1 pl-2.5 pr-1.5 text-sm font-medium">
      {label}
      <button
        type="button"
        onClick={onRemove}
        aria-label={`Remove ${label}`}
        className="rounded-full p-0.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </span>
  );
}
