import { createClient } from "@/lib/supabase/server";
import { aiFeaturesAllowed } from "@/lib/subscription";
import type Anthropic from "@anthropic-ai/sdk";
import { getAnthropicClient, DEFAULT_MODEL } from "@/lib/anthropic";
import type { OhlcBar, ChartAnnotation } from "@/components/ticker-charts/types";
import {
  TRADE_REVIEW_PERSONA_PROMPTS,
  TRADE_REVIEW_PERSONA_LABELS,
  TRADE_REVIEW_ORCHESTRATOR_PROMPT,
  withTradingStrategy,
  type TradeReviewPersonaId,
  type TradeReviewContext,
} from "@/lib/chart-ai/personas";
import {
  SEARCH_NEWS_TOOL,
  formatLatestArticlesBlock,
  ohlcSummary,
  searchTickerNews,
} from "@/lib/chart-ai/tools";
import { callClaude } from "@/lib/chart-ai/claude";
import type {
  ChartAiChatMessage,
  PersonaScores,
  PersonaReport,
} from "@/app/actions/chart-workspace";
import {
  tradeReviewSave,
  type TradeReviewScores,
} from "@/app/actions/trade-reviews";
import { findClosedPosition, type TradeLedgerInput } from "@/lib/trades/closed-positions";

const ALL_REVIEW_PERSONAS: TradeReviewPersonaId[] = [
  "entry_quality",
  "exit_quality",
  "risk_management",
  "lesson",
];

type ReviewScoreShape = {
  execution?: unknown;
  timing?: unknown;
  risk_mgmt?: unknown;
  lesson?: unknown;
};

/**
 * Trade-review personas use a different SCORES shape than the chart route's
 * personas — parse the trailing `SCORES: {...}` JSON into our 4-axis schema.
 */
function parseReviewScores(raw: string): { analysis: string; scores: TradeReviewScores | undefined } {
  const match = raw.match(/\nSCORES:\s*(\{[^\n]+\})\s*$/);
  if (!match) return { analysis: raw.trim(), scores: undefined };
  try {
    const parsed = JSON.parse(match[1]) as ReviewScoreShape;
    const clamp = (v: unknown) => Math.min(100, Math.max(0, Math.round(Number(v))));
    if (
      typeof parsed.execution === "number" ||
      typeof parsed.timing === "number" ||
      typeof parsed.risk_mgmt === "number" ||
      typeof parsed.lesson === "number"
    ) {
      return {
        analysis: raw.slice(0, match.index).trim(),
        scores: {
          execution: clamp(parsed.execution ?? 50),
          timing: clamp(parsed.timing ?? 50),
          risk_mgmt: clamp(parsed.risk_mgmt ?? 50),
          lesson: clamp(parsed.lesson ?? 50),
        },
      };
    }
  } catch {
    /* fall through */
  }
  return { analysis: raw.trim(), scores: undefined };
}

async function callReviewPersona(
  personaId: TradeReviewPersonaId,
  ctx: TradeReviewContext,
  ohlcData: OhlcBar[],
  tradingStrategy: string,
): Promise<{ analysis: string; scores?: TradeReviewScores; error?: string }> {
  const systemPrompt = withTradingStrategy(TRADE_REVIEW_PERSONA_PROMPTS[personaId](ctx), tradingStrategy);
  const dataBlock = `OHLC data covering the position window (≈5 bars before entry through 5 bars after exit):\n\`\`\`\n${ohlcSummary(ohlcData, 200)}\n\`\`\``;

  try {
    const { text } = await callClaude(
      [{ role: "user", content: dataBlock }],
      { system: systemPrompt, maxTokens: 1024 },
    );
    const { analysis, scores } = parseReviewScores(text.trim());
    return { analysis, scores };
  } catch (err) {
    return {
      analysis: "",
      error: `${TRADE_REVIEW_PERSONA_LABELS[personaId]} reviewer error: ${err instanceof Error ? err.message : String(err)}`,
    };
  }
}

/**
 * Aggregate persona scores into the single 4-axis review score that gets
 * persisted on the review row. Currently averages execution/timing/risk
 * across the personas that produced numbers; the "lesson" axis uses the
 * lesson persona's own score.
 */
function aggregateScores(perPersona: { id: TradeReviewPersonaId; scores?: TradeReviewScores }[]): TradeReviewScores | null {
  const avg = (vals: number[]) => Math.round(vals.reduce((a, b) => a + b, 0) / vals.length);
  const execVals = perPersona.flatMap((p) => (p.scores ? [p.scores.execution] : []));
  const timingVals = perPersona.flatMap((p) => (p.scores ? [p.scores.timing] : []));
  const riskVals = perPersona.flatMap((p) => (p.scores ? [p.scores.risk_mgmt] : []));
  const lessonPersona = perPersona.find((p) => p.id === "lesson");
  if (!execVals.length) return null;
  return {
    execution: avg(execVals),
    timing: avg(timingVals.length ? timingVals : execVals),
    risk_mgmt: avg(riskVals.length ? riskVals : execVals),
    lesson: lessonPersona?.scores?.lesson ?? avg(execVals),
  };
}

export async function POST(req: Request) {
  const supabase = await createClient();
  const { data: claims } = await supabase.auth.getClaims();
  const userId = claims?.claims?.sub;
  if (!userId) return new Response("Unauthorized", { status: 401 });

  // AI trade review is a paid/trial feature — gate Observers (open beta bypasses).
  if (!(await aiFeaturesAllowed(supabase))) {
    return new Response("AI features require a paid plan", { status: 403 });
  }

  const rawText = await req.text();
  if (!rawText) return new Response("Empty body", { status: 400 });

  let body: {
    closingTradeId: number;
    ohlcData: OhlcBar[];
    messages: ChartAiChatMessage[];
    /** If provided, skip per-persona pass (e.g. follow-up turn). */
    skipPersonas?: boolean;
  };
  try {
    body = JSON.parse(rawText);
  } catch {
    return new Response("Invalid JSON", { status: 400 });
  }

  const { closingTradeId, ohlcData, messages: history, skipPersonas } = body;
  if (!Number.isFinite(closingTradeId)) {
    return new Response("Missing closingTradeId", { status: 400 });
  }

  // Re-derive the position server-side from the user's full ledger so we
  // never trust a client-supplied position summary.
  const { data: ledgerRows, error: ledgerErr } = await supabase
    .schema("swingtrader")
    .from("user_trades")
    .select("id, ticker, currency, quantity, price_per_unit, side, executed_at, is_paper")
    .order("executed_at", { ascending: true })
    .limit(2000);

  if (ledgerErr) {
    return new Response(`Ledger fetch failed: ${ledgerErr.message}`, { status: 500 });
  }

  const position = findClosedPosition((ledgerRows ?? []) as TradeLedgerInput[], closingTradeId);
  if (!position) {
    return new Response("No closed position for this trade.", { status: 404 });
  }

  // Notes from participating trade rows — feeds the risk-management persona.
  const participatingIds = [...position.openTradeIds, ...position.closeTradeIds];
  const { data: noteRows } = await supabase
    .schema("swingtrader")
    .from("user_trades")
    .select("notes")
    .in("id", participatingIds);
  const userNotes = (noteRows ?? [])
    .map((r) => (r.notes as string | null)?.trim())
    .filter((n): n is string => !!n);

  const reviewCtx: TradeReviewContext = {
    ticker: position.ticker,
    side: position.side,
    qty: position.qty,
    avgEntry: position.avgEntry,
    avgExit: position.avgExit,
    openedAt: position.openedAt,
    closedAt: position.closedAt,
    holdingDays: position.holdingDays,
    realizedPnl: position.realizedPnl,
    realizedPnlPct: position.realizedPnlPct,
    currency: position.currency,
    userNotes,
  };

  const { data: strategyRow } = await supabase
    .schema("swingtrader")
    .from("user_trading_strategy")
    .select("strategy")
    .eq("user_id", userId)
    .maybeSingle();
  const tradingStrategy = strategyRow?.strategy ?? "";

  // On the very first turn we run all 4 reviewers. On follow-ups we skip the
  // persona pass — the user is conversing with the orchestrator.
  const isFirstTurn = history.filter((m) => m.role === "assistant" && m.content).length === 0;
  const runPersonas = isFirstTurn && !skipPersonas;

  const encoder = new TextEncoder();
  const emit = (controller: ReadableStreamDefaultController, obj: unknown) =>
    controller.enqueue(encoder.encode(JSON.stringify(obj) + "\n"));

  const stream = new ReadableStream({
    async start(controller) {
      try {
        const personaReports: PersonaReport[] = [];
        const personaScoresList: { id: TradeReviewPersonaId; scores?: TradeReviewScores }[] = [];
        const specialistReports: string[] = [];

        if (runPersonas) {
          emit(controller, { type: "specialists_requested", personas: ALL_REVIEW_PERSONAS });
          await Promise.all(
            ALL_REVIEW_PERSONAS.map((id) =>
              callReviewPersona(id, reviewCtx, ohlcData, tradingStrategy).then((r) => {
                const label = TRADE_REVIEW_PERSONA_LABELS[id];
                // Map our 4-axis review scores onto the existing PersonaScores
                // shape (confidence/short_term/long_term) so the chat UI can
                // render the score chips without any changes.
                const uiScores: PersonaScores | undefined = r.scores
                  ? {
                      confidence: r.scores.execution,
                      short_term: r.scores.timing,
                      long_term: r.scores.risk_mgmt,
                    }
                  : undefined;
                emit(controller, {
                  type: "persona",
                  id,
                  label,
                  analysis: r.analysis,
                  scores: uiScores ?? null,
                  error: r.error ?? null,
                });
                personaReports.push({
                  id,
                  label,
                  analysis: r.analysis,
                  error: r.error ?? null,
                  scores: uiScores,
                });
                personaScoresList.push({ id, scores: r.scores });
                const text = r.error ? `[Error: ${r.error}]` : (r.analysis || "[No analysis]");
                specialistReports.push(`### ${label}\n${text}`);
              }),
            ),
          );
        }

        // Pre-fetch news covering the holding period for the orchestrator.
        const openedMs = new Date(position.openedAt).getTime();
        const closedMs = new Date(position.closedAt).getTime();
        const daysBack = Number.isFinite(openedMs) && Number.isFinite(closedMs)
          ? Math.min(180, Math.max(7, Math.ceil((Date.now() - openedMs) / 86_400_000) + 7))
          : 60;
        const latestArticlesResult = await searchTickerNews(supabase, position.ticker, {
          limit: 12,
          days_back: daysBack,
        }).catch(() => null);
        const articlesBlock = formatLatestArticlesBlock(
          position.ticker,
          latestArticlesResult?.articles ?? [],
          daysBack,
        );

        const positionBlock = [
          `## Position summary`,
          `Side: ${position.side.toUpperCase()}`,
          `Qty: ${position.qty}`,
          `Avg entry: ${position.avgEntry.toFixed(4)} ${position.currency} (${position.openedAt.slice(0, 10)})`,
          `Avg exit:  ${position.avgExit.toFixed(4)} ${position.currency} (${position.closedAt.slice(0, 10)})`,
          `Held: ${position.holdingDays.toFixed(1)} days`,
          `Realized P&L: ${position.realizedPnl.toFixed(2)} ${position.currency} (${(position.realizedPnlPct * 100).toFixed(2)}%)`,
          userNotes.length ? `User notes:\n${userNotes.map((n) => `- ${n}`).join("\n")}` : "",
        ].filter(Boolean).join("\n");

        const ohlcBlock = `## OHLC around the trade\n\`\`\`\n${ohlcSummary(ohlcData, 200)}\n\`\`\``;

        const orchestratorInput = [
          positionBlock,
          ohlcBlock,
          articlesBlock ? `\n${articlesBlock}` : "",
          specialistReports.length > 0
            ? `\n## Specialist Reviewer Reports\n\n${specialistReports.join("\n\n")}`
            : "",
        ].filter(Boolean).join("\n\n");

        const orchestratorMessages: Anthropic.MessageParam[] = [
          ...history.map((m) => ({
            role: (m.role === "assistant" ? "assistant" : "user") as "user" | "assistant",
            content: m.content,
          })),
          { role: "user", content: orchestratorInput },
        ];

        const orchestratorSystem = withTradingStrategy(
          TRADE_REVIEW_ORCHESTRATOR_PROMPT(reviewCtx),
          tradingStrategy,
        );

        const tools: Anthropic.Tool[] = [SEARCH_NEWS_TOOL];

        const client = getAnthropicClient();
        const conversation: Anthropic.MessageParam[] = [...orchestratorMessages];

        let analysisText = "";
        const MAX_TOOL_ROUNDS = 3;

        for (let round = 0; round < MAX_TOOL_ROUNDS; round++) {
          const response = await client.messages.create({
            model: DEFAULT_MODEL,
            max_tokens: 3072,
            system: orchestratorSystem,
            messages: conversation,
            tools,
            tool_choice: { type: "auto" },
          });

          let roundText = "";
          const toolUseBlocks: Anthropic.ToolUseBlock[] = [];
          for (const block of response.content) {
            if (block.type === "text") roundText += block.text;
            else if (block.type === "tool_use") toolUseBlocks.push(block);
          }

          const toolResults: Anthropic.ToolResultBlockParam[] = [];
          for (const tu of toolUseBlocks) {
            if (tu.name === "search_ticker_news") {
              emit(controller, { type: "tool_use", name: tu.name });
              const args = tu.input as Record<string, unknown>;
              const result = await searchTickerNews(supabase, position.ticker, args);
              toolResults.push({
                type: "tool_result",
                tool_use_id: tu.id,
                content: JSON.stringify(result),
              });
            }
          }

          if (toolResults.length > 0) {
            conversation.push({ role: "assistant", content: response.content });
            conversation.push({ role: "user", content: toolResults });
            continue;
          }

          analysisText = roundText;
          break;
        }

        const aggregated = aggregateScores(personaScoresList);

        // Persist the conversation + final summary/scores. We append a single
        // assistant message representing this orchestrator pass, plus any
        // collected persona reports as metadata on that message.
        const finalAssistantMessage: ChartAiChatMessage = {
          role: "assistant",
          content: analysisText,
          ...(personaReports.length ? { personaReports } : {}),
        };
        const messagesToPersist: ChartAiChatMessage[] = [...history, finalAssistantMessage];
        // The history we received already includes the trailing empty
        // assistant placeholder if any — strip it before persisting.
        const cleaned = messagesToPersist.filter((m, i) =>
          !(i === messagesToPersist.length - 2 && m.role === "assistant" && !m.content),
        );

        const saveRes = await tradeReviewSave(closingTradeId, {
          messages: cleaned,
          summary: isFirstTurn ? analysisText : undefined,
          scores: isFirstTurn ? aggregated : undefined,
        });
        if (!saveRes.ok) {
          // Non-fatal — the chat continues; the user will see the analysis but
          // a refresh won't restore it. Log for ops.
          console.warn("[trade-review] save failed:", saveRes.error);
        }

        emit(controller, { type: "annotations", data: [] as ChartAnnotation[] });
        emit(controller, { type: "analysis", content: analysisText });
      } catch (err) {
        emit(controller, { type: "error", message: String(err) });
      } finally {
        controller.close();
      }
    },
  });

  return new Response(stream, {
    headers: { "Content-Type": "application/x-ndjson; charset=utf-8" },
  });
}
