import Anthropic from "@anthropic-ai/sdk";

export const DEFAULT_MODEL = process.env.ANTHROPIC_DEFAULT_MODEL ?? "claude-sonnet-4-6";
export const ROUTER_MODEL = process.env.ANTHROPIC_ROUTER_MODEL ?? "claude-haiku-4-5";

let _client: Anthropic | null = null;

export function getAnthropicClient(): Anthropic {
  if (_client) return _client;
  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) throw new Error("ANTHROPIC_API_KEY is not set");
  _client = new Anthropic({ apiKey });
  return _client;
}

export type ChatMessage = { role: "system" | "user" | "assistant"; content: string };

/**
 * Splits a flat message list into a top-level system prompt + Anthropic message turns.
 * Concatenates multiple system messages with double newlines.
 */
export function splitSystemMessages(messages: ChatMessage[]): {
  system: string | undefined;
  messages: Anthropic.MessageParam[];
} {
  const systemParts: string[] = [];
  const turns: Anthropic.MessageParam[] = [];
  for (const m of messages) {
    if (m.role === "system") systemParts.push(m.content);
    else turns.push({ role: m.role, content: m.content });
  }
  return {
    system: systemParts.length > 0 ? systemParts.join("\n\n") : undefined,
    messages: turns,
  };
}
