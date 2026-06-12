/**
 * Shared "setup" tool layer for the AI assistants.
 *
 * Both the onboarding Setup Assistant (/api/ai/onboarding) and the always-on
 * Ask AI help chat (/api/ai/help) use these tools to read and change the user's
 * setup conversationally: trading strategy, market-screening subscriptions,
 * Telegram pairing, and scheduled agent jobs.
 *
 * Every tool wraps an existing server action / lib helper — no new business
 * logic — and runs with the authed Supabase client, so RLS confines all writes
 * to the current user.
 */

import type Anthropic from "@anthropic-ai/sdk";
import type { createClient } from "@/lib/supabase/server";

import { getTradingStrategy, saveTradingStrategy } from "@/app/actions/trading-strategy";
import {
  listMarketScreenings,
  getMySubscriptionIds,
  subscribeToMarketScreening,
  unsubscribeFromMarketScreening,
  importLatestMarketScreeningResultForMe,
} from "@/app/actions/market-screenings";
import {
  listScheduledScreenings,
  createScheduledScreening,
  updateScheduledScreening,
  toggleScreening,
  testRunScreening,
  getScreeningLimits,
  type TradingSession,
} from "@/app/actions/screenings-agent";
import { generateTelegramLink, getTelegramStatus } from "@/lib/telegram/link";

type ServerClient = Awaited<ReturnType<typeof createClient>>;

export type SetupToolContext = {
  supabase: ServerClient;
  userId: string;
};

/** A special client-side UI event a tool can request (beyond plain text). */
export type SetupClientEvent = {
  type: "telegram_link";
  deep_link: string;
  expires_at: string;
};

export type SetupToolOutcome = {
  /** JSON payload fed back to the model as the tool_result content. */
  result: unknown;
  /** Short human label for an inline confirmation chip in the chat UI. */
  statusLabel?: string;
  /** Optional richer UI event (e.g. render the Telegram connect button). */
  clientEvent?: SetupClientEvent;
};

// ── Tool definitions ─────────────────────────────────────────────────────────

export const SETUP_TOOLS: Anthropic.Tool[] = [
  {
    name: "get_setup_status",
    description:
      "Read the user's current setup across all four areas at once: trading strategy, Telegram connection, market-screening subscriptions, and scheduled agents (plus plan limits). Call this first when onboarding or when the user asks 'what's left to set up'.",
    input_schema: { type: "object", properties: {} },
  },
  {
    name: "save_trading_strategy",
    description:
      "Save (overwrite) the user's trading strategy. This free-text description is injected into every AI analysis so recommendations align to their approach. Confirm the wording with the user before saving. Keep it under 2000 characters.",
    input_schema: {
      type: "object",
      required: ["strategy"],
      properties: {
        strategy: {
          type: "string",
          description:
            "The user's trading strategy in their own words — style (momentum, swing, CAN SLIM…), risk/reward rules, holding period, position sizing, what they avoid.",
        },
      },
    },
  },
  {
    name: "list_market_screenings",
    description:
      "List the published market screenings the user can subscribe to, each flagged with whether they're already subscribed. Use before subscribing so you can recommend relevant ones by slug.",
    input_schema: { type: "object", properties: {} },
  },
  {
    name: "subscribe_to_screening",
    description:
      "Subscribe the user to a market screening by slug. Optionally import the latest results immediately so they see current picks without waiting for the next scheduled run. Confirm with the user first.",
    input_schema: {
      type: "object",
      required: ["slug"],
      properties: {
        slug: {
          type: "string",
          description: "The screening slug (from list_market_screenings).",
        },
        import_latest: {
          type: "boolean",
          description:
            "If true, also import the most recent results into the user's workspace now. Defaults to true.",
        },
      },
    },
  },
  {
    name: "unsubscribe_from_screening",
    description:
      "Remove the user's subscription to a market screening by slug. Confirm with the user first.",
    input_schema: {
      type: "object",
      required: ["slug"],
      properties: {
        slug: { type: "string", description: "The screening slug to unsubscribe from." },
      },
    },
  },
  {
    name: "add_holding",
    description:
      "Record one of the user's current holdings as an open position in their trade book, so the portfolio table and P&L start tracking it. Use after asking whether they already hold anything. Confirm ticker, share quantity, and average entry price first. Call once per holding.",
    input_schema: {
      type: "object",
      required: ["ticker", "quantity", "avg_price"],
      properties: {
        ticker: { type: "string", description: "Ticker symbol, e.g. AAPL." },
        quantity: {
          type: "number",
          description: "Number of shares/units held (positive).",
        },
        avg_price: {
          type: "number",
          description: "Average entry price per share, in the position's currency.",
        },
        currency: {
          type: "string",
          description: "ISO currency code. Defaults to USD.",
        },
        acquired_at: {
          type: "string",
          description:
            "Optional ISO date the position was opened (e.g. 2025-01-15). Defaults to today if unknown.",
        },
        short: {
          type: "boolean",
          description: "Set true only if this is a short position. Defaults to false (long).",
        },
      },
    },
  },
  {
    name: "start_telegram_connection",
    description:
      "Begin Telegram pairing: mint a one-time deep link the user taps to connect their account. Alerts from scheduled agents are delivered via Telegram, so this is required before creating agents. After calling this, tell the user to tap the button that appears, then call check_telegram_status to confirm.",
    input_schema: { type: "object", properties: {} },
  },
  {
    name: "check_telegram_status",
    description:
      "Check whether the user's Telegram account is connected yet. Call after start_telegram_connection once the user says they've tapped the link.",
    input_schema: { type: "object", properties: {} },
  },
  {
    name: "get_agent_limits",
    description:
      "Get the user's scheduled-agent plan limits: how many agents they can run, how many are used, their plan tier, and the minimum allowed schedule (cron) for their plan. Check before creating an agent.",
    input_schema: { type: "object", properties: {} },
  },
  {
    name: "list_agent_jobs",
    description: "List the user's existing scheduled agents (id, name, prompt, schedule, active state).",
    input_schema: { type: "object", properties: {} },
  },
  {
    name: "create_agent_job",
    description:
      "Create a scheduled AI agent that runs a prompt on a cron schedule and alerts the user via Telegram when conditions are met. Requires Telegram connected. ALWAYS confirm the prompt, schedule, and tickers with the user before calling. Respect the minimum schedule from get_agent_limits.",
    input_schema: {
      type: "object",
      required: ["name", "prompt", "schedule"],
      properties: {
        name: { type: "string", description: "Short name, e.g. 'Airline Macro Watch'." },
        prompt: {
          type: "string",
          description:
            "What the agent should watch for and when to alert, in plain English. Be specific about tickers/clusters and thresholds.",
        },
        schedule: {
          type: "string",
          description:
            "Cron expression, e.g. '0 7 * * 1-5' (weekdays 7am). Must be no more frequent than the plan minimum.",
        },
        timezone: {
          type: "string",
          description: "IANA timezone, e.g. 'America/New_York'. Defaults to America/New_York.",
        },
        tickers: {
          type: "array",
          items: { type: "string" },
          description: "Optional focus symbols, e.g. ['AAL','DAL','UAL'].",
        },
        trading_session: {
          type: "string",
          enum: ["none", "nyse"],
          description:
            "Gate runs to NYSE session (9:30–16:00 ET) with 'nyse', or run any time with 'none' (default).",
        },
        condition_enabled: {
          type: "boolean",
          description:
            "If true, only deliver when trigger_condition is met (otherwise it always sends a summary).",
        },
        trigger_condition: {
          type: "string",
          description: "Required when condition_enabled is true: the condition that must hold to alert.",
        },
      },
    },
  },
  {
    name: "update_agent_job",
    description:
      "Update an existing scheduled agent by id. Only pass the fields to change. Use to rename, re-schedule, change the prompt/tickers, or edit the trigger condition. Confirm changes with the user first.",
    input_schema: {
      type: "object",
      required: ["id"],
      properties: {
        id: { type: "string", description: "The agent id (from list_agent_jobs)." },
        name: { type: "string" },
        prompt: { type: "string" },
        schedule: { type: "string", description: "Cron expression." },
        timezone: { type: "string" },
        tickers: { type: "array", items: { type: "string" } },
        trading_session: { type: "string", enum: ["none", "nyse"] },
        condition_enabled: { type: "boolean" },
        trigger_condition: { type: "string" },
      },
    },
  },
  {
    name: "toggle_agent_job",
    description: "Pause or resume a scheduled agent by id.",
    input_schema: {
      type: "object",
      required: ["id", "active"],
      properties: {
        id: { type: "string", description: "The agent id." },
        active: { type: "boolean", description: "true = resume, false = pause." },
      },
    },
  },
  {
    name: "test_agent_job",
    description:
      "Request an immediate one-off test run of a scheduled agent so the user can preview its output. Returns once the run is requested; the result is delivered asynchronously.",
    input_schema: {
      type: "object",
      required: ["id"],
      properties: { id: { type: "string", description: "The agent id." } },
    },
  },
];

export const SETUP_TOOL_NAMES: ReadonlySet<string> = new Set(
  SETUP_TOOLS.map((t) => t.name),
);

// ── Execution ────────────────────────────────────────────────────────────────

type Input = Record<string, unknown>;

/**
 * Race a promise against a timeout. On timeout the fallback value is returned
 * and the underlying promise is left to settle in the background. Used to keep a
 * slow screening import from blocking the whole onboarding turn (and the
 * Telegram step that follows it) — the subscription is already committed by then.
 */
async function withTimeout<T>(
  promise: Promise<T>,
  ms: number,
  onTimeout: () => T,
): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<T>((resolve) => {
    timer = setTimeout(() => resolve(onTimeout()), ms);
  });
  try {
    return await Promise.race([promise, timeout]);
  } finally {
    if (timer) clearTimeout(timer);
  }
}

const str = (v: unknown): string => (typeof v === "string" ? v : "");
const strArr = (v: unknown): string[] =>
  Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];

/**
 * Execute one setup tool. Returns the JSON result to feed back to the model,
 * plus optional UI hints (status chip + special client event). Never throws —
 * errors are returned in the result so the model can relay them to the user.
 */
export async function executeSetupTool(
  name: string,
  input: Input,
  ctx: SetupToolContext,
): Promise<SetupToolOutcome> {
  try {
    switch (name) {
      case "get_setup_status": {
        const [strategy, telegram, subIds, screenings, agentsRes, limitsRes, tradesCount] =
          await Promise.all([
            getTradingStrategy(),
            getTelegramStatus(ctx.supabase, ctx.userId),
            getMySubscriptionIds(),
            listMarketScreenings(),
            listScheduledScreenings(),
            getScreeningLimits(),
            ctx.supabase
              .schema("swingtrader")
              .from("user_trades")
              .select("id", { count: "exact", head: true })
              .eq("user_id", ctx.userId),
          ]);
        const subSlugs = screenings
          .filter((s) => subIds.includes(s.id))
          .map((s) => s.slug);
        const agents = agentsRes.ok ? agentsRes.data : [];
        return {
          result: {
            trading_strategy: strategy
              ? { set: true, preview: strategy.slice(0, 240) }
              : { set: false },
            telegram_connected: telegram.connected,
            subscribed_screening_slugs: subSlugs,
            has_logged_trades: (tradesCount.count ?? 0) > 0,
            agents: agents.map((a) => ({
              id: a.id,
              name: a.name,
              schedule: a.schedule,
              is_active: a.is_active,
            })),
            agent_limits: limitsRes.ok ? limitsRes.data : null,
          },
        };
      }

      case "save_trading_strategy": {
        const strategy = str(input.strategy).trim();
        if (!strategy) {
          return { result: { ok: false, error: "Strategy text is empty." } };
        }
        const res = await saveTradingStrategy(strategy);
        return {
          result: res,
          statusLabel: res.ok ? "Saved your trading strategy" : undefined,
        };
      }

      case "list_market_screenings": {
        const [screenings, subIds] = await Promise.all([
          listMarketScreenings(),
          getMySubscriptionIds(),
        ]);
        return {
          result: {
            screenings: screenings.map((s) => ({
              slug: s.slug,
              name: s.name,
              description: s.description,
              category: s.category,
              schedule: s.schedule,
              subscribed: subIds.includes(s.id),
            })),
          },
        };
      }

      case "subscribe_to_screening": {
        const slug = str(input.slug).trim();
        if (!slug) return { result: { ok: false, error: "Missing slug." } };
        const sub = await subscribeToMarketScreening(slug);
        if (!sub.ok) return { result: sub };

        // The subscription is the essential write and is now committed. Importing
        // the latest results is heavy and best-effort — bound it so a slow or
        // failing import can't hang the turn (which would block the Telegram step
        // that comes next). On timeout/failure we report it and let onboarding
        // continue; the next scheduled run will populate the picks.
        const importLatest = input.import_latest !== false;
        let imported: { ok: boolean; data?: unknown; error?: string } | null = null;
        if (importLatest) {
          const imp = await withTimeout(
            importLatestMarketScreeningResultForMe(slug),
            20_000,
            () => ({ ok: false as const, error: "Import is taking longer than expected." }),
          );
          imported = imp.ok
            ? { ok: true, data: imp.data }
            : { ok: false, error: imp.error };
        }
        return {
          result: {
            ok: true,
            already_subscribed: sub.data.alreadySubscribed,
            // Subscription succeeded regardless; this only reflects the optional
            // results import so the model can relay it and move on.
            imported,
            import_note:
              imported && !imported.ok
                ? "Subscribed successfully, but the latest results didn't load yet — they'll arrive on the next scheduled run. Continue with setup."
                : undefined,
          },
          statusLabel: sub.data.alreadySubscribed
            ? `Already subscribed to ${slug}`
            : `Subscribed to ${slug}`,
        };
      }

      case "unsubscribe_from_screening": {
        const slug = str(input.slug).trim();
        if (!slug) return { result: { ok: false, error: "Missing slug." } };
        const res = await unsubscribeFromMarketScreening(slug);
        return {
          result: res,
          statusLabel: res.ok ? `Unsubscribed from ${slug}` : undefined,
        };
      }

      case "add_holding": {
        const ticker = str(input.ticker).trim().toUpperCase();
        const quantity = Number(input.quantity);
        const avgPrice = Number(input.avg_price);
        if (!ticker) return { result: { ok: false, error: "Missing ticker." } };
        if (!Number.isFinite(quantity) || quantity <= 0) {
          return { result: { ok: false, error: "Quantity must be a positive number." } };
        }
        if (!Number.isFinite(avgPrice) || avgPrice < 0) {
          return {
            result: { ok: false, error: "Average price must be a non-negative number." },
          };
        }
        const isShort = input.short === true;
        const acquired = str(input.acquired_at).trim();
        const parsed = acquired ? new Date(acquired) : null;
        const executedAt =
          parsed && !Number.isNaN(parsed.getTime())
            ? parsed.toISOString()
            : new Date().toISOString();

        const { error } = await ctx.supabase
          .schema("swingtrader")
          .from("user_trades")
          .insert({
            user_id: ctx.userId,
            side: isShort ? "sell" : "buy",
            position_side: isShort ? "short" : "long",
            ticker,
            quantity,
            price_per_unit: avgPrice,
            currency: str(input.currency).trim().toUpperCase() || "USD",
            executed_at: executedAt,
            notes: "Added during onboarding",
            is_paper: false,
          });
        if (error) return { result: { ok: false, error: error.message } };
        return {
          result: { ok: true, ticker, quantity, avg_price: avgPrice, short: isShort },
          statusLabel: `Added holding: ${quantity} ${ticker}`,
        };
      }

      case "start_telegram_connection": {
        const link = await generateTelegramLink(ctx.supabase, ctx.userId);
        if (!link.ok) return { result: { ok: false, error: link.error } };
        return {
          result: {
            ok: true,
            instructions:
              "A connect button is shown to the user. Ask them to tap it, open Telegram, and press Start. Then call check_telegram_status.",
            expires_at: link.expires_at,
          },
          statusLabel: "Telegram link ready — tap to connect",
          clientEvent: {
            type: "telegram_link",
            deep_link: link.deep_link,
            expires_at: link.expires_at,
          },
        };
      }

      case "check_telegram_status": {
        const status = await getTelegramStatus(ctx.supabase, ctx.userId);
        return {
          result: { connected: status.connected },
          statusLabel: status.connected ? "Telegram connected" : undefined,
        };
      }

      case "get_agent_limits": {
        const res = await getScreeningLimits();
        return { result: res.ok ? res.data : res };
      }

      case "list_agent_jobs": {
        const res = await listScheduledScreenings();
        if (!res.ok) return { result: res };
        return {
          result: {
            agents: res.data.map((a) => ({
              id: a.id,
              name: a.name,
              prompt: a.prompt,
              schedule: a.schedule,
              timezone: a.timezone,
              tickers: a.tickers,
              is_active: a.is_active,
              condition_enabled: a.condition_enabled,
              trigger_condition: a.trigger_condition,
              last_run_at: a.last_run_at,
            })),
          },
        };
      }

      case "create_agent_job": {
        const name_ = str(input.name).trim() || "Untitled Agent";
        const prompt = str(input.prompt).trim();
        const schedule = str(input.schedule).trim();
        if (!prompt) return { result: { ok: false, error: "Prompt is required." } };
        if (!schedule) return { result: { ok: false, error: "Schedule is required." } };
        const conditionEnabled = input.condition_enabled === true;
        const triggerCondition = str(input.trigger_condition).trim();
        if (conditionEnabled && !triggerCondition) {
          return {
            result: {
              ok: false,
              error: "trigger_condition is required when condition_enabled is true.",
            },
          };
        }
        const res = await createScheduledScreening({
          name: name_,
          prompt,
          schedule,
          timezone: str(input.timezone).trim() || "America/New_York",
          tickers: strArr(input.tickers),
          trading_session: (str(input.trading_session) as TradingSession) || "none",
          condition_enabled: conditionEnabled,
          trigger_condition: conditionEnabled ? triggerCondition : null,
        });
        return {
          result: res.ok
            ? { ok: true, id: res.data.id, name: res.data.name }
            : res,
          statusLabel: res.ok ? `Created agent “${res.data.name}”` : undefined,
        };
      }

      case "update_agent_job": {
        const id = str(input.id).trim();
        if (!id) return { result: { ok: false, error: "Missing agent id." } };
        const patch: Parameters<typeof updateScheduledScreening>[1] = {};
        if (typeof input.name === "string") patch.name = input.name.trim();
        if (typeof input.prompt === "string") patch.prompt = input.prompt.trim();
        if (typeof input.schedule === "string") patch.schedule = input.schedule.trim();
        if (typeof input.timezone === "string") patch.timezone = input.timezone.trim();
        if (Array.isArray(input.tickers)) patch.tickers = strArr(input.tickers);
        if (typeof input.trading_session === "string")
          patch.trading_session = input.trading_session as TradingSession;
        if (typeof input.condition_enabled === "boolean") {
          patch.condition_enabled = input.condition_enabled;
          if (typeof input.trigger_condition === "string")
            patch.trigger_condition = input.trigger_condition.trim();
        }
        const res = await updateScheduledScreening(id, patch);
        return {
          result: res.ok ? { ok: true, id: res.data.id } : res,
          statusLabel: res.ok ? "Updated agent" : undefined,
        };
      }

      case "toggle_agent_job": {
        const id = str(input.id).trim();
        if (!id) return { result: { ok: false, error: "Missing agent id." } };
        const active = input.active === true;
        const res = await toggleScreening(id, active);
        return {
          result: res.ok ? { ok: true, is_active: active } : res,
          statusLabel: res.ok ? (active ? "Resumed agent" : "Paused agent") : undefined,
        };
      }

      case "test_agent_job": {
        const id = str(input.id).trim();
        if (!id) return { result: { ok: false, error: "Missing agent id." } };
        const res = await testRunScreening(id);
        return {
          result: res,
          statusLabel: res.ok ? "Test run requested" : undefined,
        };
      }

      default:
        return { result: { ok: false, error: `Unknown tool: ${name}` } };
    }
  } catch (err) {
    return {
      result: {
        ok: false,
        error: err instanceof Error ? err.message : String(err),
      },
    };
  }
}
