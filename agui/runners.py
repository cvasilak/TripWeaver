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

from agui import a2ui
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

    def task_callback(output: Any) -> None:
        mid = _id()
        text = str(getattr(output, "raw", None) or output).strip()
        # The final task's output is the structured TripPlan (JSON, via
        # output_pydantic). Don't dump raw JSON into the chat — the A2UI surface
        # renders it. Researcher tasks output natural language, which we stream.
        if text.startswith(("{", "[")):
            text = "Finalizing your trip plan…"
        emit(TextMessageStartEvent(message_id=mid, role="assistant"))
        emit(TextMessageContentEvent(message_id=mid, delta=text[:4000]))
        emit(TextMessageEndEvent(message_id=mid))

    def run() -> None:
        # Bridge CrewAI's event bus to AG-UI tool-call events, so each tool the
        # agents invoke shows up in the chat as a tool call. scoped_handlers keeps
        # the subscriptions local to this run.
        from crewai.events import crewai_event_bus
        from crewai.events.types.agent_events import (
            AgentExecutionCompletedEvent,
            AgentExecutionStartedEvent,
        )
        from crewai.events.types.tool_usage_events import (
            ToolUsageFinishedEvent,
            ToolUsageStartedEvent,
        )

        tool_calls: dict[str, str] = {}
        agent_calls: dict[str, str] = {}

        def _args_delta(value: Any) -> str:
            return value if isinstance(value, str) else json.dumps(value, default=str)

        try:
            with crewai_event_bus.scoped_handlers():

                @crewai_event_bus.on(ToolUsageStartedEvent)
                def _tool_started(_source: Any, e: Any) -> None:
                    tc = uuid.uuid4().hex
                    tool_calls[e.tool_name] = tc
                    emit(ToolCallStartEvent(tool_call_id=tc, tool_call_name=e.tool_name))
                    emit(ToolCallArgsEvent(tool_call_id=tc, delta=_args_delta(e.tool_args)))

                @crewai_event_bus.on(ToolUsageFinishedEvent)
                def _tool_finished(_source: Any, e: Any) -> None:
                    tc = tool_calls.pop(e.tool_name, None) or uuid.uuid4().hex
                    emit(ToolCallEndEvent(tool_call_id=tc))
                    emit(ToolCallResultEvent(message_id=uuid.uuid4().hex, tool_call_id=tc,
                                             content=str(getattr(e, "output", ""))[:600], role="tool"))

                @crewai_event_bus.on(AgentExecutionStartedEvent)
                def _agent_started(_source: Any, e: Any) -> None:
                    # A render-only "agent_step" tool call: it stays in-progress
                    # (spinner) until the agent finishes; the frontend renders it as
                    # "Starting <agent>…".
                    tc = uuid.uuid4().hex
                    agent_calls[e.agent_id] = tc
                    emit(ToolCallStartEvent(tool_call_id=tc, tool_call_name="agent_step"))
                    emit(ToolCallArgsEvent(tool_call_id=tc, delta=json.dumps({"agent": e.agent_role})))

                @crewai_event_bus.on(AgentExecutionCompletedEvent)
                def _agent_completed(_source: Any, e: Any) -> None:
                    tc = agent_calls.pop(e.agent_id, None) or uuid.uuid4().hex
                    emit(ToolCallEndEvent(tool_call_id=tc))
                    emit(ToolCallResultEvent(message_id=uuid.uuid4().hex, tool_call_id=tc,
                                             content="{}", role="tool"))

                crew = build_crew(task_callback=task_callback)
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
            # Render the crew's structured TripPlan as an A2UI surface (cards),
            # then keep the raw plan in shared state for non-A2UI consumers.
            for ev in a2ui.emit_surface(a2ui.trip_plan_surface(snapshot)):
                yield ev
            yield StateSnapshotEvent(snapshot={"plan": snapshot})
            yield RunFinishedEvent(thread_id=tid, run_id=rid, result=snapshot)
            return
        yield item


# --------------------------------------------------------------------------- #
# a2ui runner — no LLM; real A2A calls; renders results as A2UI surfaces over
# AG-UI, with a human-in-the-loop "Confirm & book" gate.
# --------------------------------------------------------------------------- #
async def a2ui_runner(agent_input: RunAgentInput) -> AsyncIterator[BaseEvent]:
    tid, rid = agent_input.thread_id, agent_input.run_id
    req = _trip_request(agent_input)
    fp = getattr(agent_input, "forwarded_props", None) or {}
    action = fp.get("action") if isinstance(fp, dict) else None
    nights = max(1, int(req["days"]) - 1)

    yield RunStartedEvent(thread_id=tid, run_id=rid)

    # --- HITL second leg: the user clicked "Confirm & book" on the plan surface ---
    if action == "book":
        async for ev in _stream_text("Confirming your booking with the suppliers…"):
            yield ev
        code = "TWX-" + uuid.uuid4().hex[:6].upper()
        for ev in a2ui.emit_surface(a2ui.booking_confirmation_surface(fp, code)):
            yield ev
        yield RunFinishedEvent(thread_id=tid, run_id=rid, result={"booked": True, "code": code})
        return

    # --- first leg (or a "choose_flight" re-render): research + render the plan ---
    async for ev in _stream_text(f"Planning your trip to {req['destination']} and rendering it as A2UI…"):
        yield ev

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
    yield StepFinishedEvent(step_name="research_flights")

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
    yield StepFinishedEvent(step_name="research_hotels")

    # The user may have picked a flight (choose_flight action); else default to cheapest.
    chosen_airline = fp.get("airline") if isinstance(fp, dict) else None
    if not chosen_airline:
        chosen_airline = min(flights["options"], key=lambda o: o["price_per_person"])["airline"]
    chosen = next(f for f in flights["options"] if f["airline"] == chosen_airline)
    hotel = {**hotels["options"][0], "nights": nights}
    total = chosen["price_per_person"] * int(req["travelers"]) + hotel["price_per_night"] * nights

    for ev in a2ui.emit_surface(a2ui.plan_surface(req, flights["options"], hotel, chosen_airline, total)):
        yield ev
    yield RunFinishedEvent(thread_id=tid, run_id=rid, result={"surface": a2ui.PLAN_SURFACE})


RUNNERS = {"demo": demo_runner, "crew": crew_runner, "a2ui": a2ui_runner}
