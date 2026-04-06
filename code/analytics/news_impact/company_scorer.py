"""
Score a list of company vectors against a news impact vector.

For each company:
    score = sum(company.dimensions[dim] * impact_score
                for dim, impact_score in impact_vector.items())

Companies not present in the impact vector contribute 0 for missing dimensions.
"""

import logging
from dataclasses import dataclass

from news_impact.company_vector import CompanyVector

logger = logging.getLogger(__name__)


@dataclass
class CompanyScore:
    ticker:   str
    score:    float
    drivers:  list[tuple[str, float]]  # top 3 (dimension_key, contribution)
    metadata: dict


def score_companies(
    impact_vector: dict[str, float],
    company_vectors: list[CompanyVector],
    top_n: int = 10,
) -> list[CompanyScore]:
    """
    Score each company against the impact vector and return sorted results.

    Parameters
    ----------
    impact_vector    : {dimension_key: impact_score} from aggregate_heads()
    company_vectors  : list of CompanyVector (rank-normalised 0-1 dimensions)
    top_n            : return at most top_n companies (by abs score); pass 0 for all

    Returns
    -------
    List of CompanyScore sorted by score descending (highest tailwind first).
    """
    if not impact_vector:
        logger.warning("[company_scorer] empty impact vector — all scores will be 0")

    scores: list[CompanyScore] = []

    n_dims = len(impact_vector) or 1  # avoid div-by-zero

    for cv in company_vectors:
        total   = 0.0
        contribs: dict[str, float] = {}

        for dim, impact in impact_vector.items():
            # Company dimension value: use 0.5 (neutral) if not in vector
            company_val = cv.dimensions.get(dim, 0.5)
            contrib     = company_val * impact
            total      += contrib
            if abs(contrib) > 0:
                contribs[dim] = contrib

        # Normalise to [-1, +1] by dividing by the number of active dimensions
        normalised = total / n_dims

        # Top 3 drivers by absolute contribution
        drivers = sorted(contribs.items(), key=lambda x: abs(x[1]), reverse=True)[:3]

        scores.append(CompanyScore(
            ticker=cv.ticker,
            score=round(normalised, 4),
            drivers=drivers,
            metadata=cv.metadata,
        ))

    scores.sort(key=lambda x: x.score, reverse=True)

    if top_n and top_n < len(scores):
        # Keep top_n/2 tailwinds and top_n/2 headwinds
        half = top_n // 2
        tailwinds  = [s for s in scores if s.score >= 0][:half]
        headwinds  = [s for s in scores if s.score < 0][-half:]
        # Merge: tailwinds (desc) + headwinds (desc by abs = asc in raw score)
        return tailwinds + list(reversed(headwinds))

    return scores


if __name__ == "__main__":
    import asyncio
    import pathlib
    from dotenv import load_dotenv
    from news_impact.company_vector import build_vectors

    load_dotenv(pathlib.Path(__file__).parent.parent / ".env")

    # Minimal demo with a hand-crafted impact vector
    _IMPACT = {
        "interest_rate_sensitivity": -0.8,
        "debt_burden":               -0.7,
        "sector_financials":         +0.6,
        "price_momentum":            -0.4,
        "valuation_multiple":        -0.5,
    }

    async def _demo():
        vectors = await build_vectors(["AAPL", "MSFT", "JPM", "XOM"], use_cache=True)
        results = score_companies(_IMPACT, vectors)
        print(f"\nCompany scores against demo impact vector:")
        for cs in results:
            drivers_str = ", ".join(f"{d}:{v:+.2f}" for d, v in cs.drivers)
            print(f"  {cs.ticker:<6} {cs.score:+.3f}  [{drivers_str}]")

    asyncio.run(_demo())
