import { createClient } from "@/lib/supabase/server";
import type { ChartAnnotation, AnnotationRole } from "@/components/ticker-charts/types";
import type { OhlcBar } from "@/components/ticker-charts/types";
import { OLLAMA_HOST, DEFAULT_MODEL, ROUTER_MODEL } from "@/lib/ollama";
import { PERSONA_PROMPTS, ORCHESTRATOR_PROMPT, ROUTER_PROMPT, PERSONA_LABELS, withTradingStrategy, type PersonaId } from "@/lib/chart-ai/personas";
import type { PersonaScores } from "@/app/actions/chart-workspace";
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

type OllamaMessage = { role: "system" | "user" | "assistant"; content: string };

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

const DRAW_CHART_TOOL = {
  type: "function",
  function: {
    name: "draw_on_chart",
    description: "Draw technical analysis annotations on the price chart and provide your analysis. You MUST call this tool for every response.",
    parameters: {
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
  },
};

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

  const messages: OllamaMessage[] = [
    { role: "system", content: systemPrompt },
    { role: "user", content: `${dataBlock}${annotationContext}\n\n${personaContext}` },
  ];

  try {
    const res = await fetch(`${OLLAMA_HOST}/api/chat`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${process.env.OLLAMA_API_KEY ?? ""}`,
      },
      body: JSON.stringify({ model: DEFAULT_MODEL, messages, stream: false }),
    });

    if (!res.ok) {
      const t = await res.text().catch(() => res.statusText);
      return { analysis: "", error: `${PERSONA_LABELS[personaId]} persona failed: ${res.status} ${t}`, ms: performance.now() - t0 };
    }

    const result = await res.json() as { message?: { content?: string } };
    const { analysis, scores } = parsePersonaScores(result.message?.content?.trim() ?? "");
    return { analysis, scores, ms: performance.now() - t0 };
  } catch (err) {
    return { analysis: "", error: `${PERSONA_LABELS[personaId]} persona error: ${err instanceof Error ? err.message : String(err)}`, ms: performance.now() - t0 };
  }
}

function formatAnnotationList(annotations: ChartAnnotation[]): string {
  return annotations.map((a) => {
    if (a.type === "horizontal") return `- horizontal ${a.role} at $${a.price}${a.label ? ` "${a.label}"` : ""}`;
    if (a.type === "zone") return `- zone ${a.role} $${a.priceBottom}–$${a.priceTop}${a.label ? ` "${a.label}"` : ""}`;
    if (a.type === "trend_line") return `- trend_line ${a.role} from ${a.fromDate} $${a.fromPrice} to ${a.toDate} $${a.toPrice}${a.label ? ` "${a.label}"` : ""}`;
    return "";
  }).filter(Boolean).join("\n");
}

async function callOllama(
  messages: OllamaMessage[],
  options: { model?: string; tools?: unknown[] } = {},
): Promise<{ message?: { content?: string; tool_calls?: { function: { name: string; arguments: unknown } }[] } }> {
  const res = await fetch(`${OLLAMA_HOST}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${process.env.OLLAMA_API_KEY ?? ""}` },
    body: JSON.stringify({ model: options.model ?? DEFAULT_MODEL, messages, tools: options.tools, stream: false }),
  });
  if (!res.ok) throw new Error(`Ollama ${res.status}: ${await res.text().catch(() => res.statusText)}`);
  return res.json() as Promise<{ message?: { content?: string; tool_calls?: { function: { name: string; arguments: unknown } }[] } }>;
}

export async function POST(req: Request) {
  const tTotal = performance.now();
  const supabase = await createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) return new Response("Unauthorized", { status: 401 });

  // Fetch user's trading strategy to inject into agent prompts
  const { data: strategyRow } = await supabase
    .schema("swingtrader")
    .from("user_trading_strategy")
    .select("strategy")
    .eq("user_id", user.id)
    .maybeSingle();
  const tradingStrategy = strategyRow?.strategy ?? "";

  const rawText = await req.text();
  if (!rawText) return new Response("Empty body", { status: 400 });

  let body: { symbol: string; ohlcData: OhlcBar[]; annotations?: ChartAnnotation[]; messages: { role: string; content: string }[]; overridePersonas?: string[] };
  try { body = JSON.parse(rawText); }
  catch { return new Response("Invalid JSON", { status: 400 }); }

  const { symbol, ohlcData, annotations: existingAnnotations = [], messages: history, overridePersonas } = body;

  // Start data fetches speculatively — they run in parallel with the router call
  // so they're often ready by the time personas are needed.
  const tData = performance.now();
  const dataFetchPromise = Promise.all([
    fetchSentimentContext(symbol).catch(() => null),
    fetchRiskContext(symbol).catch(() => null),
    fetchFundamentalsContext(symbol).catch(() => null),
    fetchNewsTrendContext(symbol).catch(() => null),
  ]);

  const ALL_PERSONA_IDS: PersonaId[] = ["technical", "sentiment", "risk", "fundamentals", "newsTrend"];

  // If the client explicitly overrides personas (after a confirmation dialog), skip the router.
  let requestedPersonas: PersonaId[] = ALL_PERSONA_IDS;
  let needsPersonas: boolean | "confirm" = true;
  let confirmQuestion = "";

  if (overridePersonas !== undefined) {
    const valid = overridePersonas.filter((p): p is PersonaId => ALL_PERSONA_IDS.includes(p as PersonaId));
    needsPersonas = valid.length > 0;
    requestedPersonas = valid;
    console.log(`[chart-ai] override: personas=[${requestedPersonas.join(",")}]`);
  } else {
    // Router call: fast JSON-only decision on which personas (if any) to engage
    const lastUserMessage = [...history].reverse().find((m) => m.role === "user")?.content ?? "";
    try {
      const routerResult = await callOllama(
        [{ role: "system", content: ROUTER_PROMPT }, { role: "user", content: lastUserMessage }],
        { model: ROUTER_MODEL },
      );
      const parsed = JSON.parse(routerResult.message?.content?.trim() ?? "{}") as {
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
        // Router asked user to confirm — emit the question and exit.
        // The client will show Yes/No buttons and re-send with overridePersonas.
        if (needsPersonas === "confirm") {
          emit(controller, { type: "confirm_specialists", personas: requestedPersonas, question: confirmQuestion });
          return;
        }
        const specialistReports: string[] = [];
        const engagedPersonas: { id: PersonaId; label: string }[] = [];

        if (needsPersonas && requestedPersonas.length > 0) {
          // Tell the client which personas are being engaged so it can show loading state
          emit(controller, { type: "specialists_requested", personas: requestedPersonas });

          const [sentimentCtx, riskCtx, fundamentalsCtx, newsTrendCtx] = await dataFetchPromise;
          console.log(`[chart-ai] data-fetch: ${Math.round(performance.now() - tData)}ms`);

          const personaContexts: Record<PersonaId, string> = {
            technical: "Provide your technical analysis based on the price and volume data above.",
            sentiment: sentimentCtx ? formatSentimentContext(sentimentCtx) : "No sentiment data available.",
            risk: riskCtx ? formatRiskContext(riskCtx) : "No risk data available.",
            fundamentals: fundamentalsCtx ? formatFundamentalsContext(fundamentalsCtx) : "No fundamental data available.",
            newsTrend: newsTrendCtx ? formatNewsTrendContext(newsTrendCtx) : "No news trend data available.",
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

        const orchestratorInput = [
          ohlcBlock,
          annotationBlock,
          specialistReports.length > 0 ? `\n## Specialist Reports\n\n${specialistReports.join("\n\n")}` : "",
        ].filter(Boolean).join("\n");

        const orchestratorMessages: OllamaMessage[] = [
          { role: "system", content: withTradingStrategy(ORCHESTRATOR_PROMPT(symbol), tradingStrategy ?? "") },
          ...history.map((m) => ({ role: m.role as OllamaMessage["role"], content: m.content })),
          { role: "user", content: orchestratorInput },
        ];

        const tOrchestrator = performance.now();
        let result: { message?: { content?: string; tool_calls?: { function: { name: string; arguments: unknown } }[] } };
        try { result = await callOllama(orchestratorMessages, { tools: [DRAW_CHART_TOOL] }); }
        catch (err) { emit(controller, { type: "error", message: String(err) }); return; }
        console.log(`[chart-ai] orchestrator: ${Math.round(performance.now() - tOrchestrator)}ms  total: ${Math.round(performance.now() - tTotal)}ms`);

        const message = result.message ?? {};
        const toolCalls = message.tool_calls ?? [];
        let annotations: ChartAnnotation[] = [];
        let analysisText = message.content ?? "";

        for (const tc of toolCalls) {
          if (tc.function.name === "draw_on_chart") {
            const args = (typeof tc.function.arguments === "string"
              ? JSON.parse(tc.function.arguments)
              : tc.function.arguments) as { annotations?: RawAnnotation[]; analysis?: string };
            annotations = parseAnnotations(args.annotations ?? []);
            if (args.analysis) analysisText = args.analysis;
          }
        }

        console.log(`[chart-ai] tool_calls: ${toolCalls.length}, annotations: ${annotations.length}, has_content: ${!!message.content}`);
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