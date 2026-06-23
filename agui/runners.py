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
# crew runner — the real CrewAI crew (needs ANTHROPIC_API_KEY + credits),
# with human-in-the-loop "pick your flight & hotel" and "confirm booking" gates.
#
# The flow spans three runs (AG-UI is one-directional SSE):
#   Run 1 (no pick yet): run the research crew -> emit a `select_options` tool
#       call carrying the ranked flight/hotel options, then finish the run.
#       CopilotKit's renderAndWaitForResponse renders the picker and waits.
#   Run 2 (pick present): the traveler's choice arrives as a tool-result message;
#       run the planning crew *around* that choice, render the TripPlan, then emit
#       a `confirm_booking` tool call and finish — CopilotKit waits again.
#   Run 3 (confirmation present): run the booking crew to place the reservations
#       and render the booking-confirmation surface.
# Phases are checked in reverse order (confirmation -> pick -> fresh) because each
# later run's messages still contain the earlier gates' results.
# --------------------------------------------------------------------------- #
SELECT_OPTIONS_TOOL = "select_options"
CONFIRM_BOOKING_TOOL = "confirm_booking"


def _parse_pick(content: Any) -> dict | None:
    """Parse a tool-result payload into ``{'flight': {...}, 'hotel': {...}}`` or
    return None if it isn't a flight+hotel selection."""
    try:
        data = json.loads(content) if isinstance(content, str) else content
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    flight, hotel = data.get("flight"), data.get("hotel")
    if isinstance(flight, dict) and isinstance(hotel, dict):
        return {"flight": flight, "hotel": hotel}
    return None


def _read_selection(agent_input: RunAgentInput) -> dict | None:
    """If this run continues after the traveler picked options, return the pick.

    CopilotKit's ``renderAndWaitForResponse`` delivers the pick as a tool-result
    message (role ``"tool"``) answering our ``select_options`` tool call. We scan
    the incoming messages newest-first and parse the first flight+hotel payload —
    preferring one that answers our own tool call, but tolerant of the exact id
    plumbing so a stray-but-valid pick still works.
    """
    messages = list(getattr(agent_input, "messages", None) or [])

    select_ids: set[str] = set()
    for m in messages:
        for tcobj in getattr(m, "tool_calls", None) or []:
            fn = getattr(tcobj, "function", None)
            name = getattr(fn, "name", None) if fn is not None else None
            cid = getattr(tcobj, "id", None)
            if name == SELECT_OPTIONS_TOOL and cid:
                select_ids.add(cid)

    for m in reversed(messages):
        if getattr(m, "role", None) != "tool":
            continue
        payload = _parse_pick(getattr(m, "content", None))
        if payload is None:
            continue
        if select_ids and getattr(m, "tool_call_id", None) not in select_ids:
            continue
        return payload
    return None


def _parse_confirmation(content: Any) -> dict | None:
    """Parse a tool-result payload into a booking confirmation (``{'confirmed': ...,
    'booking': {...}}``) or None if it isn't one."""
    try:
        data = json.loads(content) if isinstance(content, str) else content
    except (ValueError, TypeError):
        return None
    if isinstance(data, dict) and "confirmed" in data:
        return data
    return None


def _read_confirmation(agent_input: RunAgentInput) -> dict | None:
    """Return the booking confirmation if the traveler has *just* answered the
    confirm-booking gate (and we haven't booked yet); else None.

    Guard against re-booking: if any assistant turn follows the confirmation
    tool-result, Run 3 already handled it, so later chatter won't book again.
    """
    messages = list(getattr(agent_input, "messages", None) or [])

    confirm_ids: set[str] = set()
    for m in messages:
        for tcobj in getattr(m, "tool_calls", None) or []:
            fn = getattr(tcobj, "function", None)
            name = getattr(fn, "name", None) if fn is not None else None
            cid = getattr(tcobj, "id", None)
            if name == CONFIRM_BOOKING_TOOL and cid:
                confirm_ids.add(cid)

    for idx in range(len(messages) - 1, -1, -1):
        m = messages[idx]
        if getattr(m, "role", None) != "tool":
            continue
        payload = _parse_confirmation(getattr(m, "content", None))
        if payload is None:
            continue
        if confirm_ids and getattr(m, "tool_call_id", None) not in confirm_ids:
            continue
        # Only the most recent confirmation matters; act on it only if no assistant
        # turn comes after it (i.e. we haven't already booked).
        already_handled = any(
            getattr(messages[j], "role", None) == "assistant" for j in range(idx + 1, len(messages))
        )
        return None if already_handled else payload
    return None


def _extract_options(task_output: Any) -> list[dict]:
    """Pull the list of options out of a research TaskOutput (structured first,
    raw-JSON fallback)."""
    pyd = getattr(task_output, "pydantic", None)
    if pyd is not None and hasattr(pyd, "options"):
        return [o.model_dump() for o in pyd.options]
    raw = getattr(task_output, "raw", None) or ""
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return []
    opts = data.get("options") if isinstance(data, dict) else data
    return opts if isinstance(opts, list) else []


async def _run_crew(
    build_fn: Any,
    inputs: dict[str, Any],
    *,
    stream_tasks: bool = True,
    finalize_text: str = "Finalizing your trip plan…",
) -> AsyncIterator[Any]:
    """Run a crew in a worker thread, yielding AG-UI events as the agents work.

    Each tool the agents invoke surfaces as a tool call; each agent start surfaces
    as an in-progress ``agent_step`` (spinner). The final item yielded is the
    sentinel tuple ``("__done__", CrewOutput)`` or ``("__error__", exc)`` — the
    caller handles it.
    """
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def emit(event: BaseEvent) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, event)

    def task_callback(output: Any) -> None:
        mid = _id()
        text = str(getattr(output, "raw", None) or output).strip()
        # Structured task outputs (JSON via output_pydantic) are rendered as UI,
        # not dumped into the chat; natural-language task outputs are streamed.
        if text.startswith(("{", "[")):
            text = finalize_text
        emit(TextMessageStartEvent(message_id=mid, role="assistant"))
        emit(TextMessageContentEvent(message_id=mid, delta=text[:4000]))
        emit(TextMessageEndEvent(message_id=mid))

    def run() -> None:
        # Bridge CrewAI's event bus to AG-UI tool-call events. scoped_handlers
        # keeps the subscriptions local to this run.
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
        agent_stack: list[str] = []  # tool_call ids for in-flight agents (LIFO; crew is sequential)

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
                    # "Starting <agent role>…". Read the role off the agent object —
                    # event.agent_role isn't reliably populated.
                    role = getattr(getattr(e, "agent", None), "role", None) or e.agent_role or "agent"
                    tc = uuid.uuid4().hex
                    agent_stack.append(tc)
                    emit(ToolCallStartEvent(tool_call_id=tc, tool_call_name="agent_step"))
                    emit(ToolCallArgsEvent(tool_call_id=tc, delta=json.dumps({"agent": role})))

                @crewai_event_bus.on(AgentExecutionCompletedEvent)
                def _agent_completed(_source: Any, e: Any) -> None:
                    tc = agent_stack.pop() if agent_stack else uuid.uuid4().hex
                    emit(ToolCallEndEvent(tool_call_id=tc))
                    emit(ToolCallResultEvent(message_id=uuid.uuid4().hex, tool_call_id=tc,
                                             content="{}", role="tool"))

                crew = build_fn(task_callback=task_callback if stream_tasks else None)
                result = crew.kickoff(inputs=inputs)
            loop.call_soon_threadsafe(queue.put_nowait, ("__done__", result))
        except Exception as e:  # noqa: BLE001 - surfaced to the client as RUN_ERROR
            loop.call_soon_threadsafe(queue.put_nowait, ("__error__", e))

    loop.run_in_executor(None, run)

    while True:
        item = await queue.get()
        if isinstance(item, tuple) and item and item[0] in ("__done__", "__error__"):
            yield item
            return
        yield item


async def crew_runner(agent_input: RunAgentInput) -> AsyncIterator[BaseEvent]:
    from backend.crew import (  # heavy import
        build_booking_crew,
        build_planning_crew,
        build_research_crew,
    )

    tid, rid = agent_input.thread_id, agent_input.run_id
    req = _trip_request(agent_input)
    confirmation = _read_confirmation(agent_input)
    pick = _read_selection(agent_input)

    yield RunStartedEvent(thread_id=tid, run_id=rid)

    # ---- Run 3: the traveler confirmed; place the reservations -------------
    if confirmation is not None:
        if not confirmation.get("confirmed"):
            async for ev in _stream_text(
                "No problem — I haven't booked anything. Tell me what you'd like to change."
            ):
                yield ev
            yield RunFinishedEvent(thread_id=tid, run_id=rid, result={"booked": False})
            return

        booking = confirmation.get("booking") or {}
        flight = booking.get("flight") or {}
        hotel = booking.get("hotel") or {}
        currency = booking.get("currency") or req.get("currency", "EUR")
        total = booking.get("total")

        async for ev in _stream_text(
            f"Confirming your trip — placing the flight and hotel reservations…"
        ):
            yield ev

        inputs = {
            "chosen_flight": json.dumps(flight, default=str),
            "chosen_hotel": json.dumps(hotel, default=str),
            "total": total if total is not None else "",
            "currency": currency,
        }
        result = None
        async for item in _run_crew(build_booking_crew, inputs,
                                    finalize_text="Confirming your booking…"):
            if isinstance(item, tuple):
                kind, payload = item
                if kind == "__error__":
                    yield RunErrorEvent(message=str(payload))
                    return
                result = payload
            else:
                yield item

        conf = getattr(result, "pydantic", None)
        code = (getattr(conf, "code", None) if conf else None) or ("TWX-" + uuid.uuid4().hex[:6].upper())
        message = getattr(conf, "message", "") if conf else ""
        ctx = {
            "airline": flight.get("airline", "?"),
            "hotel": hotel.get("name", "?"),
            "total": total if total is not None else "?",
            "currency": currency,
        }
        for ev in a2ui.emit_surface(a2ui.booking_confirmation_surface(ctx, code, message=message)):
            yield ev
        yield StateSnapshotEvent(snapshot={"booking": conf.model_dump() if conf else {"code": code}})
        yield RunFinishedEvent(thread_id=tid, run_id=rid, result={"booked": True, "code": code})
        return

    # ---- Run 2: the traveler has picked; plan around their choice ----------
    if pick is not None:
        flight, hotel = pick["flight"], pick["hotel"]
        async for ev in _stream_text(
            f"Great choice — building your itinerary around "
            f"{flight.get('airline', 'your flight')} and {hotel.get('name', 'your hotel')}…"
        ):
            yield ev

        inputs = {
            **req,
            "chosen_flight": json.dumps(flight, default=str),
            "chosen_hotel": json.dumps(hotel, default=str),
        }
        result = None
        async for item in _run_crew(build_planning_crew, inputs,
                                    finalize_text="Finalizing your trip plan…"):
            if isinstance(item, tuple):
                kind, payload = item
                if kind == "__error__":
                    yield RunErrorEvent(message=str(payload))
                    return
                result = payload
            else:
                yield item

        plan = getattr(result, "pydantic", None)
        snapshot = plan.model_dump() if plan is not None else {"raw": str(getattr(result, "raw", result))}
        for ev in a2ui.emit_surface(a2ui.trip_plan_surface(snapshot)):
            yield ev
        yield StateSnapshotEvent(snapshot={"plan": snapshot})

        # If we have a structured plan, offer the booking gate: a `confirm_booking`
        # tool call with NO result (renderAndWaitForResponse) carrying the booking
        # summary. The confirmation comes back on the next run (_read_confirmation).
        if "itinerary" in snapshot:
            booking_ctx = {
                "flight": snapshot.get("selected_flight") or {},
                "hotel": snapshot.get("selected_hotel") or {},
                "total": snapshot.get("estimated_total"),
                "currency": snapshot.get("currency", req.get("currency", "EUR")),
            }
            tc = _id()
            yield ToolCallStartEvent(tool_call_id=tc, tool_call_name=CONFIRM_BOOKING_TOOL)
            yield ToolCallArgsEvent(tool_call_id=tc, delta=json.dumps(booking_ctx, default=str))
            yield ToolCallEndEvent(tool_call_id=tc)
            yield RunFinishedEvent(thread_id=tid, run_id=rid, result={"awaiting": CONFIRM_BOOKING_TOOL})
            return

        yield RunFinishedEvent(thread_id=tid, run_id=rid, result=snapshot)
        return

    # ---- Run 1: research options and hand them to the traveler to pick -----
    async for ev in _stream_text(
        f"Researching flights and hotels for your trip to {req['destination']}…"
    ):
        yield ev

    result = None
    async for item in _run_crew(build_research_crew, req, stream_tasks=False):
        if isinstance(item, tuple):
            kind, payload = item
            if kind == "__error__":
                yield RunErrorEvent(message=str(payload))
                return
            result = payload
        else:
            yield item

    tasks_output = list(getattr(result, "tasks_output", None) or [])
    flights = _extract_options(tasks_output[0]) if len(tasks_output) > 0 else []
    hotels = _extract_options(tasks_output[1]) if len(tasks_output) > 1 else []

    # Hand the options to the traveler as a `select_options` tool call with NO
    # result — CopilotKit's renderAndWaitForResponse renders the picker and waits
    # for respond(). The pick comes back on the next run (see _read_selection).
    tc = _id()
    yield ToolCallStartEvent(tool_call_id=tc, tool_call_name=SELECT_OPTIONS_TOOL)
    yield ToolCallArgsEvent(
        tool_call_id=tc,
        delta=json.dumps({"flights": flights, "hotels": hotels, "request": req}, default=str),
    )
    yield ToolCallEndEvent(tool_call_id=tc)
    yield StateSnapshotEvent(snapshot={"request": req, "flights": flights, "hotels": hotels, "plan": None})
    yield RunFinishedEvent(thread_id=tid, run_id=rid, result={"awaiting": SELECT_OPTIONS_TOOL})


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
