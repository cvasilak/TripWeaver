"""A2A client used by the crew's tools to call external supplier agents.

Flow for one call:
  1. Fetch the supplier's Agent Card from ``<base_url>/.well-known/agent-card.json``
     (discovery — we don't hardcode the supplier's capabilities).
  2. Send an A2A message whose single DataPart carries the search params.
  3. Read the DataPart out of the response and return it as a plain dict.

CrewAI tools are synchronous, so we expose a sync ``query_supplier`` that drives
the async a2a-sdk client via ``asyncio.run``.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import httpx
from a2a.client import A2ACardResolver, A2AClient
from a2a.types import (
    DataPart,
    Message,
    MessageSendParams,
    Part,
    Role,
    SendMessageRequest,
)


def _result_data(response: Any) -> dict[str, Any]:
    """Pull the DataPart dict out of a SendMessageResponse."""
    root = response.root
    result = getattr(root, "result", None)
    if result is None:  # error response
        raise RuntimeError(f"A2A supplier returned an error: {getattr(root, 'error', root)}")
    for part in getattr(result, "parts", []) or []:
        if isinstance(part.root, DataPart):
            return dict(part.root.data)
    raise RuntimeError("A2A response contained no DataPart")


async def _query(base_url: str, params: dict[str, Any], timeout: float) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=timeout) as http:
        card = await A2ACardResolver(http, base_url).get_agent_card()
        client = A2AClient(http, agent_card=card)
        message = Message(
            role=Role.user,
            parts=[Part(root=DataPart(data=params))],
            message_id=str(uuid.uuid4()),
        )
        request = SendMessageRequest(
            id=str(uuid.uuid4()), params=MessageSendParams(message=message)
        )
        response = await client.send_message(request)
        return _result_data(response)


def query_supplier(base_url: str, params: dict[str, Any], timeout: float = 30.0) -> dict[str, Any]:
    """Discover the supplier agent at ``base_url`` and ask it ``params`` (sync)."""
    return asyncio.run(_query(base_url, params, timeout))


async def aquery_supplier(
    base_url: str, params: dict[str, Any], timeout: float = 30.0
) -> dict[str, Any]:
    """Async variant for callers already inside an event loop (e.g. the AG-UI server)."""
    return await _query(base_url, params, timeout)


if __name__ == "__main__":
    # CLI: query a running supplier directly (no crew / no LLM needed). Example:
    #   python -m backend.a2a_client http://127.0.0.1:8001 \
    #       origin=Athens destination=Tokyo depart_date=2026-10-05 travelers=2
    import json
    import sys

    if len(sys.argv) < 2:
        print("usage: python -m backend.a2a_client <base_url> [key=value ...]", file=sys.stderr)
        raise SystemExit(2)

    base = sys.argv[1]
    query = dict(kv.split("=", 1) for kv in sys.argv[2:])  # all values are strings; suppliers cast as needed
    print(json.dumps(query_supplier(base, query), indent=2))
