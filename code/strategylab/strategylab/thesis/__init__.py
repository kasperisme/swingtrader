"""The thesis lab — mechanisms decomposed into links that can each kill them.

See `thesis.py` for the abstraction and `theses/` for the registered theses.
"""
from .registry import ThesisRegistry
from .thesis import (BLOCKED, FAILS, HOLDS, INCONCLUSIVE, PENDING, SKIPPED,
                     Link, LinkResult, Thesis, link_bar)

__all__ = ["ThesisRegistry", "Thesis", "Link", "LinkResult", "link_bar",
           "PENDING", "HOLDS", "FAILS", "INCONCLUSIVE", "BLOCKED", "SKIPPED"]
