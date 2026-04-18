import { createClient } from "@/lib/supabase/server";
import type { ChartAnnotation, AnnotationRole } from "@/components/ticker-charts/types";
import type { OhlcBar } from "@/components/ticker-charts/types";

const OLLAMA_HOST = "https://ollama.com";
const DEFAULT_MODEL = process.env.OLLAMA_DEFAULT_MODEL ?? "gpt-oss:120b";

type OllamaMessage = {
  role: "system" | "user" | "assistant";
  content: string;
};

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

const SYSTEM_PROMPT = (symbol: string) =>
  `You are an expert swing trading chart analyst for ${symbol}. ` +
  `Always call the draw_on_chart tool to respond — include your annotations array and analysis text. ` +
  `Only use prices that appear in the OHLC data provided. ` +
  `Use dates from the OHLC data for trend lines.`;

export async function POST(req: Request) {
  const supabase = await createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) return new Response("Unauthorized", { status: 401 });

  const rawText = await req.text();
  if (!rawText) return new Response("Empty body", { status: 400 });

  let body: { symbol: string; ohlcData: OhlcBar[]; messages: { role: string; content: string }[] };
  try { body = JSON.parse(rawText); }
  catch { return new Response("Invalid JSON", { status: 400 }); }

  const { symbol, ohlcData, messages: history } = body;

  const dataContext = `OHLC data for ${symbol} (last 60 sessions):\n\`\`\`\n${ohlcSummary(ohlcData)}\n\`\`\``;

  const messages: OllamaMessage[] = [
    { role: "system", content: SYSTEM_PROMPT(symbol) },
    { role: "user", content: dataContext },
    ...history.map(m => ({ role: m.role as OllamaMessage["role"], content: m.content })),
  ];

  const upstream = await fetch(`${OLLAMA_HOST}/api/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${process.env.OLLAMA_API_KEY ?? ""}`,
    },
    body: JSON.stringify({ model: DEFAULT_MODEL, messages, tools: [DRAW_CHART_TOOL], stream: false }),
  });

  if (!upstream.ok) {
    const t = await upstream.text();
    return new Response(`Ollama error ${upstream.status}: ${t}`, { status: 502 });
  }

  let result: { message?: { content?: string; tool_calls?: { function: { name: string; arguments: unknown } }[] } };
  try { result = await upstream.json() as typeof result; }
  catch { return new Response("Invalid response from model", { status: 502 }); }

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

  const encoder = new TextEncoder();
  const stream = new ReadableStream({
    start(controller) {
      controller.enqueue(encoder.encode(`A:${JSON.stringify(annotations)}\n`));
      controller.enqueue(encoder.encode(analysisText));
      controller.close();
    },
  });

  return new Response(stream, { headers: { "Content-Type": "text/plain; charset=utf-8" } });
}
