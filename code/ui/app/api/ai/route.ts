import { createClient } from "@/lib/supabase/server";

const OLLAMA_HOST = "https://ollama.com";
const DEFAULT_MODEL = process.env.OLLAMA_DEFAULT_MODEL ?? "gpt-oss:120b";

type OllamaMessage = { role: "system" | "user" | "assistant"; content: string };

export async function POST(req: Request) {
  const supabase = await createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) return new Response("Unauthorized", { status: 401 });

  const rawText = await req.text();
  if (!rawText) return new Response("Empty request body", { status: 400 });

  let body: { model?: string; system?: string; messages: OllamaMessage[] };
  try {
    body = JSON.parse(rawText);
  } catch {
    return new Response(`Invalid JSON (${rawText.length} chars): ${rawText.slice(0, 200)}`, { status: 400 });
  }

  const model: string = body.model ?? DEFAULT_MODEL;
  const system: string | undefined = body.system;
  const userMessages: OllamaMessage[] = body.messages;

  const messages: OllamaMessage[] = [
    ...(system ? [{ role: "system" as const, content: system }] : []),
    ...userMessages,
  ];

  const upstream = await fetch(`${OLLAMA_HOST}/api/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": `Bearer ${process.env.OLLAMA_API_KEY ?? ""}`,
    },
    body: JSON.stringify({ model, messages, stream: true }),
  });

  if (!upstream.ok) {
    const text = await upstream.text();
    return new Response(`Ollama error ${upstream.status}: ${text}`, { status: 502 });
  }

  // Pipe the upstream NDJSON stream, extracting message content from each line
  const encoder = new TextEncoder();
  const upstreamBody = upstream.body!;

  const stream = new ReadableStream({
    async start(controller) {
      const reader = upstreamBody.getReader();
      const decoder = new TextDecoder();
      let buf = "";

      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buf += decoder.decode(value, { stream: true });
          const lines = buf.split("\n");
          buf = lines.pop() ?? "";

          for (const line of lines) {
            if (!line.trim()) continue;
            try {
              const json = JSON.parse(line);
              const text: string | undefined = json?.message?.content;
              if (text) controller.enqueue(encoder.encode(text));
            } catch {
              // skip malformed line
            }
          }
        }
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        controller.enqueue(encoder.encode(`\n\n[Stream error: ${msg}]`));
      } finally {
        controller.close();
      }
    },
  });

  return new Response(stream, {
    headers: { "Content-Type": "text/plain; charset=utf-8" },
  });
}
