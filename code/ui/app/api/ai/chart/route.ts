import { createClient } from "@/lib/supabase/server";
import type { ChartAnnotation, AnnotationRole } from "@/components/ticker-charts/types";
import type { OhlcBar } from "@/components/ticker-charts/types";
import { OLLAMA_HOST, DEFAULT_MODEL } from "@/lib/ollama";
import { PERSONA_PROMPTS, ORCHESTRATOR_PROMPT, PERSONA_LABELS, type PersonaId } from "@/lib/chart-ai/personas";
import {
  fetchSentimentContext,
  fetchRiskContext,
  fetchFundamentalsContext,
  formatSentimentContext,
  formatRiskContext,
  formatFundamentalsContext,
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

async function callPersona(
  personaId: PersonaId,
  symbol: string,
  ohlcData: OhlcBar[],
  personaContext: string,
  existingAnnotations: ChartAnnotation[],
): Promise<{ analysis: string; error?: string; ms: number }> {
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
    return { analysis: result.message?.content?.trim() ?? "", ms: performance.now() - t0 };
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

  // Fetch persona-specific context in parallel
  const tData = performance.now();
  const [sentimentCtx, riskCtx, fundamentalsCtx] = await Promise.all([
    fetchSentimentContext(symbol).catch(() => null),
    fetchRiskContext(symbol).catch(() => null),
    fetchFundamentalsContext(symbol).catch(() => null),
  ]);
  console.log(`[chart-ai] data-fetch: ${Math.round(performance.now() - tData)}ms`);

  // Build persona context strings (graceful degradation if data is missing)
  const sentimentContextStr = sentimentCtx ? formatSentimentContext(sentimentCtx) : "No sentiment data available.";
  const riskContextStr = riskCtx ? formatRiskContext(riskCtx) : "No risk data available.";
  const fundamentalsContextStr = fundamentalsCtx ? formatFundamentalsContext(fundamentalsCtx) : "No fundamental data available.";

  // Run all 4 persona analyses in parallel
  const tPersonas = performance.now();
  const [techResult, sentimentResult, riskResult, fundamentalsResult] = await Promise.all([
    callPersona("technical", symbol, ohlcData, "Provide your technical analysis based on the price and volume data above.", existingAnnotations),
    callPersona("sentiment", symbol, ohlcData, sentimentContextStr, existingAnnotations),
    callPersona("risk", symbol, ohlcData, riskContextStr, existingAnnotations),
    callPersona("fundamentals", symbol, ohlcData, fundamentalsContextStr, existingAnnotations),
  ]);
  console.log(`[chart-ai] personas: ${Math.round(performance.now() - tPersonas)}ms (tech=${Math.round(techResult.ms)}ms sentiment=${Math.round(sentimentResult.ms)}ms risk=${Math.round(riskResult.ms)}ms fundamentals=${Math.round(fundamentalsResult.ms)}ms)`);

  // Assemble specialist reports for orchestrator
  const specialistReports: string[] = [];
  const personas: { id: PersonaId; label: string; analysis: string }[] = [];

  const allResults = [
    { id: "technical" as PersonaId, ...techResult },
    { id: "sentiment" as PersonaId, ...sentimentResult },
    { id: "risk" as PersonaId, ...riskResult },
    { id: "fundamentals" as PersonaId, ...fundamentalsResult },
  ];

  for (const r of allResults) {
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

  // Build orchestrator prompt
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
    ...history.map(m => ({ role: m.role as OllamaMessage["role"], content: m.content })),
    { role: "user", content: orchestratorInput },
  ];

  // Call orchestrator with draw_on_chart tool
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
    return new Response(`Ollama error ${upstream.status}: ${t}`, { status: 502 });
  }

  let result: { message?: { content?: string; tool_calls?: { function: { name: string; arguments: unknown } }[] } };
  try { result = await upstream.json() as typeof result; }
  catch { return new Response("Invalid response from model", { status: 502 }); }
  console.log(`[chart-ai] orchestrator: ${Math.round(performance.now() - tOrchestrator)}ms`);

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

  // Prepend persona labels to analysis for client-side rendering
  const personaLine = personas.map((p) => `${p.label}`).join("|");
  const enrichedAnalysis = `<!-- personas:${personaLine} -->\n${analysisText}`;

  const encoder = new TextEncoder();
  console.log(`[chart-ai] total: ${Math.round(performance.now() - tTotal)}ms (data | personas | orchestrator)`);
  const stream = new ReadableStream({
    start(controller) {
      controller.enqueue(encoder.encode(`A:${JSON.stringify(annotations)}\n`));
      controller.enqueue(encoder.encode(enrichedAnalysis));
      controller.close();
    },
  });

  return new Response(stream, { headers: { "Content-Type": "text/plain; charset=utf-8" } });
}