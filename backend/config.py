"""LLM configuration for the TripWeaver crew.

CrewAI 1.x ships a *native* Anthropic provider: passing a model id prefixed with
``anthropic/`` makes CrewAI call Claude through the official ``anthropic`` SDK
(installed via the ``crewai[anthropic]`` extra) rather than a generic shim.

We default to Claude Opus 4.8. Note we deliberately do NOT set ``temperature``
or ``thinking``: Opus 4.x rejects sampling parameters, and CrewAI only sends a
parameter when you set it — so leaving them unset produces a clean request.
"""

from __future__ import annotations

import os

from crewai import LLM

DEFAULT_MODEL = "anthropic/claude-opus-4-8"


def get_llm() -> LLM:
    """Return the LLM the agents use.

    Override the model with the ``TRIPWEAVER_MODEL`` env var (e.g.
    ``anthropic/claude-sonnet-4-6`` while learning, to cut cost). The Anthropic
    provider reads ``ANTHROPIC_API_KEY`` from the environment automatically.
    """
    model = os.getenv("TRIPWEAVER_MODEL", DEFAULT_MODEL)
    return LLM(model=model)
