"""LLM configuration for the TripWeaver crew.

CrewAI 1.x ships a *native* Anthropic provider: passing a model id prefixed with
``anthropic/`` makes CrewAI call Claude through the official ``anthropic`` SDK
(installed via the ``crewai[anthropic]`` extra) rather than a generic shim.

We default to **Claude Sonnet 4.5** — the latest Sonnet that CrewAI 1.14.7 routes
through Anthropic's *native* structured-outputs beta when a task uses
``output_pydantic``. That path makes the final ``TripPlan`` reliably
schema-conforming. (Newer models such as Sonnet 4.6 / Opus 4.8 aren't yet on
CrewAI's allow-list for that beta, so they fall back to a forced-tool path that
intermittently returns partial objects and only recovers via agent retries —
which is why we pin a natively supported version here.)

We deliberately do NOT set ``temperature`` or ``thinking``: CrewAI only sends a
parameter when you set it, so leaving them unset produces a clean request that
works across models (several recent Claude models reject sampling parameters).
"""

from __future__ import annotations

import os

from crewai import LLM

# Latest Sonnet on CrewAI 1.14.7's native structured-outputs allow-list. Other
# allow-listed options if you want to trade cost/quality (all support the native
# path): anthropic/claude-opus-4-5 (stronger), anthropic/claude-haiku-4-5 (cheapest).
DEFAULT_MODEL = "anthropic/claude-sonnet-4-5"


def get_llm() -> LLM:
    """Return the LLM the agents use.

    Override the model with the ``TRIPWEAVER_MODEL`` env var (e.g.
    ``anthropic/claude-haiku-4-5`` while learning, to cut cost). For reliable
    structured output, prefer a model on CrewAI's native allow-list (the Claude
    4.5 generation). The Anthropic provider reads ``ANTHROPIC_API_KEY`` from the
    environment automatically.
    """
    model = os.getenv("TRIPWEAVER_MODEL", DEFAULT_MODEL)
    # max_tokens is an output-budget cap, not a sampling parameter, so it's safe
    # to set on Opus. We raise it from the provider's 4096 default to give the
    # final structured TripPlan (a long, nested object) room so it can't truncate.
    return LLM(model=model, max_tokens=8192)
