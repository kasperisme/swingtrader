import { Suspense } from "react";
import { RelationshipsUI } from "./relationships-ui";

function RelationshipsData() {
  return <RelationshipsUI />;
}

export default function RelationshipsPage() {
  return (
    <div className="flex-1 w-full flex flex-col gap-6">
      <div>
        <p className="text-xs font-semibold uppercase tracking-widest text-amber-500">Network</p>
        <h1 className="mt-1 text-2xl font-bold tracking-tight">Ticker Relationships Explorer</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Traverse canonical ticker relationships and inspect source-article evidence behind each edge.
        </p>
      </div>

      <Suspense
        fallback={
          <div className="text-sm text-muted-foreground animate-pulse rounded-lg border border-border p-6">
            Loading relationship explorer…
          </div>
        }
      >
        <RelationshipsData />
      </Suspense>
    </div>
  );
}
