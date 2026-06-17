"""FlightSupplier — a standalone A2A agent that "sells" flights.

Run it:
    uv run python -m a2a_suppliers.flight_supplier        # serves on 127.0.0.1:8001
    PORT=9001 uv run python -m a2a_suppliers.flight_supplier

Discover it:
    curl http://127.0.0.1:8001/.well-known/agent-card.json

It returns canned data (same shape as the Phase 1 mock), but the data now
crosses a real A2A boundary instead of a local function call.
"""

from __future__ import annotations

import os

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.apps import A2AStarletteApplication
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentSkill

from a2a_suppliers.protocol import data_message, extract_query


def _flight_options(origin: str, destination: str, depart_date: str) -> list[dict]:
    """Mock inventory. Echoes the requested route/date so the response is clearly
    a reply to *this* query (Phase 3+ could call a real GDS here instead)."""
    base = [
        {"airline": "Aegean + ANA (codeshare)", "stops": 1, "duration_hours": 16.5, "price_per_person": 920},
        {"airline": "Qatar Airways", "stops": 1, "duration_hours": 18.0, "price_per_person": 845},
        {"airline": "Emirates", "stops": 2, "duration_hours": 22.5, "price_per_person": 780},
    ]
    return [
        {"from": origin, "to": destination, "depart_date": depart_date, "currency": "EUR", **opt}
        for opt in base
    ]


class FlightSupplierExecutor(AgentExecutor):
    """Bridges the A2A protocol to our (mock) flight-search logic."""

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        q = extract_query(context.message)
        result = {
            "travelers": int(q.get("travelers", 1)),
            "options": _flight_options(
                q.get("origin", "?"), q.get("destination", "?"), q.get("depart_date", "")
            ),
        }
        await event_queue.enqueue_event(data_message(result))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        # Stateless one-shot supplier — nothing to cancel.
        return None


def build_agent_card(url: str) -> AgentCard:
    return AgentCard(
        name="FlightSupplier",
        description="Searches round-trip flights between two cities and returns ranked options.",
        url=url,
        version="1.0.0",
        capabilities=AgentCapabilities(streaming=False, push_notifications=False),
        default_input_modes=["application/json"],
        default_output_modes=["application/json"],
        skills=[
            AgentSkill(
                id="search_flights",
                name="Search Flights",
                description=(
                    "Given origin, destination, depart_date and travelers, return flight "
                    "options (airline, stops, duration, price per person)."
                ),
                tags=["flights", "travel", "air"],
                examples=["Find flights from Athens to Tokyo departing 2026-10-05 for 2 travelers"],
            )
        ],
    )


def build_app(url: str):
    handler = DefaultRequestHandler(
        agent_executor=FlightSupplierExecutor(), task_store=InMemoryTaskStore()
    )
    return A2AStarletteApplication(agent_card=build_agent_card(url), http_handler=handler).build()


def main() -> None:
    import uvicorn

    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8001"))
    url = f"http://{host}:{port}/"
    print(f"FlightSupplier A2A agent listening on {url}")
    uvicorn.run(build_app(url), host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
