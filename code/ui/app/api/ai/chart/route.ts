import { createClient } from "@/lib/supabase/server";
import type { ChartAnnotation, AnnotationRole } from "@/components/ticker-charts/types";
import type { OhlcBar } from "@/components/ticker-charts/types";
import { OLLAMA_HOST, DEFAULT_MODEL } from "@/lib/ollama";
import { PERSONA_PROMPTS, ORCHESTRATOR_PROMPT, PERSONA_LABELS, type PersonaId } from "@/lib/chart-ai/personas";
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
          description: "Annotations to draw. Use an empty array if nothing meaningful to draw.",
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
): Promise<{ analysis: string; scores?: PersonaScores; error?: string; ms: number }> {
  const t0 = performance.now();
  const systemPrompt = PERSONA_PROMPTS[personaId](symbol);
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

export async function POST(req: Request) {
  const tTotal = performance.now();
  const supabase = await createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) return new Response("Unauthorized", { status: 401 });

  const rawText = await req.text();
  if (!rawText) return new Response("Empty body", { status: 400 });

  let body: { symbol: string; ohlcData: OhlcBar[]; annotations?: ChartAnnotation[]; messages: { role: string; content: string }[] };
  try { body = JSON.parse(rawText); }
  catch { return new Response("Invalid JSON", { status: 400 }); }

  const { symbol, ohlcData, annotations: existingAnnotations = [], messages: history } = body;

  // Fetch persona-specific context before opening the stream
  const tData = performance.now();
  const [sentimentCtx, riskCtx, fundamentalsCtx, newsTrendCtx] = await Promise.all([
    fetchSentimentContext(symbol).catch(() => null),
    fetchRiskContext(symbol).catch(() => null),
    fetchFundamentalsContext(symbol).catch(() => null),
    fetchNewsTrendContext(symbol).catch(() => null),
  ]);
  console.log(`[chart-ai] data-fetch: ${Math.round(performance.now() - tData)}ms`);

  const sentimentContextStr = sentimentCtx ? formatSentimentContext(sentimentCtx) : "No sentiment data available.";
  const riskContextStr = riskCtx ? formatRiskContext(riskCtx) : "No risk data available.";
  const fundamentalsContextStr = fundamentalsCtx ? formatFundamentalsContext(fundamentalsCtx) : "No fundamental data available.";
  const newsTrendContextStr = newsTrendCtx ? formatNewsTrendContext(newsTrendCtx) : "No news trend data available.";

  const encoder = new TextEncoder();
  const emit = (controller: ReadableStreamDefaultController, obj: unknown) =>
    controller.enqueue(encoder.encode(JSON.stringify(obj) + "\n"));

  const stream = new ReadableStream({
    async start(controller) {
      try {
        const tPersonas = performance.now();

        // Run all 5 personas concurrently — each emits to the stream as soon as it resolves
        const [techResult, sentimentResult, riskResult, fundamentalsResult, newsTrendResult] = await Promise.all([
          callPersona("technical", symbol, ohlcData, "Provide your technical analysis based on the price and volume data above.", existingAnnotations)
            .then((r) => { emit(controller, { type: "persona", id: "technical", label: PERSONA_LABELS.technical, analysis: r.analysis, scores: r.scores ?? null, error: r.error ?? null }); return r; }),
          callPersona("sentiment", symbol, ohlcData, sentimentContextStr, existingAnnotations)
            .then((r) => { emit(controller, { type: "persona", id: "sentiment", label: PERSONA_LABELS.sentiment, analysis: r.analysis, scores: r.scores ?? null, error: r.error ?? null }); return r; }),
          callPersona("risk", symbol, ohlcData, riskContextStr, existingAnnotations)
            .then((r) => { emit(controller, { type: "persona", id: "risk", label: PERSONA_LABELS.risk, analysis: r.analysis, scores: r.scores ?? null, error: r.error ?? null }); return r; }),
          callPersona("fundamentals", symbol, ohlcData, fundamentalsContextStr, existingAnnotations)
            .then((r) => { emit(controller, { type: "persona", id: "fundamentals", label: PERSONA_LABELS.fundamentals, analysis: r.analysis, scores: r.scores ?? null, error: r.error ?? null }); return r; }),
          callPersona("newsTrend", symbol, ohlcData, newsTrendContextStr, existingAnnotations)
            .then((r) => { emit(controller, { type: "persona", id: "newsTrend", label: PERSONA_LABELS.newsTrend, analysis: r.analysis, scores: r.scores ?? null, error: r.error ?? null }); return r; }),
        ]);

        console.log(`[chart-ai] personas: ${Math.round(performance.now() - tPersonas)}ms (tech=${Math.round(techResult.ms)}ms sentiment=${Math.round(sentimentResult.ms)}ms risk=${Math.round(riskResult.ms)}ms fundamentals=${Math.round(fundamentalsResult.ms)}ms newsTrend=${Math.round(newsTrendResult.ms)}ms)`);

        // Assemble specialist reports for orchestrator
        const specialistReports: string[] = [];
        const personas: { id: PersonaId; label: string; analysis: string }[] = [];

        for (const r of [
          { id: "technical" as PersonaId, ...techResult },
          { id: "sentiment" as PersonaId, ...sentimentResult },
          { id: "risk" as PersonaId, ...riskResult },
          { id: "fundamentals" as PersonaId, ...fundamentalsResult },
          { id: "newsTrend" as PersonaId, ...newsTrendResult },
        ]) {
          const label = PERSONA_LABELS[r.id];
          if (r.error) {
            specialistReports.push(`### ${label} Analysis\n[Error: ${r.error}]`);
            personas.push({ id: r.id, label, analysis: `[Error: ${r.error}]` });
          } else if (r.analysis) {
            specialistReports.push(`### ${label} Analysis\n${r.analysis}`);
            personas.push({ id: r.id, label, analysis: r.analysis });
          } else {
            specialistReports.push(`### ${label} Analysis\n[No data available]`);
            personas.push({ id: r.id, label, analysis: "[No data available]" });
          }
        }

        const orchestratorInput = [
          `OHLC data for ${symbol} (last 60 sessions):\n\`\`\`\n${ohlcSummary(ohlcData)}\n\`\`\``,
          existingAnnotations.length > 0
            ? `\nExisting chart annotations (${existingAnnotations.length}):\n` +
              existingAnnotations.map((a) => {
                if (a.type === "horizontal") return `- horizontal ${a.role} at $${a.price}${a.label ? ` "${a.label}"` : ""}`;
                if (a.type === "zone") return `- zone ${a.role} $${a.priceBottom}–$${a.priceTop}${a.label ? ` "${a.label}"` : ""}`;
                if (a.type === "trend_line") return `- trend_line ${a.role} from ${a.fromDate} $${a.fromPrice} to ${a.toDate} $${a.toPrice}${a.label ? ` "${a.label}"` : ""}`;
                return "";
              }).join("\n")
            : "",
          `\n## Specialist Reports\n\n${specialistReports.join("\n\n")}`,
        ].join("\n");

        const orchestratorMessages: OllamaMessage[] = [
          { role: "system", content: ORCHESTRATOR_PROMPT(symbol) },
          ...history.map((m) => ({ role: m.role as OllamaMessage["role"], content: m.content })),
          { role: "user", content: orchestratorInput },
        ];

        const tOrchestrator = performance.now();
        const upstream = await fetch(`${OLLAMA_HOST}/api/chat`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${process.env.OLLAMA_API_KEY ?? ""}`,
          },
          body: JSON.stringify({ model: DEFAULT_MODEL, messages: orchestratorMessages, tools: [DRAW_CHART_TOOL], stream: false }),
        });

        if (!upstream.ok) {
          const t = await upstream.text();
          emit(controller, { type: "error", message: `Ollama error ${upstream.status}: ${t}` });
          return;
        }

        let result: { message?: { content?: string; tool_calls?: { function: { name: string; arguments: unknown } }[] } };
        try { result = await upstream.json() as typeof result; }
        catch { emit(controller, { type: "error", message: "Invalid response from model" }); return; }
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

        const personaLine = personas.map((p) => p.label).join("|");
        emit(controller, { type: "annotations", data: annotations });
        emit(controller, { type: "analysis", content: `<!-- personas:${personaLine} -->\n${analysisText}` });
      } catch (err) {
        emit(controller, { type: "error", message: String(err) });
      } finally {
        controller.close();
      }
    },
  });

  return new Response(stream, { headers: { "Content-Type": "application/x-ndjson; charset=utf-8" } });
}