"""strategylab — LLM-in-the-loop reinforcement search over trading strategies.

Environment : purged walk-forward backtest of a parameterised swing strategy
Action      : a mutation of the strategy genome (rules, universe, data, exits)
Reward      : overfitting-aware, risk-adjusted objective anchored on Sharpe
Policy      : Claude proposes experiments; a bandit/TPE/evolution mix explores
Terminal    : a genome that clears the deployment gate on untouched data
"""

__version__ = "0.1.0"
