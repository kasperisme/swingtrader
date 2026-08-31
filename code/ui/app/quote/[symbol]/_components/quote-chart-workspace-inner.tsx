"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import {
  chartWorkspaceLoad,
  chartWorkspaceSave,
  type ChartAiChatMessage,
} from "@/app/actions/chart-workspace";
import { getChartWorkspaceAccess } from "@/app/actions/plan-gate";
import {
  TickerChartsPanel,
  type ChartAnnotation,
  type ChartPoint,
  type OhlcBar,
  type EntryMarker,
  type TickerChartNoteStatus,
} from "@/components/ticker-charts";
import { ChartAiChat } from "@/components/chart-ai-chat";
import { AiChatLocked } from "@/components/ai-chat-locked";
import { AddToScreening } from "@/components/add-to-screening";
import {
  ChartDateRangePicker,
  type ChartGranularity,
} from "@/components/chart-date-range-picker";
import { MobileAiChatSheet } from "@/components/mobile-ai-chat-sheet";
import { ChartWorkspaceSignedOut } from "./chart-workspace-signin";

/**
 * The chart workspace that used to live at /protected/charts, scoped to a
 * single ticker — the one whose quote page this is.
 *
 * What changed in the move, beyond losing the ticker search: that page opened
 * on SPY/QQQ/IWM and made you search your way to a company, and it resolved
 * auth and plan tier on the server. Here the company is the page, and the gate
 * is resolved after mount so /quote/[symbol] stays statically prerendered.
 * Everyone gets the chart; the account buys persistence and the AI panel.
 */
export function QuoteChartWorkspaceInner({ symbol }: { symbol: string }) {
  const [access, setAccess] = useState<{
    signedIn: boolean;
    aiEnabled: boolean;
  } | null>(null);
  const [pivot, setPivot] = useState<EntryMarker | null>(null);
  const [chartData, setChartData] = useState<OhlcBar[]>([]);
  const [annotations, setAnnotations] = useState<ChartAnnotation[]>([]);
  const [aiChatMessages, setAiChatMessages] = useState<ChartAiChatMessage[]>([]);
  const [workspaceReady, setWorkspaceReady] = useState(false);
  const [aiChatOpen, setAiChatOpen] = useState(true);
  const [mobileChatOpen, setMobileChatOpen] = useState(false);
  const saveSeq = useRef(0);

  const [dateRange, setDateRange] = useState<
    { from: string; to: string } | undefined
  >();
  const [granularity, setGranularity] = useState<ChartGranularity>("1day");

  useEffect(() => {
    let cancelled = false;
    void getChartWorkspaceAccess().then((res) => {
      if (!cancelled) setAccess(res);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  // Saved annotations and chat only exist for a signed-in user; for everyone
  // else the workspace is a scratch pad that starts empty and stays local.
  useEffect(() => {
    if (!access) return;
    if (!access.signedIn) {
      setWorkspaceReady(false);
      return;
    }
    let cancelled = false;
    void chartWorkspaceLoad(symbol).then((res) => {
      if (cancelled) return;
      if (res.ok) {
        setAnnotations(res.data.annotations);
        setAiChatMessages(res.data.aiChatMessages);
      } else {
        console.error("chartWorkspaceLoad:", res.error);
      }
      setWorkspaceReady(true);
    });
    return () => {
      cancelled = true;
    };
  }, [symbol, access]);

  useEffect(() => {
    if (!workspaceReady) return;
    const seq = ++saveSeq.current;
    const t = setTimeout(() => {
      if (seq !== saveSeq.current) return;
      void chartWorkspaceSave(symbol, { annotations, aiChatMessages });
    }, 750);
    return () => {
      clearTimeout(t);
    };
  }, [annotations, aiChatMessages, symbol, workspaceReady]);

  const symbols = useMemo(() => [symbol], [symbol]);
  const dismissed = useMemo(() => new Set<string>(), []);

  const getEntryMarker = useCallback(() => pivot, [pivot]);
  const onSetEntryMarker = useCallback((_ticker: string, point: ChartPoint) => {
    setPivot({ barIdx: point.barIdx, date: point.date, price: point.price });
  }, []);
  const onClearEntryMarker = useCallback(() => setPivot(null), []);

  const handleAiAnnotations = useCallback((aiAnnotations: ChartAnnotation[]) => {
    setAnnotations((prev) => [
      ...prev.filter((a) => a.origin === "user"),
      ...aiAnnotations.map((a) => ({ ...a, origin: "ai" as const })),
    ]);
  }, []);

  const handleAnnotationAdd = useCallback((ann: ChartAnnotation) => {
    setAnnotations((prev) => [...prev, ann]);
  }, []);

  const handleAnnotationDelete = useCallback((id: string) => {
    setAnnotations((prev) => prev.filter((a) => a.id !== id));
  }, []);

  // The panel is built for the screenings grid, where each row carries a
  // status, a comment and sector metadata. On a quote page there is one symbol
  // and none of that applies, so these stay inert.
  const noop = useCallback(() => {}, []);
  const getStatus = useCallback((): TickerChartNoteStatus => "active", []);
  const onSetStatus = useCallback(() => {}, []);
  const hasComment = useCallback(() => false, []);
  const getTickerMeta = useCallback(
    () => ({ sector: "", industry: "" }),
    [],
  );

  // Until the gate resolves, render nothing in the side panel rather than
  // flashing a sign-up prompt at a user who is already signed in.
  const sidePanel = !access ? null : !access.signedIn ? (
    <ChartWorkspaceSignedOut symbol={symbol} />
  ) : !access.aiEnabled ? (
    <AiChatLocked surface="quote_chart" />
  ) : (
    <ChartAiChat
      key={symbol}
      symbol={symbol}
      ohlcData={chartData}
      annotations={annotations}
      onAnnotations={handleAiAnnotations}
      messages={aiChatMessages}
      setMessages={setAiChatMessages}
      side
    />
  );

  return (
    <div className="flex w-full flex-col gap-4">
      <div data-tour="chart-indicators">
        <ChartDateRangePicker
          onChange={setDateRange}
          onGranularityChange={setGranularity}
        />
      </div>

      <div className="flex w-full items-stretch">
        <div data-tour="chart-canvas" className="min-w-0 flex-1">
          <TickerChartsPanel
            symbols={symbols}
            selectedTicker={symbol}
            onSelect={noop}
            dismissed={dismissed}
            onDismiss={noop}
            onRestore={noop}
            getStatus={getStatus}
            onSetStatus={onSetStatus}
            hasComment={hasComment}
            onEditComment={noop}
            getTickerMeta={getTickerMeta}
            getEntryMarker={getEntryMarker}
            onSetEntryMarker={onSetEntryMarker}
            onClearEntryMarker={onClearEntryMarker}
            screeningToolbar={false}
            showChevronSymbolNav={false}
            showSymbolHeadline={false}
            annotations={annotations}
            onChartData={setChartData}
            onAnnotationAdd={handleAnnotationAdd}
            onAnnotationDelete={handleAnnotationDelete}
            symbolPicker={
              access?.signedIn ? <AddToScreening ticker={symbol} /> : undefined
            }
            dateRange={dateRange}
            interval={granularity}
          />
        </div>

        {/* Collapse toggle strip */}
        <button
          type="button"
          onClick={() => setAiChatOpen((v) => !v)}
          className="hidden w-5 shrink-0 items-center justify-center border-l border-border bg-background transition-colors hover:bg-muted sm:flex"
          title={aiChatOpen ? "Collapse AI chat" : "Expand AI chat"}
        >
          {aiChatOpen ? (
            <ChevronRight className="h-3 w-3 text-muted-foreground" />
          ) : (
            <ChevronLeft className="h-3 w-3 text-muted-foreground" />
          )}
        </button>

        {aiChatOpen && sidePanel ? (
          <div
            data-tour="chart-ai-panel"
            className="relative hidden w-[340px] shrink-0 self-stretch border-l border-border sm:block"
          >
            <div className="absolute inset-0 flex min-h-0 flex-col">
              {sidePanel}
            </div>
          </div>
        ) : null}

        <MobileAiChatSheet
          open={mobileChatOpen}
          onOpen={() => setMobileChatOpen(true)}
          onClose={() => setMobileChatOpen(false)}
          title={symbol}
          hasIndicator={aiChatMessages.length > 0}
        >
          {!access ? null : !access.signedIn ? (
            <ChartWorkspaceSignedOut symbol={symbol} />
          ) : !access.aiEnabled ? (
            <AiChatLocked surface="quote_chart_mobile" />
          ) : (
            <ChartAiChat
              key={`mobile-${symbol}`}
              symbol={symbol}
              ohlcData={chartData}
              annotations={annotations}
              onAnnotations={handleAiAnnotations}
              messages={aiChatMessages}
              setMessages={setAiChatMessages}
            />
          )}
        </MobileAiChatSheet>
      </div>
    </div>
  );
}
