"""Tiny helpers for moving structured data over A2A messages.

A2A messages carry a list of *parts*. A ``DataPart`` holds a JSON object, which
is exactly what we want for supplier queries and results — so both the request
(search params) and the response (options) travel as a single DataPart. These
helpers keep the supplier executors readable.
"""

from __future__ import annotations

import uuid
from typing import Any

from a2a.types import DataPart, Message, Part, Role


def extract_query(message: Message | None) -> dict[str, Any]:
    """Return the dict from the first DataPart of an incoming A2A message."""
    if message is None:
        return {}
    for part in message.parts:
        root = part.root
        if isinstance(root, DataPart):
            return dict(root.data)
    return {}


def data_message(data: dict[str, Any], role: Role = Role.agent) -> Message:
    """Wrap a dict as an A2A Message carrying a single structured DataPart."""
    return Message(
        role=role,
        parts=[Part(root=DataPart(data=data))],
        message_id=str(uuid.uuid4()),
    )
