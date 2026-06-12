import { createClient } from "@/lib/supabase/server";
import { aiFeaturesAllowed } from "@/lib/subscription";
import { getAnthropicClient, DEFAULT_MODEL, splitSystemMessages, type ChatMessage } from "@/lib/anthropic";

export async function POST(req: Request) {
  const supabase = await createClient();
  const { data: claims } = await supabase.auth.getClaims();
  if (!claims?.claims?.sub) return new Response("Unauthorized", { status: 401 });

  // Raw model passthrough — gate to paid/trial so Observers can't call the model
  // directly (open beta bypasses).
  if (!(await aiFeaturesAllowed(supabase))) {
    return new Response("AI features require a paid plan", { status: 403 });
  }

  const rawText = await req.text();
  if (!rawText) return new Response("Empty request body", { status: 400 });

  let body: { model?: string; system?: string; messages: ChatMessage[] };
  try {
    body = JSON.parse(rawText);
  } catch {
    return new Response(`Invalid JSON (${rawText.length} chars): ${rawText.slice(0, 200)}`, { status: 400 });
  }

  const model = body.model ?? DEFAULT_MODEL;
  const { system: systemFromMessages, messages: turns } = splitSystemMessages(body.messages);
  const system = [body.system, systemFromMessages].filter(Boolean).join("\n\n") || undefined;

  const client = getAnthropicClient();

  const encoder = new TextEncoder();
  const stream = new ReadableStream({
    async start(controller) {
      try {
        const upstream = client.messages.stream({
          model,
          max_tokens: 16000,
          ...(system ? { system } : {}),
          messages: turns,
        });

        for await (const event of upstream) {
          if (event.type === "content_block_delta" && event.delta.type === "text_delta") {
            controller.enqueue(encoder.encode(event.delta.text));
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
