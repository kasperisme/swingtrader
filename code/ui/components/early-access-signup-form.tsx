"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

type EarlyAccessSignupFormProps = {
  align?: "center" | "start";
  idSuffix?: string;
  source?: string;
  ctaLabel?: string;
};

export function EarlyAccessSignupForm({
  align = "center",
  idSuffix = "default",
  source = "landing",
  ctaLabel = "Get Early Access",
}: EarlyAccessSignupFormProps = {}) {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<"idle" | "loading" | "success" | "error">("idle");
  const [message, setMessage] = useState<string | null>(null);
  const inputId = `early-access-email-${idSuffix}`;

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setStatus("loading");
    setMessage(null);
    try {
      const res = await fetch("/api/early-access", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: email.trim(), source }),
      });
      const data = (await res.json().catch(() => ({}))) as { error?: string };
      if (!res.ok) {
        setStatus("error");
        setMessage(data.error ?? "Something went wrong. Please try again.");
        return;
      }
      setStatus("success");
      setMessage("Your spot is secured. We'll be in touch when you're up.");
      setEmail("");
      router.refresh();
    } catch {
      setStatus("error");
      setMessage("Network error. Please try again.");
    }
  }

  const justify = align === "start" ? "sm:justify-start" : "sm:justify-center";

  return (
    <div className="mt-6">
      <form
        onSubmit={onSubmit}
        className={`flex flex-col gap-3 sm:flex-row ${justify}`}
      >
        <label htmlFor={inputId} className="sr-only">
          Email address
        </label>
        <input
          id={inputId}
          name="email"
          type="email"
          required
          autoComplete="email"
          disabled={status === "loading"}
          value={email}
          onChange={(e) => {
            setEmail(e.target.value);
            if (status === "success") {
              setStatus("idle");
              setMessage(null);
            }
          }}
          placeholder="Enter your email"
          className="h-12 w-full rounded-xl border border-border bg-card px-4 text-sm outline-none transition focus-visible:border-primary disabled:opacity-60 sm:max-w-xs"
        />
        <button
          type="submit"
          disabled={status === "loading"}
          className="inline-flex h-12 cursor-pointer items-center justify-center rounded-xl bg-violet-600 px-6 text-sm font-semibold text-white shadow-lg shadow-violet-500/20 transition-all hover:bg-violet-500 disabled:pointer-events-none disabled:opacity-60"
        >
          {status === "loading" ? "Joining..." : ctaLabel}
        </button>
      </form>
      {message && (
        <p
          className={`mt-3 text-sm ${align === "start" ? "text-left" : ""} ${
            status === "error" ? "text-destructive" : "text-muted-foreground"
          }`}
          role={status === "error" ? "alert" : "status"}
        >
          {message}
        </p>
      )}
    </div>
  );
}
