import { Suspense } from "react";
import { createClient } from "@/lib/supabase/server";
import { redirect } from "next/navigation";
import { ApiKeysUI } from "./api-keys-ui";

export const metadata = { title: "API Keys" };

async function ApiKeysContent() {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) redirect("/auth/login");

  const { data: keys } = await supabase
    .schema("swingtrader")
    .from("user_api_keys")
    .select("id, name, key_prefix, scopes, created_at, last_used_at, expires_at, revoked_at")
    .eq("user_id", user.id)
    .order("created_at", { ascending: false });

  return (
    <div className="flex flex-col gap-6 w-full">
      <div>
        <p className="text-xs font-semibold uppercase tracking-widest text-amber-500">Developer</p>
        <h1 className="mt-1 text-2xl font-bold tracking-tight">API Keys</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Use API keys to query the public REST API from your own scripts or applications.
        </p>
      </div>

      {/* Quick-start */}
      <div className="rounded-2xl border border-border bg-card overflow-hidden">
        <div className="border-b border-border px-5 py-3">
          <p className="text-xs font-semibold uppercase tracking-widest text-amber-500">Quick start</p>
        </div>
        <div className="px-5 py-4 space-y-3 text-sm">
          <p className="text-muted-foreground">
            Pass your key as a Bearer token in the{" "}
            <code className="font-mono text-xs bg-muted rounded px-1.5 py-0.5">Authorization</code>{" "}
            header:
          </p>
          <pre className="text-xs bg-background rounded-xl border border-border p-4 overflow-x-auto text-muted-foreground">{`# News (scope: news:read)
curl https://<your-domain>/api/v1/news/impact-heads \\
  -H "Authorization: Bearer st_live_<your_key>" \\
  -G -d "limit=10" -d "min_confidence=0.8"

# Screenings — create run, then rows (scope: screenings:write)
curl https://<your-domain>/api/v1/screenings/runs \\
  -H "Authorization: Bearer st_live_<your_key>" \\
  -H "Content-Type: application/json" \\
  -d '{"scan_date":"2026-04-11","source":"my_screener","market_json":{}}'
curl https://<your-domain>/api/v1/screenings/runs/<run_id>/rows \\
  -H "Authorization: Bearer st_live_<your_key>" \\
  -H "Content-Type: application/json" \\
  -d '{"rows":[{"dataset":"passed_stocks","row_data":{"symbol":"AAPL","Passed":true}}]}'`}</pre>
          <p className="text-muted-foreground">
            Rate limit:{" "}
            <span className="font-semibold text-foreground">60 requests / minute</span> per key.
          </p>
        </div>
      </div>

      <ApiKeysUI initialKeys={keys ?? []} />
    </div>
  );
}

export default function ApiKeysPage() {
  return (
    <div className="flex-1 w-full max-w-2xl">
      <Suspense
        fallback={
          <div className="text-sm text-muted-foreground animate-pulse">Loading API keys…</div>
        }
      >
        <ApiKeysContent />
      </Suspense>
    </div>
  );
}
