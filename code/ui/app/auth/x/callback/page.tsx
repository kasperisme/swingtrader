"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";

function CallbackContent() {
  const params = useSearchParams();
  const code = params.get("code");
  const state = params.get("state");
  const error = params.get("error");
  const hasCode = Boolean(code);
  const hasState = Boolean(state);
  const hasError = Boolean(error);

  return (
    <>
      <h1 className="text-2xl font-semibold">X Sign-In Callback</h1>
      <p className="text-sm text-muted-foreground">
        Dedicated callback route for future user sign-in with X.
      </p>

      <section className="rounded border p-4 text-sm">
        <p>
          Callback status:{" "}
          {hasError
            ? "error received"
            : hasCode && hasState
              ? "authorization response received"
              : "missing expected OAuth params"}
        </p>
        {error ? (
          <p className="mt-2 text-destructive">Error: {error}</p>
        ) : null}
      </section>

      <section className="rounded border p-4 text-sm text-muted-foreground">
        Next implementation step: exchange code for tokens server-side, validate
        state/nonce, then create an authenticated app session.
      </section>
    </>
  );
}

export default function XAuthCallbackPage() {
  return (
    <main className="mx-auto flex min-h-svh max-w-2xl flex-col justify-center gap-4 p-6">
      <Suspense
        fallback={
          <p className="text-sm text-muted-foreground">
            Reading OAuth callback parameters...
          </p>
        }
      >
        <CallbackContent />
      </Suspense>
    </main>
  );
}
