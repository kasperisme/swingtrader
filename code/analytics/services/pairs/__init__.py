"""
Pairs-trading / statistical-arbitrage layer on top of the relationship graph.

The news-derived relationship graph (ticker_relationship_edges) supplies the
candidate pairs; this package attaches price-derived cointegration metrics to
each pair and keeps them fresh on two clocks:

  - cointegration  — pure stats (hedge ratio, Engle-Granger, OU half-life)
  - candidates     — candidate pair loading off the graph
  - store          — persistence to swingtrader.ticker_pair_stats
  - calibrate_cli  — slow clock (weekly): full recalibration
  - zscore_cli     — fast clock (daily/intraday): live z-score refresh
"""
