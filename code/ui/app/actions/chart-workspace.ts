"use server";

import { createClient } from "@/lib/supabase/server";
import type { ChartAnnotation } from "@/components/ticker-charts/types";

export type PersonaScores = {
  confidence: number;
  short_term: number;
  long_term: number;
};

export type PersonaReport = {
  id: string;
  label: string;
  analysis: string;
  error?: string | null;
  scores?: PersonaScores;
};

export type ChartAiChatMessage = {
  role: "user" | "assistant";
  content: string;
  /** Annotations drawn in this assistant turn (for pills under that message). */
  chartAnnotations?: ChartAnnotation[];
  /** Individual persona reports from this assistant turn. */
  personaReports?: PersonaReport[];
};

type WorkspaceRow = {
  annotations: unknown;
  ai_chat_messages: unknown;
  note?: string | null;
};

/** PostgREST / Postgres when `note` column not migrated yet. */
function looksLikeMissingNoteColumn(message: string): boolean {
  const m = message.toLowerCase();
  if (!m.includes("note")) return false;
  return (
    m.includes("does not exist") ||
    m.includes("schema cache") ||
    m.includes("could not find")
  );
}

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
    if (Array.isArray(o.personaReports)) {
      msg.personaReports = o.personaReports as PersonaReport[];
    }
    out.push(msg);
  }
  return out;
}

export async function chartWorkspaceLoad(
  ticker: string,
): Promise<
  ActionSuccess<{ annotations: ChartAnnotation[]; aiChatMessages: ChartAiChatMessage[]; note: string }> | ActionError
> {
  const sym = normalizeTicker(ticker);
  if (!sym) return { ok: false, error: "Missing ticker" };

  const supabase = await createClient();
  const {
    data: { user },
    error: authError,
  } = await supabase.auth.getUser();
  if (authError || !user) return { ok: false, error: "Unauthorized" };

  let { data, error } = await supabase
    .schema("swingtrader")
    .from("user_ticker_chart_workspace")
    .select("annotations, ai_chat_messages, note")
    .eq("user_id", user.id)
    .eq("ticker", sym)
    .maybeSingle();

  if (error && looksLikeMissingNoteColumn(error.message)) {
    ({ data, error } = await supabase
      .schema("swingtrader")
      .from("user_ticker_chart_workspace")
      .select("annotations, ai_chat_messages")
      .eq("user_id", user.id)
      .eq("ticker", sym)
      .maybeSingle());
  }

  if (error) return { ok: false, error: error.message };

  const row = data as WorkspaceRow | null;
  if (!row) {
    return { ok: true, data: { annotations: [], aiChatMessages: [], note: "" } };
  }

  return {
    ok: true,
    data: {
      annotations: parseAnnotations(row.annotations),
      aiChatMessages: parseMessages(row.ai_chat_messages),
      note: row.note ?? "",
    },
  };
}

export async function chartWorkspaceSave(
  ticker: string,
  payload: { annotations: ChartAnnotation[]; aiChatMessages: ChartAiChatMessage[]; note?: string },
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
        ...(payload.note !== undefined ? { note: payload.note || null } : {}),
      },
      { onConflict: "user_id,ticker" },
    );

  if (error && looksLikeMissingNoteColumn(error.message)) {
    const { error: err2 } = await supabase
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
    if (err2) return { ok: false, error: err2.message };
    return { ok: true, data: { updated: true } };
  }

  if (error) return { ok: false, error: error.message };
  return { ok: true, data: { updated: true } };
}

export async function chartWorkspaceNoteSave(
  ticker: string,
  note: string,
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
        note: note || null,
      },
      { onConflict: "user_id,ticker" },
    );

  if (error) {
    if (looksLikeMissingNoteColumn(error.message)) {
      return {
        ok: false,
        error:
          "Ticker notes are unavailable until the database adds column user_ticker_chart_workspace.note. Apply migration 20260421120000_user_ticker_chart_workspace_note.sql in Supabase (SQL editor or supabase db push).",
      };
    }
    return { ok: false, error: error.message };
  }
  return { ok: true, data: { updated: true } };
}
