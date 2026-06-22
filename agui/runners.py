"""Runners: async generators that produce the AG-UI event stream for one run.

An AG-UI run is just a sequence of typed events. A *runner* yields those events;
the server encodes them as SSE. Keeping this as a plain async generator is what
makes the protocol legible — you can read the run top to bottom.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, AsyncIterator

from ag_ui.core import (
    BaseEvent,
    RunAgentInput,
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    StateDeltaEvent,
    StateSnapshotEvent,
    StepFinishedEvent,
    StepStartedEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    ToolCallStartEvent,
)

from backend.a2a_client import aquery_supplier
from backend.main import SAMPLE_REQUEST
from backend.tools import FLIGHT_SUPPLIER_URL, HOTEL_SUPPLIER_URL


def _id() -> str:
    return uuid.uuid4().hex


def _trip_request(agent_input: RunAgentInput) -> dict[str, Any]:
    """Resolve the trip request: defaults from SAMPLE_REQUEST, overridable by the
    frontend via RunAgentInput.forwarded_props."""
    req = dict(SAMPLE_REQUEST)
    fp = getattr(agent_input, "forwarded_props", None)
    if isinstance(fp, dict):
        req.update({k: v for k, v in fp.items() if k in SAMPLE_REQUEST})
    return req


async def _stream_text(text: str, role: str = "assistant", chunk: int = 24) -> AsyncIterator[BaseEvent]:
    """Emit one assistant message as TEXT_MESSAGE_START / ...CONTENT* / ...END,
    chunked to mimic token streaming."""
    mid = _id()
    yield TextMessageStartEvent(message_id=mid, role=role)
    for i in range(0, len(text), chunk):
        yield TextMessageContentEvent(message_id=mid, delta=text[i : i + chunk])
        await asyncio.sleep(0.03)
    yield TextMessageEndEvent(message_id=mid)


async def _tool_call(name: str, params: dict, base_url: str) -> tuple[list[BaseEvent], dict]:
    """Run one A2A supplier call, returning (events, result_data).

    Emits the full TOOL_CALL_START -> ARGS -> END -> RESULT sequence and makes a
    *real* A2A call to the Phase 2 supplier — no LLM involved.
    """
    tc = _id()
    events: list[BaseEvent] = [
        ToolCallStartEvent(tool_call_id=tc, tool_call_name=name),
        ToolCallArgsEvent(tool_call_id=tc, delta=json.dumps(params)),
    ]
    data = await aquery_supplier(base_url, params)
    events.append(ToolCallEndEvent(tool_call_id=tc))
    events.append(
        ToolCallResultEvent(message_id=_id(), tool_call_id=tc, content=json.dumps(data), role="tool")
    )
    return events, data


# --------------------------------------------------------------------------- #
# demo runner — no LLM, exercises the real A2A suppliers (Phases 2+3 together)
# --------------------------------------------------------------------------- #
async def demo_runner(agent_input: RunAgentInput) -> AsyncIterator[BaseEvent]:
    tid, rid = agent_input.thread_id, agent_input.run_id
    req = _trip_request(agent_input)
    nights = max(1, int(req["days"]) - 1)

    yield RunStartedEvent(thread_id=tid, run_id=rid)

    # Shared state the frontend mirrors — start empty, fill as we go.
    yield StateSnapshotEvent(snapshot={"request": req, "flights": None, "hotels": None, "plan": None})

    async for ev in _stream_text(
        f"Planning your {req['days']}-day trip to {req['destination']} for "
        f"{req['travelers']} traveler(s) from {req['origin']}. Contacting suppliers over A2A…"
    ):
        yield ev

    # --- Flights (real A2A call) ---
    yield StepStartedEvent(step_name="research_flights")
    try:
        events, flights = await _tool_call(
            "search_flights",
            {"origin": req["origin"], "destination": req["destination"],
             "depart_date": req["start_date"], "travelers": req["travelers"]},
            FLIGHT_SUPPLIER_URL,
        )
    except Exception as e:
        yield RunErrorEvent(message=f"FlightSupplier unavailable: {e}")
        return
    for ev in events:
        yield ev
    yield StateDeltaEvent(delta=[{"op": "replace", "path": "/flights", "value": flights["options"]}])
    yield StepFinishedEvent(step_name="research_flights")

    # --- Hotels (real A2A call) ---
    yield StepStartedEvent(step_name="research_hotels")
    try:
        events, hotels = await _tool_call(
            "search_hotels",
            {"city": req["destination"], "nights": nights, "travelers": req["travelers"]},
            HOTEL_SUPPLIER_URL,
        )
    except Exception as e:
        yield RunErrorEvent(message=f"HotelSupplier unavailable: {e}")
        return
    for ev in events:
        yield ev
    yield StateDeltaEvent(delta=[{"op": "replace", "path": "/hotels", "value": hotels["options"]}])
    yield StepFinishedEvent(step_name="research_hotels")

    # --- Compose a small plan from the supplier data (no LLM) ---
    flight = min(flights["options"], key=lambda o: o["price_per_person"])
    hotel = hotels["options"][0]
    plan = {
        "selected_flight": flight,
        "selected_hotel": {**hotel, "nights": nights},
        "estimated_total": flight["price_per_person"] * int(req["travelers"])
        + hotel["price_per_night"] * nights,
        "currency": req["currency"],
        "note": "Demo plan (no LLM). Run ?mode=crew for the full day-by-day itinerary.",
    }
    async for ev in _stream_text(
        f"Picked {flight['airline']} ({flight['price_per_person']} {req['currency']}/pp) and "
        f"{hotel['name']} in {hotel['area']}. Estimated total "
        f"{plan['estimated_total']} {req['currency']} for the party."
    ):
        yield ev

    yield StateSnapshotEvent(
        snapshot={"request": req, "flights": flights["options"], "hotels": hotels["options"], "plan": plan}
    )
    yield RunFinishedEvent(thread_id=tid, run_id=rid, result=plan)


# --------------------------------------------------------------------------- #
# crew runner — the real CrewAI crew (needs ANTHROPIC_API_KEY + credits)
# --------------------------------------------------------------------------- #
async def crew_runner(agent_input: RunAgentInput) -> AsyncIterator[BaseEvent]:
    from backend.crew import build_crew  # heavy import; only when this mode is used

    tid, rid = agent_input.thread_id, agent_input.run_id
    req = _trip_request(agent_input)

    yield RunStartedEvent(thread_id=tid, run_id=rid)
    async for ev in _stream_text(f"Starting the crew to plan your trip to {req['destination']}…"):
        yield ev

    # The crew runs synchronously in a worker thread; its callbacks push AG-UI
    # events onto this queue, which we drain and yield as they arrive.
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def emit(event: BaseEvent) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, event)

    step_seq = 0

    def task_callback(output: Any) -> None:
        mid = _id()
        text = str(getattr(output, "raw", None) or output)[:4000]
        emit(TextMessageStartEvent(message_id=mid, role="assistant"))
        emit(TextMessageContentEvent(message_id=mid, delta=text))
        emit(TextMessageEndEvent(message_id=mid))

    def step_callback(step: Any) -> None:
        # AG-UI requires STEP_STARTED to be matched by STEP_FINISHED and never
        # re-started while still active. CrewAI fires this per step with repeating
        # labels (AgentAction/AgentFinish), so emit a unique, self-contained pair
        # — otherwise two STEP_STARTED "AgentFinish" collide ("already active").
        nonlocal step_seq
        step_seq += 1
        label = getattr(step, "tool", None) or type(step).__name__
        name = f"{str(label)[:48]} #{step_seq}"
        emit(StepStartedEvent(step_name=name))
        emit(StepFinishedEvent(step_name=name))

    def run() -> None:
        try:
            crew = build_crew(step_callback=step_callback, task_callback=task_callback)
            result = crew.kickoff(inputs=req)
            loop.call_soon_threadsafe(queue.put_nowait, ("__done__", result))
        except Exception as e:  # noqa: BLE001 - surfaced to the client as RUN_ERROR
            loop.call_soon_threadsafe(queue.put_nowait, ("__error__", e))

    loop.run_in_executor(None, run)

    while True:
        item = await queue.get()
        if isinstance(item, tuple) and item and item[0] in ("__done__", "__error__"):
            kind, payload = item
            if kind == "__error__":
                yield RunErrorEvent(message=str(payload))
                return
            plan = getattr(payload, "pydantic", None)
            snapshot = plan.model_dump() if plan is not None else {"raw": str(getattr(payload, "raw", payload))}
            yield StateSnapshotEvent(snapshot={"plan": snapshot})
            yield RunFinishedEvent(thread_id=tid, run_id=rid, result=snapshot)
            return
        yield item


RUNNERS = {"demo": demo_runner, "crew": crew_runner}
