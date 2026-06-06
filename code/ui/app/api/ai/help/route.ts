import type Anthropic from "@anthropic-ai/sdk";
import { createClient } from "@/lib/supabase/server";
import { runAssistantLoop, type ExtraToolHandler } from "@/lib/ai/assistant-loop";
import {
  TOURS,
  howToBriefMarkdown,
  howToUrl,
} from "@/app/protected/_components/tour-configs";
import type { TourKey } from "@/app/actions/onboarding";

const TOUR_KEYS = Object.keys(TOURS) as TourKey[];

const SHOW_HOW_TO_TOOL: Anthropic.Tool = {
  name: "show_how_to",
  description:
    "Drive a guided tour highlighting the exact UI elements that answer a 'how do I…' / 'where is…' question. Use when the user wants to LEARN where something is or do it themselves. (If they instead want you to just DO or CHANGE a setting — save their strategy, subscribe, connect Telegram, create/edit/pause an agent — use the setup tools to perform it directly rather than showing a tour.) Pick the tour_key whose route matches the feature; pass from_step / to_step (0-based, inclusive) for a slice. The user is auto-navigated and the tour drives itself.",
  input_schema: {
    type: "object",
    required: ["tour_key"],
    properties: {
      tour_key: {
        type: "string",
        enum: TOUR_KEYS,
        description:
          "Which tour to drive. Each tour belongs to one route — see the how-to brief in the system prompt.",
      },
      from_step: {
        type: "integer",
        minimum: 0,
        description: "0-based first step to play. Defaults to 0 (start of tour).",
      },
      to_step: {
        type: "integer",
        minimum: 0,
        description:
          "0-based last step to play (inclusive). Defaults to the final step. Keep the range tight — usually 1–3 steps.",
      },
      reply: {
        type: "string",
        description:
          "Short markdown sentence shown alongside the navigation, e.g. 'Taking you to the screener — watch the highlighted steps.' Keep under 200 chars.",
      },
    },
  },
};

const SYSTEM_PROMPT = `You are the in-app Ask AI assistant for newsimpactscreener — a swing-trading research platform that scores news for impact, lets users build screenings, and runs AI agents on a schedule.

You do two jobs:

1. **Answer & guide.** For "how do I…" / "where is…" / "what does X do" questions, either reply briefly in markdown (conceptual questions) or call \`show_how_to\` to walk the user through the UI (preferred for actionable how-tos).

2. **Do it for them.** When the user asks you to actually change their setup — "set my trading strategy to…", "subscribe me to…", "connect Telegram", "create an agent that…", "pause my X agent", "what's left to set up" — use the setup tools to perform it directly. Always confirm the specifics in chat before any write, and especially before creating an agent (echo the schedule, prompt, and tickers). After Telegram pairing, a connect button appears in chat — tell the user to tap it, then call check_telegram_status.

# Style

- Be terse. Bullet points and short sentences over paragraphs.
- Never invent a feature, page, or button that isn't documented below. If unsure, say so and suggest the closest tour.
- For market analysis or trade ideas, redirect to the chart AI on /protected/charts.
- Respect plan limits and the minimum agent schedule from get_agent_limits; relay any tool errors plainly.

# Available tours and their steps

Use these tour_key values verbatim when calling show_how_to.

${howToBriefMarkdown()}`;

const handleShowHowTo: ExtraToolHandler = (name, input, emit) => {
  if (name !== "show_how_to") return null;
  const args = input as {
    tour_key?: string;
    from_step?: number;
    to_step?: number;
    reply?: string;
  };
  if (
    typeof args.tour_key === "string" &&
    (TOUR_KEYS as string[]).includes(args.tour_key)
  ) {
    const url = howToUrl(args.tour_key as TourKey, args.from_step, args.to_step);
    const reply = args.reply ?? "Walking you through it.";
    emit({ type: "navigate", url, reply });
    return { result: { navigated: true, url }, terminal: true };
  }
  return { result: { ok: false, error: "Unknown tour_key" } };
};

export async function POST(req: Request) {
  const supabase = await createClient();
  const { data: claims } = await supabase.auth.getClaims();
  const userId = claims?.claims?.sub;
  if (!userId) return new Response("Unauthorized", { status: 401 });

  let body: { messages: { role: string; content: string }[]; currentRoute?: string };
  try {
    body = (await req.json()) as typeof body;
  } catch {
    return new Response("Invalid JSON", { status: 400 });
  }

  const history: Anthropic.MessageParam[] = (body.messages ?? []).map((m) => ({
    role: m.role === "assistant" ? "assistant" : "user",
    content: m.content,
  }));
  if (history.length === 0) {
    return new Response("Empty conversation", { status: 400 });
  }

  const routeContext = body.currentRoute
    ? `\n\n# Current page\nThe user is on: ${body.currentRoute}`
    : "";

  const encoder = new TextEncoder();
  const stream = new ReadableStream({
    async start(controller) {
      const emit = (obj: unknown) =>
        controller.enqueue(encoder.encode(JSON.stringify(obj) + "\n"));
      try {
        await runAssistantLoop({
          system: SYSTEM_PROMPT + routeContext,
          history,
          ctx: { supabase, userId },
          emit,
          extraTools: [SHOW_HOW_TO_TOOL],
          handleExtraTool: handleShowHowTo,
          fallbackText:
            "I'm not sure how to help with that yet — could you rephrase, or ask about a specific page (Charts, Screenings, Agents, Profile, Trades, Articles, News Trends, Relations)?",
        });
      } catch (err) {
        emit({ type: "error", message: String(err) });
      } finally {
        controller.close();
      }
    },
  });

  return new Response(stream, {
    headers: { "Content-Type": "application/x-ndjson; charset=utf-8" },
  });
}
