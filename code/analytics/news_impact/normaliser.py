"""
Rank normaliser — converts a universe of raw dimension values to 0–1 rank scores.

For each dimension:
  - Collect all non-None values across tickers
  - Rank them 1..N using fractional ranking (method='average') via scipy
  - Scale to 0–1 by dividing by N
  - Assign 0.5 to any ticker where the raw value was None
"""

import logging
from typing import Optional

import numpy as np
from scipy.stats import rankdata

logger = logging.getLogger(__name__)


def rank_normalise(
    company_data: dict[str, dict[str, Optional[float]]],
) -> dict[str, dict[str, float]]:
    """
    Rank-normalise a universe of raw dimension values.

    Parameters
    ----------
    company_data : {ticker: {dimension_key: raw_value | None}}

    Returns
    -------
    {ticker: {dimension_key: 0-1 rank score}}

    Notes
    -----
    - Tickers with None for a given dimension receive a neutral score of 0.5.
    - Ties receive fractional ranks (average of tied positions).
    - Scale: rank / N, so the range is [1/N, 1.0].  A single-ticker universe
      always scores 1.0 for all non-None values.
    """
    if not company_data:
        return {}

    tickers = list(company_data.keys())

    # Collect all dimension keys across all tickers
    all_keys: set[str] = set()
    for dims in company_data.values():
        all_keys.update(dims.keys())

    # Initialise output with 0.5 (neutral default for missing data)
    output: dict[str, dict[str, float]] = {t: {} for t in tickers}

    for key in all_keys:
        # Build parallel arrays: ticker index → raw value (or None)
        raw_values: list[Optional[float]] = [
            company_data[t].get(key) for t in tickers
        ]

        # Separate valid and missing indices
        valid_indices = [i for i, v in enumerate(raw_values) if v is not None]
        missing_indices = [i for i, v in enumerate(raw_values) if v is None]

        if not valid_indices:
            # All None — assign 0.5 to everyone
            for t in tickers:
                output[t][key] = 0.5
            logger.debug("[normaliser] %s: all values None, assigning 0.5", key)
            continue

        valid_raw = np.array([raw_values[i] for i in valid_indices], dtype=float)
        n = len(valid_raw)

        # Rank 1..N, fractional for ties
        ranks = rankdata(valid_raw, method="average")
        # Scale to (0, 1]: divide by N
        scores = ranks / n

        # Write scores for valid tickers
        for list_pos, ticker_idx in enumerate(valid_indices):
            output[tickers[ticker_idx]][key] = float(scores[list_pos])

        # Write 0.5 for tickers with None
        for ticker_idx in missing_indices:
            output[tickers[ticker_idx]][key] = 0.5

        if missing_indices:
            missing_tickers = [tickers[i] for i in missing_indices]
            logger.debug(
                "[normaliser] %s: %d/%d tickers missing → 0.5 (%s)",
                key, len(missing_indices), len(tickers), missing_tickers,
            )

    return output


if __name__ == "__main__":
    # Quick sanity check
    sample = {
        "AAPL": {"debt_burden": 2.0, "pe": 30.0, "growth": None},
        "MSFT": {"debt_burden": 1.0, "pe": 35.0, "growth": 0.15},
        "NVDA": {"debt_burden": 0.5, "pe": None,  "growth": 0.40},
        "JPM":  {"debt_burden": 5.0, "pe": 12.0,  "growth": 0.05},
    }
    result = rank_normalise(sample)
    print("Rank-normalised scores:")
    keys = sorted({k for d in sample.values() for k in d})
    header = f"{'ticker':<8}" + "".join(f"{k:<14}" for k in keys)
    print(header)
    for ticker, scores in result.items():
        row = f"{ticker:<8}" + "".join(f"{scores.get(k, 0.5):<14.3f}" for k in keys)
        print(row)
