"""One place to resolve which Ollama model an agent runs on.

Every agent used to build its own fallback chain, and those chains borrowed
each other's variables: the screening agents scheduled from the UI resolved
``OLLAMA_TIKTOK_MODEL`` -> ``OLLAMA_BLOG_MODEL`` -> ``gemma4:e4b``, so in
practice they ran on whatever the *blog* generator was configured with. One
subsystem's setting silently decided another's model.

So there is now a single shared variable — ``OLLAMA_MODEL`` — plus an optional
per-subsystem override for the cases that genuinely need a different model (a
tool-calling model for one agent, a cheaper one for another). Precedence:

    <subsystem override env> -> OLLAMA_MODEL -> DEFAULT_MODEL

Nothing falls back to another subsystem's variable. Set ``OLLAMA_MODEL`` in
``code/analytics/.env`` to move every agent at once.

The arena deliberately does NOT use this: ``services/arena/decide.py`` resolves
``ARENA_MODEL`` alone, because an arena whose agents ran on different models
measures the models rather than the data slices the experiment is about.
"""
from __future__ import annotations

import os

#: The shared variable. Set this to change every agent's model at once.
SHARED_MODEL_ENV = "OLLAMA_MODEL"

#: Used only when neither an override nor the shared variable is set.
DEFAULT_MODEL = "glm-5.1:cloud"

DEFAULT_BASE_URL = "http://localhost:11434"


def resolve_model(*override_envs: str, default: str = DEFAULT_MODEL) -> str:
    """The model to run on: first override set, else OLLAMA_MODEL, else default.

    ``override_envs`` are subsystem-specific variable names, tried in order.
    Blank values are ignored so an empty entry in a .env file falls through to
    the shared variable instead of resolving to "".
    """
    for name in (*override_envs, SHARED_MODEL_ENV):
        value = (os.environ.get(name) or "").strip()
        if value:
            return value
    return default


def resolve_base_url(env: str = "OLLAMA_BASE_URL") -> str:
    return (os.environ.get(env) or DEFAULT_BASE_URL).rstrip("/")
