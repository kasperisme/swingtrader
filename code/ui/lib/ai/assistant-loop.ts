/**
 * Shared multi-round tool-use loop for the AI assistants.
 *
 * Runs Anthropic with the shared SETUP_TOOLS (plus any caller-supplied extra
 * tools), executes tool calls, and streams NDJSON events to the client:
 *   { type: "text", content }        — cumulative assistant markdown
 *   { type: "status", label }        — inline confirmation chip (e.g. "Saved …")
 *   { type: "telegram_link", … }     — render the Telegram connect button
 *   { type: "navigate", url, reply } — drive a guided tour / route change
 *   { type: "done" } | { type: "error", message }
 */

import type Anthropic from "@anthropic-ai/sdk";
import { getAnthropicClient, DEFAULT_MODEL } from "@/lib/anthropic";
import {
  SETUP_TOOLS,
  executeSetupTool,
  type SetupToolContext,
} from "@/lib/ai/setup-tools";

export type Emit = (obj: unknown) => void;

/**
 * Handler for a non-setup tool (e.g. show_how_to). Return the tool_result
 * payload to feed back to the model, optional client events already emitted by
 * the caller, and whether the loop should stop after this round.
 */
export type ExtraToolHandler = (
  name: string,
  input: Record<string, unknown>,
  emit: Emit,
) => { result: unknown; terminal?: boolean } | null;

export type AssistantLoopOptions = {
  system: string;
  history: Anthropic.MessageParam[];
  ctx: SetupToolContext;
  emit: Emit;
  extraTools?: Anthropic.Tool[];
  handleExtraTool?: ExtraToolHandler;
  maxRounds?: number;
  fallbackText?: string;
  /**
   * Fixed text emitted as the assistant's opening before the model runs. The
   * model's first text is appended to it, so the turn reads as one message.
   * Use for a deterministic standard welcome on kickoff.
   */
  seedText?: string;
};

export async function runAssistantLoop(opts: AssistantLoopOptions): Promise<void> {
  const {
    system,
    history,
    ctx,
    emit,
    extraTools = [],
    handleExtraTool,
    maxRounds = 8,
    fallbackText = "I'm not sure how to help with that — could you rephrase?",
    seedText,
  } = opts;

  const client = getAnthropicClient();
  const tools = [...SETUP_TOOLS, ...extraTools];
  const messages: Anthropic.MessageParam[] = [...history];
  let fullText = "";

  // Deterministic opening shown instantly, before the model responds.
  if (seedText?.trim()) {
    fullText = seedText.trim();
    emit({ type: "text", content: fullText });
  }

  for (let round = 0; round < maxRounds; round++) {
    const response = await client.messages.create({
      model: DEFAULT_MODEL,
      max_tokens: 1500,
      system,
      messages,
      tools,
      tool_choice: { type: "auto" },
    });

    let roundText = "";
    const toolUses: Anthropic.ToolUseBlock[] = [];
    for (const block of response.content) {
      if (block.type === "text") roundText += block.text;
      else if (block.type === "tool_use") toolUses.push(block);
    }

    if (roundText.trim()) {
      fullText = fullText ? `${fullText}\n\n${roundText.trim()}` : roundText.trim();
      emit({ type: "text", content: fullText });
    }

    if (toolUses.length === 0) break;

    // Echo the assistant turn (text + tool_use) before the tool results.
    messages.push({ role: "assistant", content: response.content });

    const toolResults: Anthropic.ToolResultBlockParam[] = [];
    let terminate = false;

    for (const tu of toolUses) {
      const input = (tu.input ?? {}) as Record<string, unknown>;
      const extra = handleExtraTool?.(tu.name, input, emit) ?? null;
      if (extra) {
        toolResults.push({
          type: "tool_result",
          tool_use_id: tu.id,
          content: JSON.stringify(extra.result),
        });
        if (extra.terminal) terminate = true;
        continue;
      }

      const outcome = await executeSetupTool(tu.name, input, ctx);
      if (outcome.statusLabel) emit({ type: "status", label: outcome.statusLabel });
      if (outcome.clientEvent) emit(outcome.clientEvent);
      toolResults.push({
        type: "tool_result",
        tool_use_id: tu.id,
        content: JSON.stringify(outcome.result),
      });
    }

    messages.push({ role: "user", content: toolResults });
    if (terminate) break;
  }

  if (!fullText.trim()) emit({ type: "text", content: fallbackText });
  emit({ type: "done" });
}
