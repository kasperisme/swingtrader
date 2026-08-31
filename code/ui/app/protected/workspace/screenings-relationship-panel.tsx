"use client";

import React, { useMemo } from "react";
import { RelationshipNetworkExplorer } from "@/components/relationship-network/relationship-network-explorer";
import type { NoteStatus } from "./screenings-types";

export function ScreeningsRelationshipNetworkPanel({
  symbols,
  selectedTicker,
  dismissed,
  onDismiss,
  onRestore,
  getStatus,
  onSetStatus,
  hasComment,
  onEditComment,
  getTickerMeta,
}: {
  symbols: string[];
  selectedTicker: string | null;
  onSelect: (ticker: string) => void;
  dismissed: Set<string>;
  onDismiss: (ticker: string) => void;
  onRestore: (ticker: string) => void;
  getStatus: (ticker: string) => NoteStatus;
  onSetStatus: (ticker: string, status: NoteStatus) => void;
  hasComment: (ticker: string) => boolean;
  onEditComment: (ticker: string) => void;
  getTickerMeta: (ticker: string) => {
    sector: string;
    industry: string;
    subSector: string;
  };
}) {
  const symbol = useMemo(() => {
    if (symbols.length === 0) return "";
    if (selectedTicker && symbols.includes(selectedTicker)) {
      return selectedTicker;
    }
    return symbols[0] ?? "";
  }, [symbols, selectedTicker]);

  if (symbols.length === 0) {
    return (
      <p className="text-sm text-muted-foreground py-8 text-center">
        No stocks to show.
      </p>
    );
  }
  const meta = getTickerMeta(symbol);
  const status = getStatus(symbol);
  const commentExists = hasComment(symbol);

  return (
    <div className="flex flex-col h-full min-h-0">
      <RelationshipNetworkExplorer
        key={symbol}
        vectors={[]}
        initialSeedTicker={symbol}
        hideSeedControls
        fillViewport
      />
    </div>
  );
}