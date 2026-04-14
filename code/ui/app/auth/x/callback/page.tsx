export default async function XAuthCallbackPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const hasCode = typeof params.code === "string" && params.code.length > 0;
  const hasState = typeof params.state === "string" && params.state.length > 0;
  const hasError = typeof params.error === "string" && params.error.length > 0;

  return (
    <main className="mx-auto flex min-h-svh max-w-2xl flex-col justify-center gap-4 p-6">
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
        {typeof params.error === "string" ? (
          <p className="mt-2 text-destructive">Error: {params.error}</p>
        ) : null}
      </section>

      <section className="rounded border p-4 text-sm text-muted-foreground">
        Next implementation step: exchange code for tokens server-side, validate
        state/nonce, then create an authenticated app session.
      </section>
    </main>
  );
}
