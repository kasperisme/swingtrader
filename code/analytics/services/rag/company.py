"""
Company scoring against a news impact vector.

Re-exports score_companies and CompanyScore from news/company/company_scorer.
Services should import from here rather than the news service directly.
"""

from __future__ import annotations

from services.news.company.company_scorer import CompanyScore, score_companies

__all__ = ["CompanyScore", "score_companies"]
