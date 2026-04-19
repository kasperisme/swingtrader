"use server";

import { createClient } from "@/lib/supabase/server";
import type { ChartAnnotation } from "@/components/ticker-charts/types";

export type ChartAiChatMessage = {
  role: "user" | "assistant";
  content: string;
  /** Annotations drawn in this assistant turn (for pills under that message). */
  chartAnnotations?: ChartAnnotation[];
};

type WorkspaceRow = {
  annotations: unknown;
  ai_chat_messages: unknown;
};

type ActionError = { ok: false; error: string };
type ActionSuccess<T> = { ok: true; data: T };

function normalizeTicker(raw: string): string {
  return raw.trim().toUpperCase().slice(0, 32);
}

function parseAnnotations(raw: unknown): ChartAnnotation[] {
  if (!Array.isArray(raw)) return [];
  return raw as ChartAnnotation[];
}

function parseMessages(raw: unknown): ChartAiChatMessage[] {
  if (!Array.isArray(raw)) return [];
  const out: ChartAiChatMessage[] = [];
  for (const item of raw) {
    if (!item || typeof item !== "object") continue;
    const o = item as Record<string, unknown>;
    const role = o.role === "user" || o.role === "assistant" ? o.role : null;
    const content = typeof o.content === "string" ? o.content : "";
    if (!role) continue;
    const msg: ChartAiChatMessage = { role, content };
    if (Array.isArray(o.chartAnnotations)) {
      msg.chartAnnotations = o.chartAnnotations as ChartAnnotation[];
    }
    out.push(msg);
  }
  return out;
}

export async function chartWorkspaceLoad(
  ticker: string,
): Promise<
  ActionSuccess<{ annotations: ChartAnnotation[]; aiChatMessages: ChartAiChatMessage[] }> | ActionError
> {
  const sym = normalizeTicker(ticker);
  if (!sym) return { ok: false, error: "Missing ticker" };

  const supabase = await createClient();
  const {
    data: { user },
    error: authError,
  } = await supabase.auth.getUser();
  if (authError || !user) return { ok: false, error: "Unauthorized" };

  const { data, error } = await supabase
    .schema("swingtrader")
    .from("user_ticker_chart_workspace")
    .select("annotations, ai_chat_messages")
    .eq("user_id", user.id)
    .eq("ticker", sym)
    .maybeSingle();

  if (error) return { ok: false, error: error.message };

  const row = data as WorkspaceRow | null;
  if (!row) {
    return { ok: true, data: { annotations: [], aiChatMessages: [] } };
  }

  return {
    ok: true,
    data: {
      annotations: parseAnnotations(row.annotations),
      aiChatMessages: parseMessages(row.ai_chat_messages),
    },
  };
}

export async function chartWorkspaceSave(
  ticker: string,
  payload: { annotations: ChartAnnotation[]; aiChatMessages: ChartAiChatMessage[] },
): Promise<ActionSuccess<{ updated: boolean }> | ActionError> {
  const sym = normalizeTicker(ticker);
  if (!sym) return { ok: false, error: "Missing ticker" };

  const supabase = await createClient();
  const {
    data: { user },
    error: authError,
  } = await supabase.auth.getUser();
  if (authError || !user) return { ok: false, error: "Unauthorized" };

  const { error } = await supabase
    .schema("swingtrader")
    .from("user_ticker_chart_workspace")
    .upsert(
      {
        user_id: user.id,
        ticker: sym,
        annotations: payload.annotations,
        ai_chat_messages: payload.aiChatMessages,
      },
      { onConflict: "user_id,ticker" },
    );

  if (error) return { ok: false, error: error.message };
  return { ok: true, data: { updated: true } };
}
