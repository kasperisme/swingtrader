"use client";

import { useMemo } from "react";

function maskQueryValue(value: string): string {
  if (value.length <= 10) return value;
  return `${value.slice(0, 5)}...${value.slice(-5)}`;
}

export default function XOauthScriptCallbackPage() {
  const fullUrl =
    typeof window !== "undefined" ? window.location.href : "Unavailable";

  const preview = useMemo(() => {
    if (typeof window === "undefined") return "Unavailable";
    const url = new URL(window.location.href);
    const safe = new URL(url.origin + url.pathname);
    for (const [key, value] of url.searchParams.entries()) {
      safe.searchParams.set(key, maskQueryValue(value));
    }
    return safe.toString();
  }, []);

  async function copyFullUrl(): Promise<void> {
    try {
      await navigator.clipboard.writeText(fullUrl);
      alert("Copied callback URL to clipboard.");
    } catch (error) {
      console.error("Failed to copy callback URL:", error);
      alert("Could not copy automatically. Please copy the URL from the address bar.");
    }
  }

  return (
    <main className="mx-auto flex min-h-svh max-w-2xl flex-col justify-center gap-4 p-6">
      <h1 className="text-2xl font-semibold">X OAuth Callback (Script)</h1>
      <p className="text-sm text-muted-foreground">
        This page is for analytics script PKCE flow. Copy the full callback URL and
        paste it into the script prompt for token exchange.
      </p>
      <p className="rounded border p-3 font-mono text-xs break-all">{preview}</p>
      <button
        type="button"
        onClick={copyFullUrl}
        className="w-fit rounded border px-4 py-2 text-sm hover:bg-muted"
      >
        Copy full callback URL
      </button>
    </main>
  );
}
