import { createClient } from "@/lib/supabase/server";
import type { SupabaseClient } from "@supabase/supabase-js";
import { normalizeSearchTag, tagsFromQuery } from "@/lib/news/search-tags";
import type { ChartAnnotation, AnnotationRole } from "@/components/ticker-charts/types";
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

type RawAnnotation = {
  type?: string;
  role?: string;
  label?: string;
  price?: number;
  price_top?: number;
  price_bottom?: number;
  from_date?: string;
  from_price?: number;
  to_date?: string;
  to_price?: number;
};

function parseAnnotations(raw: RawAnnotation[]): ChartAnnotation[] {
  const out: ChartAnnotation[] = [];
  for (const r of raw) {
    const role = (r.role ?? "info") as AnnotationRole;
    const id = crypto.randomUUID();
    if (r.type === "horizontal" && r.price != null) {
      out.push({ id, type: "horizontal", price: r.price, role, label: r.label });
    } else if (r.type === "zone" && r.price_top != null && r.price_bottom != null) {
      out.push({ id, type: "zone", priceTop: r.price_top, priceBottom: r.price_bottom, role, label: r.label });
    } else if (
      r.type === "trend_line" &&
      r.from_date && r.from_price != null &&
      r.to_date && r.to_price != null
    ) {
      out.push({
        id, type: "trend_line",
        fromDate: r.from_date, fromPrice: r.from_price,
        toDate: r.to_date, toPrice: r.to_price,
        role, label: r.label,
      });
    }
  }
  return out;
}

function ohlcSummary(bars: OhlcBar[]): string {
  const recent = bars.slice(-60);
  const lines = ["date,open,high,low,close,volume"];
  for (const b of recent) {
    lines.push(`${b.date.slice(0, 10)},${b.open},${b.high},${b.low},${b.close},${b.volume}`);
  }
  return lines.join("\n");
}

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

const DRAW_CHART_TOOL: Anthropic.Tool = {
  name: "draw_on_chart",
  description:
    "Draw technical analysis annotations on the price chart and provide your analysis. Call this for any analysis or drawing request. Skip it for pure how-to / 'where is X' questions — use show_how_to instead.",
  input_schema: {
    type: "object",
    required: ["annotations", "analysis"],
    properties: {
      annotations: {
        type: "array",
        description: "Annotations to draw on the chart. Must include every price level mentioned in the analysis (entries, stops, targets, support, resistance). Never empty.",
        items: {
          type: "object",
          required: ["type", "role"],
          properties: {
            type: {
              type: "string",
              enum: ["horizontal", "zone", "trend_line"],
              description: "horizontal = single price level; zone = price band; trend_line = line between two date/price points",
            },
            role: {
              type: "string",
              enum: ["support", "resistance", "entry", "stop", "target", "info"],
            },
            label: { type: "string", description: "Short label shown on chart" },
            price: { type: "number", description: "Required for type=horizontal" },
            price_top: { type: "number", description: "Required for type=zone" },
            price_bottom: { type: "number", description: "Required for type=zone" },
            from_date: { type: "string", description: "ISO date, required for type=trend_line" },
            from_price: { type: "number", description: "Required for type=trend_line" },
            to_date: { type: "string", description: "ISO date, required for type=trend_line" },
            to_price: { type: "number", description: "Required for type=trend_line" },
          },
        },
      },
      analysis: {
        type: "string",
        description: "Your technical analysis explanation in markdown (supports **bold**, bullet lists, etc.)",
      },
    },
  },
};

const SEARCH_NEWS_TOOL: Anthropic.Tool = {
  name: "search_ticker_news",
  description:
    "Search recent news articles for the current ticker. By default returns articles tagged with this ticker; pass `tags` or `query` to narrow to a theme/event (e.g. earnings, lawsuit, AI, guidance, FDA). Tickers should be uppercase symbols; themes are short words or phrases that get slugified. Returns title, source, date, URL, and snippet. Call once to scan recent news, or call multiple times with different filters to drill into specific catalysts.",
  input_schema: {
    type: "object",
    properties: {
      query: {
        type: "string",
        description:
          "Optional free-text query — tokens are auto-converted to tags (uppercase short tokens become ticker tags, longer words become theme slugs). Use this for natural-language follow-ups. Combined with the current ticker by default.",
      },
      tags: {
        type: "array",
        items: { type: "string" },
        description:
          "Optional explicit tag list to AND with the current ticker. Use uppercase symbols for tickers (AAPL) and lowercase words/phrases for themes (earnings, ai, lawsuit, guidance_cut). Leave empty to search just this ticker's news.",
      },
      include_ticker: {
        type: "boolean",
        description:
          "Whether to include the current ticker in the tag filter. Defaults to true. Set false only when explicitly searching cross-market themes.",
      },
      limit: {
        type: "integer",
        minimum: 1,
        maximum: 25,
        description: "Maximum number of articles to return. Default 10.",
      },
      days_back: {
        type: "integer",
        minimum: 1,
        maximum: 180,
        description: "Only return articles from the last N days. Default 30.",
      },
    },
  },
};

type NewsArticleResult = {
  title: string;
  source: string | null;
  published_at: string | null;
  url: string | null;
  snippet: string | null;
};

function formatLatestArticlesBlock(
  ticker: string,
  articles: NewsArticleResult[],
): string {
  if (!articles || articles.length === 0) return "";
  const lines = articles.slice(0, 10).map((a, i) => {
    const dateStr = a.published_at
      ? a.published_at.slice(0, 10)
      : "—";
    const source = a.source ?? "feed";
    const title = a.title || "(untitled)";
    const snippet = a.snippet ? ` — ${a.snippet}` : "";
    return `${i + 1}. [${dateStr} · ${source}] ${title}${snippet}`;
  });
  return [
    `## Latest news for ${ticker} (last 30 days)`,
    "",
    "Top headlines pre-loaded for context — cite by index when relevant. Call search_ticker_news for deeper drill-downs.",
    "",
    ...lines,
  ].join("\n");
}

async function searchTickerNews(
  supabase: SupabaseClient,
  ticker: string,
  args: {
    query?: unknown;
    tags?: unknown;
    include_ticker?: unknown;
    limit?: unknown;
    days_back?: unknown;
  },
): Promise<{
  ticker: string;
  tags: string[];
  count: number;
  articles: NewsArticleResult[];
  note?: string;
}> {
  const rawLimit = Number(args.limit);
  const limit = Number.isFinite(rawLimit) ? Math.min(Math.max(Math.round(rawLimit), 1), 25) : 10;
  const rawDays = Number(args.days_back);
  const daysBack = Number.isFinite(rawDays) ? Math.min(Math.max(Math.round(rawDays), 1), 180) : 30;
  const lookbackHours = daysBack * 24;
  const includeTicker = args.include_ticker === undefined ? true : Boolean(args.include_ticker);

  const explicit = Array.isArray(args.tags)
    ? (args.tags as unknown[]).map((t) => normalizeSearchTag(String(t))).filter(Boolean)
    : [];
  const fromQuery = typeof args.query === "string" ? tagsFromQuery(args.query) : [];

  const tagSet = new Set<string>();
  if (includeTicker) tagSet.add(normalizeSearchTag(ticker));
  for (const t of explicit) tagSet.add(t);
  for (const t of fromQuery) tagSet.add(t);
  const tagFilter = [...tagSet];

  if (tagFilter.length === 0) {
    return { ticker, tags: [], count: 0, articles: [], note: "No tags resolved from input." };
  }

  const { data, error } = await supabase.schema("swingtrader").rpc("search_news_by_tags", {
    tag_filter: tagFilter,
    match_count: limit,
    lookback_hours: lookbackHours,
    stream_filter: null,
  });

  if (error) {
    return { ticker, tags: tagFilter, count: 0, articles: [], note: `query failed: ${error.message}` };
  }

  const rows = (data ?? []) as {
    title: string | null;
    url: string | null;
    source: string | null;
    published_at: string | null;
    snippet: string | null;
  }[];

  const articles: NewsArticleResult[] = rows.map((r) => ({
    title: r.title ?? "",
    source: r.source,
    published_at: r.published_at,
    url: r.url,
    snippet: r.snippet,
  }));

  return { ticker, tags: tagFilter, count: articles.length, articles };
}

function parsePersonaScores(raw: string): { analysis: string; scores: PersonaScores | undefined } {
  const match = raw.match(/\nSCORES:\s*(\{[^\n]+\})\s*$/);
  if (!match) return { analysis: raw.trim(), scores: undefined };
  try {
    const parsed = JSON.parse(match[1]) as { confidence?: unknown; short_term?: unknown; long_term?: unknown };
    const clamp = (v: unknown) => Math.min(100, Math.max(0, Math.round(Number(v))));
    if (typeof parsed.confidence === "number" || typeof parsed.short_term === "number" || typeof parsed.long_term === "number") {
      return {
        analysis: raw.slice(0, match.index).trim(),
        scores: { confidence: clamp(parsed.confidence ?? 50), short_term: clamp(parsed.short_term ?? 50), long_term: clamp(parsed.long_term ?? 50) },
      };
    }
  } catch { /* fall through */ }
  return { analysis: raw.trim(), scores: undefined };
}

type ClaudeOptions = {
  model?: string;
  system: string;
  tools?: Anthropic.Tool[];
  toolChoice?: Anthropic.ToolChoice;
  maxTokens?: number;
};

type ClaudeResult = {
  text: string;
  toolUses: { name: string; input: unknown }[];
};

async function callClaude(
  messages: Anthropic.MessageParam[],
  opts: ClaudeOptions,
): Promise<ClaudeResult> {
  const client = getAnthropicClient();
  const response = await client.messages.create({
    model: opts.model ?? DEFAULT_MODEL,
    max_tokens: opts.maxTokens ?? 4096,
    system: opts.system,
    messages,
    ...(opts.tools ? { tools: opts.tools } : {}),
    ...(opts.toolChoice ? { tool_choice: opts.toolChoice } : {}),
  });

  let text = "";
  const toolUses: { name: string; input: unknown }[] = [];
  for (const block of response.content) {
    if (block.type === "text") text += block.text;
    else if (block.type === "tool_use") toolUses.push({ name: block.name, input: block.input });
  }
  return { text, toolUses };
}

function formatAnnotationList(annotations: ChartAnnotation[]): string {
  return annotations.map((a) => {
    if (a.type === "horizontal") return `- horizontal ${a.role} at $${a.price}${a.label ? ` "${a.label}"` : ""}`;
    if (a.type === "zone") return `- zone ${a.role} $${a.priceBottom}–$${a.priceTop}${a.label ? ` "${a.label}"` : ""}`;
    if (a.type === "trend_line") return `- trend_line ${a.role} from ${a.fromDate} $${a.fromPrice} to ${a.toDate} $${a.toPrice}${a.label ? ` "${a.label}"` : ""}`;
    return "";
  }).filter(Boolean).join("\n");
}

async function callPersona(
  personaId: PersonaId,
  symbol: string,
  ohlcData: OhlcBar[],
  personaContext: string,
  existingAnnotations: ChartAnnotation[],
  tradingStrategy?: string,
): Promise<{ analysis: string; scores?: PersonaScores; error?: string; ms: number }> {
  const t0 = performance.now();
  const systemPrompt = withTradingStrategy(PERSONA_PROMPTS[personaId](symbol), tradingStrategy ?? "");
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
            callPersona(personaId, symbol, ohlcData, personaContexts[personaId], existingAnnotations, tradingStrategy)
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
