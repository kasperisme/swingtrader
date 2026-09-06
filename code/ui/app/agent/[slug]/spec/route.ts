import { getAgent } from "@/app/actions/arena";
import { SITE_URL } from "@/lib/site";

/**
 * The agent's build spec, as a downloadable JSON config.
 *
 * Everything here comes from `arena_agents_public_v` — the same view every
 * other public surface reads. The base table carries a few more knobs (the model
 * id, the exposure target, the tool-round cap, the strategy key), and this route
 * deliberately does NOT reach past the view to get them: the view is where the
 * decision about what is published lives, and a download that quietly widened it
 * would be a leak with a filename. `notPublished` names them instead, so the
 * spec is honest about what it omits rather than silently incomplete.
 *
 * The system prompt IS published, and is the largest thing in this file. Across
 * the roster the model, broker, limits and universe are identical — the prompt
 * and the tool surface are the entire independent variable, so a spec that
 * described them instead of quoting them would not be reproducible.
 *
 * The rules block is not agent-specific — it is the arena's, identical for all
 * nine — but a spec you can act on has to state them, because they are what
 * makes a reproduction comparable rather than merely similar.
 */

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ slug: string }> },
) {
  const { slug } = await params;
  const agent = await getAgent(slug);
  if (!agent) {
    return Response.json({ error: "Agent not found" }, { status: 404 });
  }

  const spec = {
    specVersion: 1,
    generatedAt: new Date().toISOString().slice(0, 10),
    source: `${SITE_URL}/agent/${agent.slug}`,
    license:
      "Published so the experiment can be reproduced and checked. Paper trading; nothing here is investment advice.",
    disclaimer:
      `${agent.name} is a cheap knock-off, not a person. It is a general-purpose language model given a caricature of a public method and one narrow slice of one website's data, run as an experiment. Nothing in this spec or in the results it points at reflects the record, holdings, opinions or skill of the investor the name alludes to, and that person is not involved in or aware of it. Treat every number as experimental.`,

    agent: {
      slug: agent.slug,
      name: agent.name,
      tagline: agent.tagline,
      modelledOn: agent.inspiration,
      // A "deterministic" agent runs a fixed rule and never calls a model. They
      // exist so the reasoning agents have something to beat.
      engine: agent.engine,
      approach: agent.approach,
    },

    // Verbatim, as the agent receives it. The persona is the top; everything
    // below it is the shared operating contract every LLM agent is given
    // identically, so that the only difference between two agents is the thesis
    // and the data.
    systemPrompt: agent.system_prompt || null,
    systemPromptNote:
      agent.engine === "deterministic"
        ? "None: a control runs a fixed rule and never calls a model."
        : "Verbatim. The shared operating rules are appended to every LLM agent's persona identically — mechanics live there, never in a persona, or the agents stop being comparable.",

    account: {
      startingCash: agent.starting_cash,
      currency: "USD",
      fundedOn: agent.funded_on,
    },

    riskLimits: {
      maxPositionPctOfNav: agent.max_position_pct,
      maxOpenPositions: agent.max_positions,
      allowShorts: agent.allow_shorts,
    },

    // The slice of the platform this agent is allowed to read. The difference
    // between these lists, across the roster, IS the experiment: same model,
    // same broker, same limits, different data.
    dataSurfaceNote:
      agent.engine === "deterministic"
        ? "Empty by design: a control reads nothing. It runs a fixed rule."
        : undefined,
    dataSurface: (agent.tool_surface ?? []).map((t) => ({
      tool: t.name,
      label: t.label,
      reads: t.reads,
      publishedAt: t.href.startsWith("http") ? t.href : `${SITE_URL}${t.href}`,
    })),

    rules: {
      cadence: "One decision per trading session, taken after the close.",
      fills:
        "Orders fill at the NEXT session's open — never the close the decision was made on. Filling at that close would hand every agent a free overnight gap.",
      slippage: "Modelled on fill; the same model for every agent.",
      marks: "Positions are marked to each session's close.",
      writes:
        "The model's only write is an order intent. Cash, positions, fills, realised P&L and NAV are computed in Python from the tables, so an agent cannot mark its own book or revise a fill after the outcome is known.",
      rejectedOrders:
        "Orders the broker refuses are stored, not discarded, and published with the reason.",
      accounting:
        "Return, drawdown and Sharpe are computed WITHIN one championship; every agent is re-funded at the start of each.",
    },

    notPublished: [
      "The model id and backend — one setting for the whole roster, because changing it mid-competition invalidates the comparison.",
      "Gross exposure target and cap.",
      "Maximum tool rounds per decision.",
      "The internal strategy key.",
    ],

    // A control has no model to hand tools to; telling someone to give it a
    // data surface would describe a different agent from the one they are
    // reading about.
    howToReproduce:
      agent.engine === "deterministic"
        ? [
            "Fund a paper account with the starting cash above.",
            "Run the fixed rule described in `agent.approach`. There is no model and no reasoning step — that is what makes it a control.",
            "Fill its orders at the next session's open with modelled slippage, and compute cash, positions and NAV yourself from the fills.",
            "Mark to the close, and hold the result to exactly the same accounting as every reasoning agent. A benchmark measured differently is not a benchmark.",
          ]
        : [
            "Fund a paper account with the starting cash above.",
            "Give the model `systemPrompt` verbatim and the data surface above — and nothing else. The constraint is the point.",
            "Once per session, after the close, ask it for order intents only.",
            "Fill those intents at the next session's open with modelled slippage, and compute cash, positions and NAV yourself from the fills.",
            "Mark to the close, record refused orders with their reason, and never let the model revise a fill after the fact.",
          ],

    record: {
      profile: `${SITE_URL}/agent/${agent.slug}`,
      leaderboard: `${SITE_URL}/arena`,
    },
  };

  return new Response(JSON.stringify(spec, null, 2), {
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Content-Disposition": `attachment; filename="${agent.slug}.arena-agent.json"`,
      // Cheap to build, and it must never be served stale after a roster edit.
      "Cache-Control": "no-store",
    },
  });
}
