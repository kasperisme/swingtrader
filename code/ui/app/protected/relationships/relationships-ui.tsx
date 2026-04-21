"use client";

import { RelationshipNetworkExplorer } from "@/components/relationship-network/relationship-network-explorer";
import { type TickerRow } from "../vectors/vectors-ui";

export function RelationshipsUI({ vectors = [] }: { vectors?: TickerRow[] }) {
  return <RelationshipNetworkExplorer vectors={vectors} fillViewport />;
}
