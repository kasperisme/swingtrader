import { createClient } from "@/lib/supabase/server";
import { aiFeaturesAllowed } from "@/lib/subscription";
import type { ChartAnnotation } from "@/components/ticker-charts/types";
import type { OhlcBar } from "@/components/ticker-charts/types";
import type Anthropic from "@anthropic-ai/sdk";
import { getAnthropicClient, DEFAULT_MODEL, ROUTER_MODEL } from "@/lib/anthropic";
import { PERSONA_PROMPTS, ORCHESTRATOR_PROMPT, ROUTER_PROMPT, PERSONA_LABELS, withTradingStrategy, type PersonaId } from "@/lib/chart-ai/personas";
import type { PersonaScores } from "@/app/actions/chart-workspace";
import { screeningsUpsertDismissNote } from "@/app/actions/screenings";
import {
  TOURS,
  howToBriefMarkdown,
  howToUrl,
} from "@/app/protected/_components/tour-configs";
import type { TourKey } from "@/app/actions/onboarding";
import {
  DRAW_CHART_TOOL,
  SEARCH_NEWS_TOOL,
  formatAnnotationList,
  formatLatestArticlesBlock,
  ohlcSummary,
  parseAnnotations,
  searchTickerNews,
  type RawAnnotation,
} from "@/lib/chart-ai/tools";
import { callClaude, parsePersonaScores } from "@/lib/chart-ai/claude";

type TickerStatus = "active" | "dismissed" | "watchlist" | "pipeline";
const TICKER_STATUSES: readonly TickerStatus[] = ["active", "dismissed", "watchlist", "pipeline"];
import {
  fetchSentimentContext,
  fetchRiskContext,
  fetchFundamentalsContext,
  fetchNewsTrendContext,
  formatSentimentContext,
  formatRiskContext,
  formatFundamentalsContext,
  formatNewsTrendContext,
} from "@/lib/chart-ai/persona-context";

const UPDATE_STATUS_TOOL: Anthropic.Tool = {
  name: "update_ticker_status",
  description: "Change the workflow status for the current ticker in the user's screening. Use when the user asks to dismiss, watchlist, mark as active, or move to pipeline.",
  input_schema: {
    type: "object",
    required: ["status"],
    properties: {
      status: {
        type: "string",
        enum: ["active", "dismissed", "watchlist", "pipeline"],
        description: "active = default research target; dismissed = no longer interested; watchlist = monitoring; pipeline = active candidate to trade.",
      },
      comment: {
        type: "string",
        description: "Optional short note explaining the status change (e.g. \"setup invalidated\", \"earnings beat\"). Keep under 200 chars.",
      },
      highlighted: {
        type: "boolean",
        description: "Optional: pin/star this ticker so it stands out in the user's list.",
      },
    },
  },
};

const TOUR_KEYS = Object.keys(TOURS) as TourKey[];

const SHOW_HOW_TO_TOOL: Anthropic.Tool = {
  name: "show_how_to",
  description:
    "Drive a guided tour highlighting the exact UI elements that answer a 'how do I…' question. Use when the user asks how to do something the platform supports — creating a screening, adding a ticker, scheduling an agent, connecting Telegram, etc. Pick the tour_key whose route matches the feature; pass from_step / to_step (0-based, inclusive) when the question only needs a slice of the tour. The user is auto-navigated to the right page; the tour drives itself.",
  input_schema: {
    type: "object",
    required: ["tour_key"],
    properties: {
      tour_key: {
        type: "string",
        enum: TOUR_KEYS,
        description:
          "Which tour to drive. Each tour belongs to one route — see the how-to brief in the system prompt.",
      },
      from_step: {
        type: "integer",
        minimum: 0,
        description:
          "0-based first step to play. Defaults to 0 (start of tour). Use a higher index when the answer lives mid-tour.",
      },
      to_step: {
        type: "integer",
        minimum: 0,
        description:
          "0-based last step to play (inclusive). Defaults to the final step. Keep the range tight — usually 1–3 steps.",
      },
      reply: {
        type: "string",
        description:
          "Short markdown sentence shown alongside the navigation, e.g. 'Taking you to the screener — watch the highlighted steps.' Keep under 200 chars.",
      },
    },
  },
};

/**
 * A short "what time is it, and is the market open" block injected into every
 * LLM call. Without it the model only sees OHLC dates and has no idea what
 * "today", "recent", or "this week" mean, nor whether it's reasoning about a
 * live session or a stale weekend chart. Computed in US/Eastern (market time).
 */
function buildMarketTemporalContext(ohlcData: OhlcBar[]): string {
  const now = new Date();
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    weekday: "short",
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(now);
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "";
  const weekday = get("weekday");
  const hh = get("hour");
  const mm = get("minute");
  const dateStr = `${weekday} ${get("month")} ${get("day")}, ${get("year")}`;
  const minutesOfDay = Number(hh) * 60 + Number(mm);
  const isWeekend = weekday === "Sat" || weekday === "Sun";

  let session: string;
  if (isWeekend) session = "Market CLOSED (weekend)";
  else if (minutesOfDay < 4 * 60) session = "Market CLOSED (overnight)";
  else if (minutesOfDay < 9 * 60 + 30) session = "PRE-MARKET (opens 9:30 ET)";
  else if (minutesOfDay < 16 * 60) session = "Market OPEN — regular session";
  else if (minutesOfDay < 20 * 60) session = "AFTER-HOURS";
  else session = "Market CLOSED (overnight)";

  const lastBar = ohlcData[ohlcData.length - 1];
  const staleness = lastBar?.date
    ? ` The latest candle in the chart data is dated ${lastBar.date.slice(0, 10)} — treat it as the most recent confirmed close and never assume price data beyond it.`
    : "";

  return (
    `## Current time & market session\n` +
    `It is currently ${dateStr}, ${hh}:${mm} ET. ${session}.${staleness}\n` +
    `Anchor every time-relative judgement ("today", "recent", "this week", "the last few sessions", how soon earnings/catalysts are) to this current date — not to the end of the OHLC window, which may be older.\n\n`
  );
}

async function callPersona(
  personaId: PersonaId,
  symbol: string,
  ohlcData: OhlcBar[],
  personaContext: string,
  existingAnnotations: ChartAnnotation[],
  tradingStrategy?: string,
  temporalContext?: string,
): Promise<{ analysis: string; scores?: PersonaScores; error?: string; ms: number }> {
  const t0 = performance.now();
  const systemPrompt =
    (temporalContext ?? "") +
    withTradingStrategy(PERSONA_PROMPTS[personaId](symbol), tradingStrategy ?? "");
  const dataBlock = `OHLC data for ${symbol} (last 60 sessions):\n\`\`\`\n${ohlcSummary(ohlcData)}\n\`\`\``;

  const annotationContext = existingAnnotations.length > 0
    ? `\n\nExisting annotations on the chart (${existingAnnotations.length} total):\n` +
      existingAnnotations.map((a) => {
        if (a.type === "horizontal") return `- horizontal ${a.role} at $${a.price}${a.label ? ` "${a.label}"` : ""}`;
        if (a.type === "zone") return `- zone ${a.role} $${a.priceBottom}–$${a.priceTop}${a.label ? ` "${a.label}"` : ""}`;
        if (a.type === "trend_line") return `- trend_line ${a.role} from ${a.fromDate} $${a.fromPrice} to ${a.toDate} $${a.toPrice}${a.label ? ` "${a.label}"` : ""}`;
        return "";
      }).join("\n")
    : "";

  try {
    const { text } = await callClaude(
      [{ role: "user", content: `${dataBlock}${annotationContext}\n\n${personaContext}` }],
      { system: systemPrompt, maxTokens: 2048 },
    );
    const { analysis, scores } = parsePersonaScores(text.trim());
    return { analysis, scores, ms: performance.now() - t0 };
  } catch (err) {
    return { analysis: "", error: `${PERSONA_LABELS[personaId]} persona error: ${err instanceof Error ? err.message : String(err)}`, ms: performance.now() - t0 };
  }
}

export async function POST(req: Request) {
  const tTotal = performance.now();
  const supabase = await createClient();
  const { data: claims } = await supabase.auth.getClaims();
  const userId = claims?.claims?.sub;
  if (!userId) return new Response("Unauthorized", { status: 401 });

  // AI chat is a paid/trial feature — Observers are gated (the UI hides it; this
  // enforces it for direct calls). Bypassed during the open beta.
  if (!(await aiFeaturesAllowed(supabase))) {
    return new Response("AI features require a paid plan", { status: 403 });
  }

  const { data: strategyRow } = await supabase
    .schema("swingtrader")
    .from("user_trading_strategy")
    .select("strategy")
    .eq("user_id", userId)
    .maybeSingle();
  const tradingStrategy = strategyRow?.strategy ?? "";

  const rawText = await req.text();
  if (!rawText) return new Response("Empty body", { status: 400 });

  let body: { symbol: string; ohlcData: OhlcBar[]; annotations?: ChartAnnotation[]; messages: { role: string; content: string }[]; overridePersonas?: string[]; scanRowId?: number; runId?: number };
  try { body = JSON.parse(rawText); }
  catch { return new Response("Invalid JSON", { status: 400 }); }

  const { symbol, ohlcData, annotations: existingAnnotations = [], messages: history, overridePersonas, scanRowId, runId } = body;
  const canUpdateStatus = typeof scanRowId === "number" && typeof runId === "number";

  const tData = performance.now();
  const dataFetchPromise = Promise.all([
    fetchSentimentContext(symbol).catch(() => null),
    fetchRiskContext(symbol).catch(() => null),
    fetchFundamentalsContext(symbol).catch(() => null),
    fetchNewsTrendContext(symbol).catch(() => null),
    // Always pre-fetch the latest articles tagged with the current ticker so
    // every persona — and the orchestrator — can cite specific headlines
    // without first calling the search_ticker_news tool. The tool stays
    // available for follow-up drill-down queries.
    searchTickerNews(supabase, symbol, { limit: 10, days_back: 30 }).catch(
      () => null,
    ),
  ]);

  const ALL_PERSONA_IDS: PersonaId[] = ["technical", "sentiment", "risk", "fundamentals", "newsTrend"];

  let requestedPersonas: PersonaId[] = ALL_PERSONA_IDS;
  let needsPersonas: boolean | "confirm" = true;
  let confirmQuestion = "";

  if (overridePersonas !== undefined) {
    const valid = overridePersonas.filter((p): p is PersonaId => ALL_PERSONA_IDS.includes(p as PersonaId));
    needsPersonas = valid.length > 0;
    requestedPersonas = valid;
    console.log(`[chart-ai] override: personas=[${requestedPersonas.join(",")}]`);
  } else {
    const lastUserMessage = [...history].reverse().find((m) => m.role === "user")?.content ?? "";
    try {
      const { text } = await callClaude(
        [{ role: "user", content: lastUserMessage }],
        { system: ROUTER_PROMPT, model: ROUTER_MODEL, maxTokens: 512 },
      );
      const parsed = JSON.parse(text.trim() || "{}") as {
        needs_personas?: boolean | "confirm";
        personas?: string[];
        question?: string;
      };
      needsPersonas = parsed.needs_personas ?? true;
      if (Array.isArray(parsed.personas)) {
        requestedPersonas = parsed.personas.filter((p): p is PersonaId => ALL_PERSONA_IDS.includes(p as PersonaId));
        if (requestedPersonas.length === 0) requestedPersonas = ALL_PERSONA_IDS;
      }
      if (needsPersonas === "confirm") {
        confirmQuestion = parsed.question ?? "Would you like me to run a full specialist analysis on this?";
      }
    } catch (err) {
      console.warn("[chart-ai] router failed, falling back to all personas:", err);
    }
    console.log(`[chart-ai] router: needs_personas=${String(needsPersonas)} personas=[${requestedPersonas.join(",")}] t=${Math.round(performance.now() - tTotal)}ms`);
  }

  const temporalContext = buildMarketTemporalContext(ohlcData);
  const ohlcBlock = `OHLC data for ${symbol} (last 60 sessions):\n\`\`\`\n${ohlcSummary(ohlcData)}\n\`\`\``;
  const annotationBlock = existingAnnotations.length > 0
    ? `\nExisting chart annotations (${existingAnnotations.length}):\n${formatAnnotationList(existingAnnotations)}`
    : "";

  const encoder = new TextEncoder();
  const emit = (controller: ReadableStreamDefaultController, obj: unknown) =>
    controller.enqueue(encoder.encode(JSON.stringify(obj) + "\n"));

  const stream = new ReadableStream({
    async start(controller) {
      try {
        if (needsPersonas === "confirm") {
          emit(controller, { type: "confirm_specialists", personas: requestedPersonas, question: confirmQuestion });
          return;
        }
        const specialistReports: string[] = [];
        const engagedPersonas: { id: PersonaId; label: string }[] = [];

        if (needsPersonas && requestedPersonas.length > 0) {
          emit(controller, { type: "specialists_requested", personas: requestedPersonas });

          const [
            sentimentCtx,
            riskCtx,
            fundamentalsCtx,
            newsTrendCtx,
            latestArticlesResult,
          ] = await dataFetchPromise;
          console.log(`[chart-ai] data-fetch: ${Math.round(performance.now() - tData)}ms`);

          // Compact markdown summary of the latest ticker articles. Used as
          // an addendum on the newsTrend persona prompt + an extra block on
          // the orchestrator input so every persona can cite specifics.
          const latestArticlesBlock = formatLatestArticlesBlock(
            symbol,
            latestArticlesResult?.articles ?? [],
          );

          const personaContexts: Record<PersonaId, string> = {
            technical: "Provide your technical analysis based on the price and volume data above.",
            sentiment: sentimentCtx ? formatSentimentContext(sentimentCtx) : "No sentiment data available.",
            risk: riskCtx ? formatRiskContext(riskCtx) : "No risk data available.",
            fundamentals: fundamentalsCtx ? formatFundamentalsContext(fundamentalsCtx) : "No fundamental data available.",
            newsTrend:
              (newsTrendCtx
                ? formatNewsTrendContext(newsTrendCtx)
                : "No news trend data available.") +
              (latestArticlesBlock ? `\n\n${latestArticlesBlock}` : ""),
          };

          const tPersonas = performance.now();
          await Promise.all(requestedPersonas.map((personaId) =>
            callPersona(personaId, symbol, ohlcData, personaContexts[personaId], existingAnnotations, tradingStrategy, temporalContext)
              .then((r) => {
                emit(controller, { type: "persona", id: personaId, label: PERSONA_LABELS[personaId], analysis: r.analysis, scores: r.scores ?? null, error: r.error ?? null });
                const text = r.error ? `[Error: ${r.error}]` : (r.analysis || "[No data available]");
                specialistReports.push(`### ${PERSONA_LABELS[personaId]} Analysis\n${text}`);
                engagedPersonas.push({ id: personaId, label: PERSONA_LABELS[personaId] });
              })
          ));
          console.log(`[chart-ai] personas (${requestedPersonas.length}): ${Math.round(performance.now() - tPersonas)}ms`);
        }

        // Re-fetch outside the persona branch so the orchestrator still sees
        // the article list when no specialists ran (router skipped them, etc.).
        const [, , , , latestArticlesAtTop] = await dataFetchPromise;
        const orchestratorArticlesBlock = formatLatestArticlesBlock(
          symbol,
          latestArticlesAtTop?.articles ?? [],
        );

        const orchestratorInput = [
          ohlcBlock,
          annotationBlock,
          orchestratorArticlesBlock ? `\n${orchestratorArticlesBlock}` : "",
          specialistReports.length > 0 ? `\n## Specialist Reports\n\n${specialistReports.join("\n\n")}` : "",
        ].filter(Boolean).join("\n");

        const orchestratorMessages: Anthropic.MessageParam[] = [
          ...history.map((m) => ({ role: (m.role === "assistant" ? "assistant" : "user") as "user" | "assistant", content: m.content })),
          { role: "user", content: orchestratorInput },
        ];

        const tools: Anthropic.Tool[] = canUpdateStatus
          ? [DRAW_CHART_TOOL, UPDATE_STATUS_TOOL, SHOW_HOW_TO_TOOL, SEARCH_NEWS_TOOL]
          : [DRAW_CHART_TOOL, SHOW_HOW_TO_TOOL, SEARCH_NEWS_TOOL];

        const howToSystem =
          `\n\n## How-to / "show me" questions\n` +
          `If the user asks how to do something the platform supports (e.g. "how do I add this to a screening", "where do I schedule an agent", "how does Telegram work"), call the show_how_to tool with the matching tour_key + step range instead of writing prose. The user is auto-navigated and the tour drives itself.\n\n` +
          `Pick a tight step range (often 1–3 steps) — only span more steps when the question genuinely covers more.\n\n` +
          `Available tours and their steps (use these tour_key values verbatim):\n\n` +
          howToBriefMarkdown();

        const newsSystem =
          `\n\n## News questions\n` +
          `When the user asks about news, catalysts, recent headlines, or what's been moving the stock, call search_ticker_news first to fetch articles, then incorporate the findings into your analysis. The tool defaults to searching the current ticker — pass \`tags\` (e.g. ["earnings"], ["lawsuit"], ["AI"]) or a natural-language \`query\` to drill into a specific theme. Cite specific headlines and dates when relevant. You may call it multiple times with different filters.`;

        const orchestratorSystem =
          temporalContext +
          withTradingStrategy(ORCHESTRATOR_PROMPT(symbol), tradingStrategy ?? "") +
          howToSystem +
          newsSystem;

        const client = getAnthropicClient();
        const conversation: Anthropic.MessageParam[] = [...orchestratorMessages];

        let annotations: ChartAnnotation[] = [];
        let analysisText = "";
        let toolCallTotal = 0;
        const MAX_TOOL_ROUNDS = 4;

        const tOrchestrator = performance.now();
        try {
          for (let round = 0; round < MAX_TOOL_ROUNDS; round++) {
            const response = await client.messages.create({
              model: DEFAULT_MODEL,
              max_tokens: 4096,
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
            toolCallTotal += toolUseBlocks.length;

            const toolResults: Anthropic.ToolResultBlockParam[] = [];

            for (const tu of toolUseBlocks) {
              if (tu.name === "search_ticker_news") {
                emit(controller, { type: "tool_use", name: tu.name });
                const args = tu.input as {
                  query?: unknown;
                  tags?: unknown;
                  include_ticker?: unknown;
                  limit?: unknown;
                  days_back?: unknown;
                };
                const result = await searchTickerNews(supabase, symbol, args);
                toolResults.push({
                  type: "tool_result",
                  tool_use_id: tu.id,
                  content: JSON.stringify(result),
                });
              } else if (tu.name === "draw_on_chart") {
                const args = tu.input as { annotations?: RawAnnotation[]; analysis?: string };
                annotations = parseAnnotations(args.annotations ?? []);
                if (args.analysis) analysisText = args.analysis;
              } else if (tu.name === "show_how_to") {
                const args = tu.input as {
                  tour_key?: string;
                  from_step?: number;
                  to_step?: number;
                  reply?: string;
                };
                if (
                  typeof args.tour_key === "string" &&
                  (TOUR_KEYS as string[]).includes(args.tour_key)
                ) {
                  const url = howToUrl(
                    args.tour_key as TourKey,
                    args.from_step,
                    args.to_step,
                  );
                  emit(controller, { type: "navigate", url, reply: args.reply ?? null });
                  if (args.reply) analysisText = args.reply;
                }
              } else if (tu.name === "update_ticker_status" && canUpdateStatus) {
                const args = tu.input as { status?: string; comment?: string; highlighted?: boolean };
                const status = TICKER_STATUSES.includes(args.status as TickerStatus)
                  ? (args.status as TickerStatus)
                  : null;
                if (status) {
                  const res = await screeningsUpsertDismissNote({
                    scanRowId: scanRowId!,
                    runId: runId!,
                    ticker: symbol,
                    status,
                    ...(typeof args.highlighted === "boolean" ? { highlighted: args.highlighted } : {}),
                    ...(typeof args.comment === "string" ? { comment: args.comment } : {}),
                  });
                  emit(controller, {
                    type: "status_change",
                    status,
                    highlighted: args.highlighted ?? null,
                    comment: args.comment ?? null,
                    ok: res.ok,
                    error: res.ok ? null : res.error,
                  });
                }
              }
            }

            // If the model fetched data, return results and let it reason again.
            if (toolResults.length > 0) {
              conversation.push({ role: "assistant", content: response.content });
              conversation.push({ role: "user", content: toolResults });
              continue;
            }

            // No data-fetch tools used this round — finalize.
            if (!analysisText) analysisText = roundText;
            break;
          }
        } catch (err) { emit(controller, { type: "error", message: String(err) }); return; }
        console.log(`[chart-ai] orchestrator: ${Math.round(performance.now() - tOrchestrator)}ms  total: ${Math.round(performance.now() - tTotal)}ms`);

        console.log(`[chart-ai] tool_calls: ${toolCallTotal}, annotations: ${annotations.length}, has_text: ${!!analysisText}`);
        const personaLine = engagedPersonas.map((p) => p.label).join("|");
        emit(controller, { type: "annotations", data: annotations });
        emit(controller, { type: "analysis", content: personaLine ? `<!-- personas:${personaLine} -->\n${analysisText}` : analysisText });
      } catch (err) {
        emit(controller, { type: "error", message: String(err) });
      } finally {
        controller.close();
      }
    },
  });

  return new Response(stream, { headers: { "Content-Type": "application/x-ndjson; charset=utf-8" } });
}
