-- Activate the Second-Order Chain market screening.
-- Bound to script_key = 'second_order_chain'; read by the Philip Fissure agent.

insert into swingtrader.market_screenings (name, slug, script_key, category, schedule, timezone, is_active, is_published, author_user_id, description, llm_prompt)
values (
  'Second-Order Chain',
  'second-order-chain',
  'second_order_chain',
  'relationship-graph',
  '0 7 * * 1-5',
  'Europe/Copenhagen',
  true,
  true,
  '1077d309-5a94-441b-b8d3-52c40c6a45e0',
$desc$When a big story hits one company, the company economically attached to it often has not reacted yet. This board reads the platform's 38,000-edge relationship graph — typed, directional, evidence-backed supplier / customer / partner / competitor links extracted from news — and finds those un-reacted neighbours.

The hard part is not finding connections; it is the three ways this strategy loses, each of which is a filter here rather than a judgement call:

  1. THE NEIGHBOUR HAS ALREADY MOVED. This is a PRICE question, not a news question — sympathy selling moves a stock without generating a single article, so quiet coverage proves nothing. Each candidate's return over the window is compared with the headline's, and anything that has already collected a meaningful share of the move (in either direction) is dropped.
  2. THE SIGN IS BACKWARDS. Edge direction in the graph is unambiguous — `from -[supplier]-> to` means from SUPPLIES to — so the rule is arithmetic: everyone in a value chain moves WITH the headline, a competitor moves AGAINST it.
  3. THE EDGE IS TOO SMALL TO MATTER. A real relationship touching 2% of revenue is a fact, not a trade. Edges are gated on strength and on how many independent articles asserted them.

Pipeline:
  1. Headline names: enough coverage in the last few days to be a real story, and either a strongly one-directional sentiment reading or a large price move. Both are reported, because they disagree more often than you would expect — one recent story ran at +0.31 average sentiment across 75 articles while the stock fell 15%, and a sentiment-only screen would have pointed the wrong way.
  2. Neighbours: every graph edge above a strength and mention floor, deduplicated to ONE edge per pair (the graph stores both directions and sometimes several types for the same pair).
  3. Tradeable: US-listed and liquid enough to enter and exit; the raw graph contains foreign listings that no order could fill.
  4. Sign, then the not-yet-moved test.
  5. Contradictions dropped: a name that two live stories push in OPPOSITE directions is removed rather than resolved, because it has no second-order edge left. Several stories pushing the same way are kept as corroboration.

Each row carries the headline and its move, the neighbour and its move, the share of the move already captured, the edge type / strength / evidence count, and the resulting side.$desc$,
$prompt$You are a second-order analyst. You never trade the company in the headline; you trade the one attached to it that has not reacted yet.

You receive ONE candidate at a time. It has already passed a screen: a real story on the headline name, a strong and well-evidenced graph edge, the correct sign for the relationship type, and — most importantly — a neighbour whose price has NOT yet followed.

What to establish, in order:

1. IS THE MECHANISM REAL? State in one plain sentence how the headline changes this company's revenue or costs. If you cannot, there is no trade — a graph edge is evidence that two companies were discussed together, not that money flows between them.

2. HOW BIG IS IT? This is the question that matters most and the one most often skipped. Roughly what share of this company's revenue does the affected relationship represent? A chipmaker that sells some parts to carmakers is not an automotive stock. A real edge that touches a small division is a fact, not a trade — say so and pass.

3. WHY HAS IT NOT MOVED? There are two answers and they are opposites. Either nobody has made the connection yet, which is your trade — or the market has considered it and concluded it does not matter, which means you are about to learn why. Distinguish them. Check whether the neighbour has its own news that explains the silence.

4. GET THE SIGN RIGHT. The screen computes it, but verify: a supplier is hurt when its customer struggles; a competitor is usually HELPED by a rival's trouble. If your reasoning disagrees with the screen's `side`, say so explicitly and explain — you may be right, and a disagreement is worth recording either way.

5. WHAT WOULD SETTLE IT? Name the measurable thing — an earnings date, a guidance revision, an order announcement — that would confirm or kill this within your holding period.

A caution on horizon. These theses are FUNDAMENTAL: they are about revenue, and revenue moves on a quarterly cycle. A two-week hold is not enough time for the mechanism you just described to appear in any number. Either hold long enough for the mechanism to show up, or be honest that you are trading the market's realisation rather than the fundamental itself — those are different trades with different exits.

Give a verdict, a size proportional to how material the relationship actually is, and the one measurement that would settle it.$prompt$
)
on conflict (slug) do update set
  name        = excluded.name,
  script_key  = excluded.script_key,
  category    = excluded.category,
  schedule    = excluded.schedule,
  timezone    = excluded.timezone,
  is_active   = excluded.is_active,
  is_published= excluded.is_published,
  description = excluded.description,
  llm_prompt  = excluded.llm_prompt;
