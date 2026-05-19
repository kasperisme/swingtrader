"use client";

import { RelationshipNetworkExplorer } from "@/components/relationship-network/relationship-network-explorer";
import { type TickerRow } from "../vectors/vectors-ui";

export function RelationshipsUI({
  vectors = [],
  initialTicker,
}: {
  vectors?: TickerRow[];
  initialTicker?: string;
}) {
  return (
    <RelationshipNetworkExplorer
      vectors={vectors}
      fillViewport
      initialSeedTicker={initialTicker}
    />
  );
}
