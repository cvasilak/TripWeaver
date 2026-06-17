"""HotelSupplier — a standalone A2A agent that "sells" lodging.

Run it:
    uv run python -m a2a_suppliers.hotel_supplier         # serves on 127.0.0.1:8002
    PORT=9002 uv run python -m a2a_suppliers.hotel_supplier

Discover it:
    curl http://127.0.0.1:8002/.well-known/agent-card.json
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


def _hotel_options(city: str) -> list[dict]:
    base = [
        {"name": "Hotel Ryumeikan", "area": "Marunouchi (near Tokyo Station)", "stars": 4,
         "price_per_night": 185, "tags": ["central", "great transit access", "ryokan-style"]},
        {"name": "Shibuya Stream Excel Hotel Tokyu", "area": "Shibuya", "stars": 4,
         "price_per_night": 160, "tags": ["nightlife", "food scene", "vibrant"]},
        {"name": "UNPLAN Kagurazaka (private room)", "area": "Kagurazaka", "stars": 3,
         "price_per_night": 95, "tags": ["budget", "quiet neighborhood", "local feel"]},
    ]
    return [{"city": city, "currency": "EUR", **opt} for opt in base]


class HotelSupplierExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        q = extract_query(context.message)
        result = {
            "nights": int(q.get("nights", 1)),
            "travelers": int(q.get("travelers", 1)),
            "options": _hotel_options(q.get("city", "?")),
        }
        await event_queue.enqueue_event(data_message(result))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        return None


def build_agent_card(url: str) -> AgentCard:
    return AgentCard(
        name="HotelSupplier",
        description="Searches hotels in a city and returns options with nightly price and area.",
        url=url,
        version="1.0.0",
        capabilities=AgentCapabilities(streaming=False, push_notifications=False),
        default_input_modes=["application/json"],
        default_output_modes=["application/json"],
        skills=[
            AgentSkill(
                id="search_hotels",
                name="Search Hotels",
                description=(
                    "Given a city, number of nights and travelers, return hotel options "
                    "(name, area, stars, price per night)."
                ),
                tags=["hotels", "travel", "lodging"],
                examples=["Find hotels in Tokyo for 7 nights for 2 travelers"],
            )
        ],
    )


def build_app(url: str):
    handler = DefaultRequestHandler(
        agent_executor=HotelSupplierExecutor(), task_store=InMemoryTaskStore()
    )
    return A2AStarletteApplication(agent_card=build_agent_card(url), http_handler=handler).build()


def main() -> None:
    import uvicorn

    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8002"))
    url = f"http://{host}:{port}/"
    print(f"HotelSupplier A2A agent listening on {url}")
    uvicorn.run(build_app(url), host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
