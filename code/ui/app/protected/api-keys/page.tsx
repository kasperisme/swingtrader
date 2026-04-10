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
        <h1 className="text-2xl font-bold">API Keys</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Use API keys to query the public REST API from your own scripts or applications.
        </p>
      </div>

      {/* Quick-start */}
      <div className="rounded-lg border bg-muted/40 p-4 text-sm space-y-2">
        <p className="font-medium">Quick start</p>
        <p className="text-muted-foreground">
          Pass your key as a Bearer token in the{" "}
          <code className="font-mono text-xs bg-muted rounded px-1">Authorization</code> header:
        </p>
        <pre className="text-xs bg-muted rounded p-3 overflow-x-auto">{`curl https://<your-domain>/api/v1/news/impact-heads \\
  -H "Authorization: Bearer st_live_<your_key>" \\
  -G -d "limit=10" -d "min_confidence=0.8"`}</pre>
        <p className="text-muted-foreground">
          Rate limit: <strong>60 requests / minute</strong> per key.
        </p>
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
