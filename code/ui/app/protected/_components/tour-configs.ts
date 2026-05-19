/**
 * Tour configuration registry.
 *
 * Editing the per-page guided tours starts and ends in this file. Each tour is
 * pure data — selectors, titles, copy. The PageTour component reads from this
 * registry by key; pages mount <PageTour tourKey="..." /> and that's it.
 *
 * To add a step: add a TourStep object. To add a tour: add a key to TourKey
 * and an entry to TOURS. To retarget an element: change the selector.
 *
 * Selectors should target [data-tour="..."] attributes on rendered elements.
 * Tours degrade gracefully — Driver.js skips steps whose target is missing.
 */

import type { TourKey } from "@/app/actions/onboarding";

export type TourStep = {
  /** CSS selector. Prefer [data-tour="..."] for stability. Omit for centered modal step. */
  selector?: string;
  title: string;
  description: string;
  side?: "top" | "bottom" | "left" | "right" | "over";
  align?: "start" | "center" | "end";
};

export type TourConfig = {
  key: TourKey;
  /** Shown in the "Take the tour" button label, never inside Driver.js itself. */
  label: string;
  /** Route the tour belongs to (where the elements actually exist). */
  route: string;
  /** One-line summary used to brief AI/help surfaces. */
  summary: string;
  steps: ReadonlyArray<TourStep>;
};

export const TOURS: Record<TourKey, TourConfig> = {
  profile: {
    key: "profile",
    label: "Tour profile setup",
    route: "/protected/profile",
    summary:
      "Set the trading strategy, connect Telegram, manage subscription and (optional) API access.",
    steps: [
      {
        title: "Set up your account",
        description:
          "Three things to set here: your trading strategy, your Telegram, and your subscription. Each one changes what the rest of the platform does for you.",
      },
      {
        selector: '[data-tour="trading-strategy"]',
        title: "Your trading strategy",
        description:
          "Tell the system how you trade — timeframe, risk tolerance, asset focus. AI agents and screen scoring use this as the lens. Without it, every ticker grades the same.",
        side: "bottom",
      },
      {
        selector: '[data-tour="telegram-connect"]',
        title: "Telegram delivery",
        description:
          "Connect Telegram and the platform pings you only when something matters — agent triggers, daily narrative, screening alerts. The system runs even when you're not on the site.",
        side: "bottom",
      },
      {
        selector: '[data-tour="subscription"]',
        title: "Subscription & billing",
        description:
          "Your plan controls how deep the impact history goes, how many agents you can run, and which screens are unlocked. Manage it here.",
        side: "bottom",
      },
      {
        selector: '[data-tour="api-keys"]',
        title: "API access (optional)",
        description:
          "Pull screen results, news scores, and your portfolio into your own tools via REST or MCP. Skip if you only use the website.",
        side: "bottom",
      },
    ],
  },

  articles: {
    key: "articles",
    label: "Tour the article feed",
    route: "/articles",
    summary:
      "Read the news feed: how every headline gets scored across sentiment, novelty, magnitude, and ticker relevance.",
    steps: [
      {
        title: "How news becomes a tradeable signal",
        description:
          "Every headline is broken down across multiple dimensions and combined into an impact score. Knowing the breakdown is what lets you trust — or override — the score.",
      },
      {
        selector: '[data-tour="article-list"]',
        title: "The feed",
        description:
          "Headlines ranked by impact across the universe you care about. Newest at top, highest impact float up via the score.",
        side: "right",
      },
      {
        selector: '[data-tour="article-impact-score"]',
        title: "Impact score",
        description:
          "The composite — sentiment × novelty × magnitude × ticker relevance. A 0–100 grade for whether this article will move price.",
        side: "left",
      },
      {
        selector: '[data-tour="article-dimensions"]',
        title: "Dimension breakdown",
        description:
          "The score's ingredients. Sentiment (direction), novelty (is this new info?), magnitude (size of the event), relevance (does it actually touch this ticker?). Click any dimension to see why it scored that way.",
        side: "left",
      },
      {
        selector: '[data-tour="article-tickers"]',
        title: "Linked tickers",
        description:
          "Every article surfaces the names it touches. Click a ticker to jump straight to the chart with this article pinned as context.",
        side: "left",
      },
      {
        selector: '[data-tour="article-filters"]',
        title: "Filters",
        description:
          "Narrow by sector, sentiment, impact threshold, time window. Use this to turn the feed into your own signal queue.",
        side: "bottom",
      },
    ],
  },

  news_trends: {
    key: "news_trends",
    label: "Tour news trends",
    route: "/protected/news-trends",
    summary:
      "Cluster news themes by aggregate impact across a chosen time window — read the regime, not single headlines.",
    steps: [
      {
        title: "Zoom out from one article to the regime",
        description:
          "Articles are scored individually — but the same dimensions cluster across the day. News Trends reveals which themes are accumulating impact, so you stop reacting to single headlines and start reading the regime.",
      },
      {
        selector: '[data-tour="trends-list"]',
        title: "Trending themes",
        description:
          "Topics ranked by aggregate impact across recent news. A trend is many articles pointing the same direction.",
        side: "right",
      },
      {
        selector: '[data-tour="trends-window"]',
        title: "Time window",
        description:
          "Toggle the lookback. Short windows surface what's hot right now; long windows reveal slower regime shifts you'd otherwise miss.",
        side: "bottom",
      },
      {
        selector: '[data-tour="trends-sentiment"]',
        title: "Sentiment direction",
        description:
          "The aggregate sentiment of the trend's underlying articles. A trend can be hot AND bearish — both pieces matter for which side of the trade to take.",
        side: "left",
      },
      {
        selector: '[data-tour="trends-tickers"]',
        title: "Tickers in the trend",
        description:
          "The names this theme is touching. Often where the trade idea actually lives — exposure to a hot theme that's not yet priced in.",
        side: "left",
      },
    ],
  },

  relations: {
    key: "relations",
    label: "Tour the relations graph",
    route: "/protected/relations",
    summary:
      "Explore the ticker/entity relationship graph: who is exposed to whom, and which articles established the link.",
    steps: [
      {
        title: "Who's actually exposed",
        description:
          "Every news article is linked to the tickers, sectors, and entities it touches. The relationship graph turns one headline into a list of who gets hit — second-order moves you'd otherwise miss.",
      },
      {
        selector: '[data-tour="relations-graph"]',
        title: "The graph",
        description:
          "Nodes are tickers and entities. Edges are relationships — supplier, competitor, sector peer, news co-mention. Drag to explore.",
        side: "left",
      },
      {
        selector: '[data-tour="relations-search"]',
        title: "Start from a ticker",
        description:
          "Search any name to anchor the graph on it. The connected nodes are your second-order plays when news hits your anchor.",
        side: "bottom",
      },
      {
        selector: '[data-tour="relations-edges"]',
        title: "Edge weight & traceability",
        description:
          "Thicker edges = stronger relationship. Click an edge to see which articles and filings established the link — every connection is traceable, not a black box.",
        side: "right",
      },
      {
        selector: '[data-tour="relations-filters"]',
        title: "Filter by relationship type",
        description:
          "Show only suppliers, only sector peers, only news-cluster co-mentions. Use this to find the right kind of exposure for the kind of news you're trading.",
        side: "bottom",
      },
    ],
  },

  charts: {
    key: "charts",
    label: "Tour the chart workspace",
    route: "/protected/charts",
    summary:
      "Chart workspace: ticker search, candles + indicators, AI analyst panel, and the 'Add to screening' button.",
    steps: [
      {
        title: "Pin news to candles",
        description:
          "Charts brings together price action, technical context, and an AI analyst that explains what the price is reacting to — using the same impact scores and dimensions you've now learned.",
      },
      {
        selector: '[data-tour="chart-ticker-input"]',
        title: "Pick a ticker",
        description:
          "Type any symbol. The chart, indicators, and AI panel all retarget around it. Bookmarkable URL — share workspaces with one link.",
        side: "bottom",
      },
      {
        selector: '[data-tour="chart-canvas"]',
        title: "The chart itself",
        description:
          "Candles plus your indicators. News events with impact above your threshold are pinned directly to the bars they happened on.",
        side: "top",
      },
      {
        selector: '[data-tour="chart-ai-panel"]',
        title: "AI analyst",
        description:
          "Ask in plain English: 'why is this ripping?', 'what's the next catalyst?', 'how does today compare to the last earnings reaction?' The model has the news, the impact scores, and the price.",
        side: "left",
      },
      {
        selector: '[data-tour="chart-indicators"]',
        title: "Indicators & timeframe",
        description:
          "Toggle indicators and timeframes. Workspace settings persist per ticker so you don't reconfigure every visit.",
        side: "bottom",
      },
      {
        selector: '[data-tour="add-to-screening"]',
        title: "Add this ticker to a screening",
        description:
          "Found something worth watching? Drop it into an existing screening or spin up a new one right here — no leaving the chart. The screener page is where you'll work the list afterwards.",
        side: "bottom",
        align: "end",
      },
    ],
  },

  screenings: {
    key: "screenings",
    label: "Tour the screener",
    route: "/protected/screenings",
    summary:
      "The screener: create named screenings, switch between them, narrow with filters, and work the resulting list.",
    steps: [
      {
        title: "Turn the universe into a shortlist",
        description:
          "A screening is a named list of tickers you're tracking, scored by the dimensions you've learned — impact, sentiment, fundamentals, trend templates. This is how passive reading becomes a daily list of names worth a closer look.",
      },
      {
        selector: '[data-tour="screen-create"]',
        title: "Create a screening",
        description:
          "Type a name (e.g. 'Bullish breakouts') and click Create. Empty screenings live here until you start dropping tickers into them — that's the next step.",
        side: "bottom",
        align: "end",
      },
      {
        selector: '[data-tour="screen-runs"]',
        title: "Switch between screenings",
        description:
          "Each card is one of your saved screenings. Click a card to load its tickers; the filter bar and results below update around it.",
        side: "bottom",
      },
      {
        title: "How tickers get added",
        description:
          "Tickers come into a screening from two places: the Charts page (the 'Add to screening' button on any chart) or the article and trends views (click any linked ticker → 'Add to screening'). Anything you add lands in the active screening — switch screenings first if you want it elsewhere.",
      },
      {
        selector: '[data-tour="screen-filters"]',
        title: "Narrow the list",
        description:
          "Stack filters on top of the active screening: sentiment direction, impact threshold, sector, market cap, technical setup. Each filter narrows the results live without touching the underlying ticker list.",
        side: "bottom",
      },
      {
        selector: '[data-tour="screen-results"]',
        title: "Work the results",
        description:
          "What survived the filters. Sort by impact, recent move, or fundamentals. Click any row to jump to its chart with the context preserved — and from there you can add even more tickers to this screening.",
        side: "top",
      },
    ],
  },

  trade: {
    key: "trade",
    label: "Tour trade logging",
    route: "/protected/trades",
    summary:
      "Log entries and exits; the portfolio table, equity curve, and P&L derive from this.",
    steps: [
      {
        title: "Log entries and exits",
        description:
          "Logging trades turns on the portfolio table, equity curve, and P&L on your dashboard. It's also how the platform learns which kinds of setups actually work for you over time.",
      },
      {
        selector: '[data-tour="trade-add"]',
        title: "Add a trade",
        description:
          "Ticker, side, quantity, price, executed-at. That's the minimum. Notes and account label are optional but useful when you review later.",
        side: "bottom",
      },
      {
        selector: '[data-tour="trade-list"]',
        title: "Trade history",
        description:
          "Every entry and exit chronologically. The portfolio table on your dashboard derives from this — net positions, average entry, currency totals.",
        side: "top",
      },
      {
        selector: '[data-tour="trade-portfolio"]',
        title: "Portfolio summary",
        description:
          "Built from your trades. Open positions, unrealized P&L, equity curve. Returns to your dashboard so it's the first thing you see when you log in.",
        side: "left",
      },
    ],
  },

  agent: {
    key: "agent",
    label: "Tour AI agents",
    route: "/protected/agents",
    summary:
      "AI agents: natural-language screenings that run on a cron and ping Telegram only when they trigger.",
    steps: [
      {
        title: "Eyes on the market while you sleep",
        description:
          "An AI agent is a natural-language screening that runs on a cron and pings your Telegram only when it triggers. This is the payoff of every prior step — the platform watching the market for you.",
      },
      {
        selector: '[data-tour="agent-create"]',
        title: "Create an agent",
        description:
          "Describe the setup in plain English: 'tech stocks with bullish news impact > 70 and a breakout from 50-day high'. The agent translates that into the screen.",
        side: "left",
      },
      {
        selector: '[data-tour="agent-schedule"]',
        title: "Schedule",
        description:
          "Set when it runs — pre-market, hourly, end-of-day. Cron syntax under the hood; presets cover most use cases.",
        side: "bottom",
      },
      {
        selector: '[data-tour="agent-list"]',
        title: "Your agents",
        description:
          "Active agents and their last-run status. Pause or edit any of them. Triggers ping Telegram and persist here so you can review them later.",
        side: "top",
      },
      {
        selector: '[data-tour="agent-results"]',
        title: "Run history",
        description:
          "Every run, whether it triggered or not, and the names that came through. Use this to tune the prompt — too many false positives, tighten it; nothing triggering, loosen it.",
        side: "left",
      },
    ],
  },
};

/* -------------------------------------------------------------------------- */
/*  How-to index — flat view of TOURS for AI/help surfaces                    */
/* -------------------------------------------------------------------------- */

export type HowToEntry = {
  tourKey: TourKey;
  /** 0-based step index inside the tour. */
  stepIndex: number;
  /** Total steps in the tour, so callers can compute end-of-tour ranges. */
  totalSteps: number;
  route: string;
  title: string;
  description: string;
  /** True if the step targets a real DOM anchor (vs a centered explainer). */
  hasAnchor: boolean;
};

/** Flatten TOURS to a single ordered list of how-to entries. */
export function listHowToEntries(): HowToEntry[] {
  const out: HowToEntry[] = [];
  for (const tour of Object.values(TOURS)) {
    tour.steps.forEach((step, idx) => {
      out.push({
        tourKey: tour.key,
        stepIndex: idx,
        totalSteps: tour.steps.length,
        route: tour.route,
        title: step.title,
        description: step.description,
        hasAnchor: !!step.selector,
      });
    });
  }
  return out;
}

/** A compact, prompt-ready brief of every tour for AI surfaces.
 * One line per step so a model can scan it and pick a tourKey + step range. */
export function howToBriefMarkdown(): string {
  const sections: string[] = [];
  for (const tour of Object.values(TOURS)) {
    const header = `### ${tour.key} — ${tour.summary} (route: ${tour.route})`;
    const lines = tour.steps.map(
      (step, idx) => `  ${idx}. ${step.title} — ${step.description}`,
    );
    sections.push([header, ...lines].join("\n"));
  }
  return sections.join("\n\n");
}

/** Build the URL that drives a tour (or a slice of one) when the user lands on it. */
export function howToUrl(
  tourKey: TourKey,
  fromStep?: number,
  toStep?: number,
): string {
  const tour = TOURS[tourKey];
  const params = new URLSearchParams({ tour: "1" });
  if (typeof fromStep === "number" && fromStep > 0) {
    params.set("step", String(fromStep));
  }
  if (typeof toStep === "number" && toStep < tour.steps.length - 1) {
    params.set("end", String(toStep));
  }
  return `${tour.route}?${params.toString()}`;
}
