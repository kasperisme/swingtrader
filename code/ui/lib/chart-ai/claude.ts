import type Anthropic from "@anthropic-ai/sdk";
import { getAnthropicClient, DEFAULT_MODEL } from "@/lib/anthropic";
import type { PersonaScores } from "@/app/actions/chart-workspace";

export type ClaudeCallOptions = {
  model?: string;
  system: string;
  tools?: Anthropic.Tool[];
  toolChoice?: Anthropic.ToolChoice;
  maxTokens?: number;
};

export type ClaudeCallResult = {
  text: string;
  toolUses: { name: string; input: unknown }[];
};

export async function callClaude(
  messages: Anthropic.MessageParam[],
  opts: ClaudeCallOptions,
): Promise<ClaudeCallResult> {
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

/**
 * Parses an `SCORES: {...}` trailing line from a persona's reply and returns
 * the analysis prefix + structured scores. Tolerant of malformed JSON.
 */
export function parsePersonaScores(raw: string): {
  analysis: string;
  scores: PersonaScores | undefined;
} {
  const match = raw.match(/\nSCORES:\s*(\{[^\n]+\})\s*$/);
  if (!match) return { analysis: raw.trim(), scores: undefined };
  try {
    const parsed = JSON.parse(match[1]) as {
      confidence?: unknown;
      short_term?: unknown;
      long_term?: unknown;
    };
    const clamp = (v: unknown) => Math.min(100, Math.max(0, Math.round(Number(v))));
    if (
      typeof parsed.confidence === "number" ||
      typeof parsed.short_term === "number" ||
      typeof parsed.long_term === "number"
    ) {
      return {
        analysis: raw.slice(0, match.index).trim(),
        scores: {
          confidence: clamp(parsed.confidence ?? 50),
          short_term: clamp(parsed.short_term ?? 50),
          long_term: clamp(parsed.long_term ?? 50),
        },
      };
    }
  } catch {
    /* fall through */
  }
  return { analysis: raw.trim(), scores: undefined };
}
