"""Autonomous research — the lab running itself.

What a 24/7 researcher needs beyond a search loop: an LLM layer that validates
rather than trusts its models, budgets and stopping rules so it cannot destroy
its own statistical validity while nobody is watching, a findings store that
demands replication before believing anything, and a daemon to tie them together.
"""

from .llm import Client, LLMResult  # noqa: F401
