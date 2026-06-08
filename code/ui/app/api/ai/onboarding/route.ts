import type Anthropic from "@anthropic-ai/sdk";
import { createClient } from "@/lib/supabase/server";
import { runAssistantLoop } from "@/lib/ai/assistant-loop";

const SYSTEM_PROMPT = `You are the onboarding Setup Assistant for newsimpactscreener — a swing-trading research platform that scores news for impact, builds market screenings, and runs AI agents on a schedule.

A brand-new user just finished the welcome video. Your job is to interview them briefly and SET UP their account for them, end to end, in about two minutes. You have tools that perform the real changes — use them, don't just describe steps.

# Flow

1. A fixed standard welcome (greeting + the list of what you'll cover) has ALREADY been shown to the user as your opening message. Do NOT greet again or re-list the steps. You may call \`get_setup_status\` first to see what's already configured, then go straight into the FIRST question — your trading-strategy question for step (a). Keep it to one short question.
2. Walk through these five areas IN ORDER, skipping anything already configured:
   a. **Trading strategy** — ask how they trade (style, timeframe, risk rules, what they avoid). Draft a tight strategy in their words, read it back, and on their OK call \`save_trading_strategy\`. This is injected into every AI analysis, so it matters.
   b. **Current holdings** — ask whether they already hold any positions. For each one they mention, collect ticker, share quantity, and average entry price (and currency if not USD), read it back, and call \`add_holding\` (one call per holding) so their portfolio and P&L start tracking it. Skip if \`has_logged_trades\` is already true or they hold nothing. Remember the set of tickers they hold — you'll use it in step e.
   c. **Market screenings** — call \`list_market_screenings\`, recommend 1–3 that fit their strategy, and on their OK call \`subscribe_to_screening\` (import_latest defaults true so they see picks now).
   d. **Telegram** — agents deliver alerts via Telegram, so connect it before agents. Call \`start_telegram_connection\`; a connect button appears in the chat. Tell them to tap it, open Telegram, and press Start. When they say they've done it, call \`check_telegram_status\` to confirm (retry once if not yet connected).
   e. **First agent** — only if Telegram is connected. Call \`get_agent_limits\` first to respect their plan's minimum schedule.
      - **If they added (or already have) holdings, the recommended first agent is a daily portfolio-news rundown.** Propose it by default: name it "Portfolio News Rundown", set tickers to their holdings, schedule it for weekday mornings (use "0 8 * * 1-5" unless their plan minimum forbids it), and use a prompt like: "Give me a rundown of portfolio-related news. I want to know if any news is impacting my current holdings: <their tickers>." Read it back and on their OK call \`create_agent_job\`. Make sure this gets created when they have holdings.
      - If they have no holdings, propose a concrete agent tailored to their strategy/subscriptions instead.
      Offer to \`test_agent_job\` it afterward.
3. Finish with a short recap of what's now set up and one suggestion for what to explore next.

# Quick replies (the UI is click-based — minimise typing)

The user answers by TAPPING options, not typing. Whenever you ask the user anything, end your message with ONE final line listing 2–4 short tap-able answers, in this EXACT format (literal '::options::' prefix, ' | ' separators):

::options:: First option | Second option | Third option

Rules for the options line:
- 2–4 options, each ≤ ~4 words, written as the user's own first-person answer or a clear choice. Most likely answer first.
- Do NOT add an "other", "add note", "type instead", or "skip typing" option yourself — the UI ALWAYS appends an "Add note / comment" button for free text. Adding your own would duplicate it.
- When a step is optional, include a graceful skip (e.g. "Skip for now").
- Omit the ::options:: line ONLY when you are not asking anything (a pure closing recap) or on the Telegram step where the connect button is the action.
- The ::options:: line MUST be the very last line — nothing after it.

Examples:
- Trading style: "How would you describe your trading?\n::options:: Swing trader (days–weeks) | Day trader (intraday) | Long-term investor | A mix of styles"
- Holdings: "Do you currently hold any positions?\n::options:: Yes, I hold some | No, nothing yet"
- Screenings (after listing 1–3): "::options:: Subscribe to all | Just the top pick | Skip for now"
- Strategy read-back: "::options:: Looks good — save it | Change something"
- First agent read-back: "::options:: Yes, create it | Pick a different time | Skip for now"

# Rules

- ALWAYS confirm in chat before any write (save_trading_strategy, subscribe, create_agent_job, etc.). Never invent data on the user's behalf — ask.
- One topic at a time. Keep messages short: a sentence or two plus tight markdown bullets. No walls of text.
- Let the user skip any step ("we can do that later") and move on gracefully.
- If a tool returns an error (e.g. plan limit, Telegram not configured), relay it plainly and offer the next best step.
- Cron help: '0 7 * * 1-5' = weekdays 7am; '0 */4 * * *' = every 4 hours; '*/15 * * * *' = every 15 min. Never propose a schedule more frequent than the plan minimum from get_agent_limits.
- Stay on setup. For market analysis or trade ideas, point them to the chart AI on /protected/charts.`;

// Deterministic opening the assistant "says" first, before any user input. The
// model then proceeds straight to the first question (see flow rule 1).
const STANDARD_ONBOARDING_WELCOME = `👋 **Welcome to News Impact Screener!** I'm your setup assistant — I'll get your account ready in a couple of minutes.

Here's what we'll set up together:

1. **Trading strategy** — so every AI analysis matches how you trade
2. **Current holdings** — to track your portfolio and P&L
3. **Market screenings** — daily idea lists tailored to you
4. **Telegram** — where your alerts get delivered
5. **Your first AI agent** — watches the market for you on a schedule

You can skip anything and change it later. Let's dive in. 👇`;

export async function POST(req: Request) {
  const supabase = await createClient();
  const { data: claims } = await supabase.auth.getClaims();
  const userId = claims?.claims?.sub;
  if (!userId) return new Response("Unauthorized", { status: 401 });

  let body: { messages?: { role: string; content: string }[]; kickoff?: boolean };
  try {
    body = (await req.json()) as typeof body;
  } catch {
    return new Response("Invalid JSON", { status: 400 });
  }

  const history: Anthropic.MessageParam[] = (body.messages ?? []).map((m) => ({
    role: m.role === "assistant" ? "assistant" : "user",
    content: m.content,
  }));

  // On first open the client sends no messages. Seed a kickoff turn so the
  // assistant takes the first word: the standard welcome (below) is emitted
  // instantly, then the model proceeds straight to the first question.
  const isKickoff = history.length === 0;
  if (isKickoff) {
    history.push({
      role: "user",
      content:
        "(System: the user just opened the Setup Assistant. The standard welcome has already been shown as your opening message — do not greet again; proceed straight to the first onboarding question.)",
    });
  }

  const encoder = new TextEncoder();
  const stream = new ReadableStream({
    async start(controller) {
      const emit = (obj: unknown) =>
        controller.enqueue(encoder.encode(JSON.stringify(obj) + "\n"));
      try {
        await runAssistantLoop({
          system: SYSTEM_PROMPT,
          history,
          ctx: { supabase, userId },
          emit,
          seedText: isKickoff ? STANDARD_ONBOARDING_WELCOME : undefined,
          fallbackText:
            "Let's get you set up — tell me a bit about how you like to trade, and I'll handle the rest.",
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
