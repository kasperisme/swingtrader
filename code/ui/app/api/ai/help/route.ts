import { createClient } from "@/lib/supabase/server";
import type Anthropic from "@anthropic-ai/sdk";
import { getAnthropicClient, DEFAULT_MODEL } from "@/lib/anthropic";
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
    "Drive a guided tour highlighting the exact UI elements that answer a 'how do I…' question. Use whenever the answer to the user's question is a UI walkthrough — creating a screening, adding a ticker, scheduling an agent, connecting Telegram, etc. Pick the tour_key whose route matches the feature; pass from_step / to_step (0-based, inclusive) when the question only needs a slice of the tour. The user is auto-navigated to the right page; the tour drives itself.",
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
        description:
          "0-based first step to play. Defaults to 0 (start of tour).",
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

const SYSTEM_PROMPT = `You are the in-app help assistant for newsimpactscreener — a swing-trading research platform that scores news for impact, lets users build screenings, and runs AI agents on a schedule.

Your job is to answer "how do I…" / "where is…" / "what does X do" questions about the platform, and to walk users to the right place.

# Two ways to answer

1. **Walk them through it (preferred).** If the answer is a UI workflow, call \`show_how_to\` with the tour_key + a tight step range. The user is auto-navigated and a guided tour highlights the exact controls. Use this for almost every actionable question.

2. **Reply in chat.** When the question is conceptual (what does the impact score mean? what's the difference between a screening and an agent?), answer briefly in markdown — 2–4 sentences — and offer a tour as a follow-up if it would help.

# Style

- Be terse. Bullet points and short sentences over paragraphs.
- Never invent a feature, page, or button that isn't documented below. If you don't know, say so and suggest the closest tour.
- When the user asks something off-topic (chart analysis, trade ideas, company fundamentals), redirect: that's what the chart AI on /protected/charts is for.

# Available tours and their steps

Use these tour_key values verbatim when calling show_how_to.

${howToBriefMarkdown()}`;

export async function POST(req: Request) {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return new Response("Unauthorized", { status: 401 });

  let body: {
    messages: { role: string; content: string }[];
    currentRoute?: string;
  };
  try {
    body = (await req.json()) as typeof body;
  } catch {
    return new Response("Invalid JSON", { status: 400 });
  }

  const history = (body.messages ?? []).map((m) => ({
    role: (m.role === "assistant" ? "assistant" : "user") as
      | "user"
      | "assistant",
    content: m.content,
  }));
  if (history.length === 0) {
    return new Response("Empty conversation", { status: 400 });
  }

  const routeContext = body.currentRoute
    ? `\n\n# Current page\nThe user is on: ${body.currentRoute}`
    : "";

  const encoder = new TextEncoder();
  const emit = (
    controller: ReadableStreamDefaultController,
    obj: unknown,
  ) => controller.enqueue(encoder.encode(JSON.stringify(obj) + "\n"));

  const stream = new ReadableStream({
    async start(controller) {
      try {
        const client = getAnthropicClient();
        const response = await client.messages.create({
          model: DEFAULT_MODEL,
          max_tokens: 1024,
          system: SYSTEM_PROMPT + routeContext,
          messages: history,
          tools: [SHOW_HOW_TO_TOOL],
          tool_choice: { type: "auto" },
        });

        let textOut = "";
        let navigated = false;

        for (const block of response.content) {
          if (block.type === "text") {
            textOut += block.text;
          } else if (block.type === "tool_use" && block.name === "show_how_to") {
            const args = block.input as {
              tour_key?: string;
              from_step?: number;
              to_step?: number;
              reply?: string;
            };
            if (
              typeof args.tour_key === "string" &&
              (TOUR_KEYS as string[]).includes(args.tour_key)
            ) {
              const url = howToUrl(
                args.tour_key as TourKey,
                args.from_step,
                args.to_step,
              );
              const reply = args.reply ?? "Walking you through it.";
              emit(controller, { type: "navigate", url, reply });
              navigated = true;
            }
          }
        }

        if (!navigated && textOut.trim()) {
          emit(controller, { type: "text", content: textOut });
        } else if (!navigated && !textOut.trim()) {
          emit(controller, {
            type: "text",
            content:
              "I'm not sure how to help with that yet — could you rephrase, or ask about a specific page (Charts, Screenings, Agents, Profile, Trades, Articles, News Trends, Relations)?",
          });
        }
        emit(controller, { type: "done" });
      } catch (err) {
        emit(controller, { type: "error", message: String(err) });
      } finally {
        controller.close();
      }
    },
  });

  return new Response(stream, {
    headers: { "Content-Type": "application/x-ndjson; charset=utf-8" },
  });
}
