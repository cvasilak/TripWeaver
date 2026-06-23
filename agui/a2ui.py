"""A2UI v0.9 surface builders for TripWeaver (Phase 4).

The agent doesn't emit HTML or JSX — it emits **declarative A2UI messages** (data,
not code) that a client renders with its own trusted component catalog. We build
spec-compliant v0.9 messages (``createSurface`` / ``updateComponents`` /
``updateDataModel``), **validate each one against CrewAI's bundled A2UI v0.9
validator**, and ship them over the Phase 3 AG-UI stream as ``CustomEvent``s.

Component model (v0.9 "basic catalog", flat form):
    {"id": "...", "component": "Text", "text": "..."}            # leaf
    {"id": "...", "component": "Card", "child": "<id>"}          # single child by id
    {"id": "...", "component": "Column", "children": ["<id>"]}   # children by id
    {"id": "...", "component": "Button", "child": "<id>",
     "action": {"event": {"name": "book", "context": {...}}}}    # round-trips to the agent
One component must have id "root". Values can be literals or {"path": "/ptr"}
bindings into the surface data model.
"""

from __future__ import annotations

import contextvars
import json
import os
import uuid
from typing import Any

from ag_ui.core import (
    BaseEvent,
    CustomEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    ToolCallStartEvent,
)
from crewai.a2a.extensions.a2ui.validator import validate_a2ui_message_v09

A2UI_CATALOG_ID = "https://a2ui.org/specification/v0_9/basic_catalog.json"
A2UI_EVENT_NAME = "a2ui"

# How A2UI reaches the frontend. Two consumers, two carriers:
#   "custom" — AG-UI CUSTOM events (name "a2ui"); read by our bundled vanilla
#              renderer (agui/static/index.html and the copilotkit branch).
#   "tool"   — a "render_a2ui" tool call; what CopilotKit's native A2UI middleware
#              (@ag-ui/a2ui-middleware) consumes to render surfaces in <CopilotChat>.
# Set TRIPWEAVER_A2UI_CARRIER=tool when serving the full CopilotKit app.
A2UI_RENDER_TOOL = "render_a2ui"


# --- message envelopes (validated) ---------------------------------------- #
def event(message: dict[str, Any]) -> CustomEvent:
    """Validate an A2UI v0.9 message against the spec, then wrap it for AG-UI.

    Raises ``A2UIValidationError`` if the message isn't spec-compliant — so a
    malformed surface fails here, not silently in the browser.
    """
    validate_a2ui_message_v09(message)
    return CustomEvent(name=A2UI_EVENT_NAME, value=message)


def create_surface(surface_id: str) -> dict[str, Any]:
    return {"version": "v0.9", "createSurface": {
        "surfaceId": surface_id, "catalogId": A2UI_CATALOG_ID,
        "theme": {"primaryColor": "#5db0ff", "agentDisplayName": "TripWeaver"}}}


def update_components(surface_id: str, components: list[dict]) -> dict[str, Any]:
    return {"version": "v0.9", "updateComponents": {"surfaceId": surface_id, "components": components}}


def update_data(surface_id: str, path: str, value: Any) -> dict[str, Any]:
    return {"version": "v0.9", "updateDataModel": {"surfaceId": surface_id, "path": path, "value": value}}


# --- carrier: CUSTOM events vs a render_a2ui tool call --------------------- #
# Per-request carrier override (set by the server from the ?a2ui= query param),
# falling back to the env var, then "custom". A contextvar so concurrent requests
# don't clobber each other.
_carrier_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("a2ui_carrier", default=None)


def set_carrier(value: str | None) -> None:
    """Set the A2UI carrier for the current request context ("tool" | "custom")."""
    _carrier_var.set(value or None)


def emit_surface(messages: list[CustomEvent]) -> list[BaseEvent]:
    """Turn a surface (list of validated CUSTOM-event A2UI messages) into the
    AG-UI events to actually emit, per the active carrier. The surface builders
    always produce CUSTOM events; this adapts them to a render_a2ui tool call for
    CopilotKit. Carrier resolution: per-request override -> env -> "custom"."""
    carrier = _carrier_var.get() or os.getenv("TRIPWEAVER_A2UI_CARRIER", "custom")
    if carrier.lower() == "tool":
        return _to_render_tool(messages)
    return list(messages)


def _ptr_set(obj: dict, pointer: str, value: Any) -> None:
    if not pointer or pointer == "/":
        return
    parts = pointer.split("/")[1:]
    node = obj
    for p in parts[:-1]:
        node = node.setdefault(p, {})
    node[parts[-1]] = value


def _to_render_tool(messages: list[CustomEvent]) -> list[BaseEvent]:
    """Repackage createSurface/updateComponents/updateDataModel messages as a
    single ``render_a2ui`` tool call (surfaceId + flat components + initial data)
    — the shape CopilotKit's A2UI middleware renders."""
    surface_id: str | None = None
    components: list[dict] = []
    data: dict[str, Any] = {}
    for ev in messages:
        v = ev.value
        if "createSurface" in v:
            surface_id = v["createSurface"]["surfaceId"]
        elif "updateComponents" in v:
            surface_id = surface_id or v["updateComponents"]["surfaceId"]
            components = v["updateComponents"]["components"]
        elif "updateDataModel" in v:
            _ptr_set(data, v["updateDataModel"].get("path", "/"), v["updateDataModel"].get("value"))
    args: dict[str, Any] = {"surfaceId": surface_id, "components": components}
    if data:
        args["data"] = data
    tc = uuid.uuid4().hex
    # The middleware renders the surface when it sees the tool-call RESULT (it
    # then emits an ACTIVITY_SNAPSHOT the renderer consumes); without the result
    # the args are buffered but never rendered.
    return [
        ToolCallStartEvent(tool_call_id=tc, tool_call_name=A2UI_RENDER_TOOL),
        ToolCallArgsEvent(tool_call_id=tc, delta=json.dumps(args)),
        ToolCallEndEvent(tool_call_id=tc),
        ToolCallResultEvent(message_id=uuid.uuid4().hex, tool_call_id=tc, content="{}", role="tool"),
    ]


# --- component helpers ----------------------------------------------------- #
def text(cid: str, value: Any, hint: str | None = None) -> dict:
    c = {"id": cid, "component": "Text", "text": value}
    if hint:
        c["usageHint"] = hint
    return c


def card(cid: str, child: str) -> dict:
    return {"id": cid, "component": "Card", "child": child}


def column(cid: str, children: list[str], **kw) -> dict:
    return {"id": cid, "component": "Column", "children": children, **kw}


def row(cid: str, children: list[str], **kw) -> dict:
    return {"id": cid, "component": "Row", "children": children, **kw}


def divider(cid: str) -> dict:
    return {"id": cid, "component": "Divider"}


def button(cid: str, label_id: str, action: str, context: dict | None = None, primary: bool = False) -> dict:
    c = {"id": cid, "component": "Button", "child": label_id,
         "action": {"event": {"name": action, "context": context or {}}}}
    if primary:
        c["primary"] = True
    return c


# --- high-level surfaces --------------------------------------------------- #
PLAN_SURFACE = "trip-plan"
BOOKING_SURFACE = "booking"


def plan_surface(req: dict, flights: list[dict], hotel: dict, chosen_airline: str, total: float) -> list[CustomEvent]:
    """The main interactive surface: flight cards (each with a Choose button), the
    hotel, a short itinerary, and a primary 'Confirm & book' gate (HITL)."""
    comps: list[dict] = []
    root_children: list[str] = []

    def add(c: dict) -> str:
        comps.append(c)
        return c["id"]

    add(text("hdr", f"Your {req['days']}-day trip to {req['destination']}", "h2"))
    root_children.append("hdr")
    add(text("fhdr", "Flights — pick one", "h3"))
    root_children.append("fhdr")

    for i, f in enumerate(flights):
        chosen = f["airline"] == chosen_airline
        title = f"{'✓ ' if chosen else ''}{f['airline']}"
        meta = f"{f['stops']} stop(s) · {f['duration_hours']}h · {f['price_per_person']} {req['currency']}/pp"
        add(text(f"f{i}t", title, "body"))
        add(text(f"f{i}m", meta, "caption"))
        add(text(f"f{i}bl", "Chosen" if chosen else "Choose"))
        add(button(f"f{i}b", f"f{i}bl", "choose_flight", {"airline": f["airline"]}, primary=chosen))
        add(column(f"f{i}c", [f"f{i}t", f"f{i}m", f"f{i}b"]))
        add(card(f"f{i}", f"f{i}c"))
        root_children.append(f"f{i}")

    add(text("hhdr", "Hotel", "h3"))
    root_children.append("hhdr")
    add(text("h0t", hotel["name"], "body"))
    add(text("h0m", f"{hotel['area']} · {hotel['price_per_night']} {req['currency']}/night × {hotel['nights']} nights"))
    add(column("h0c", ["h0t", "h0m"]))
    add(card("h0", "h0c"))
    root_children.append("h0")

    add(text("ihdr", "Itinerary", "h3"))
    root_children.append("ihdr")
    for d, line in enumerate(_itinerary_lines(req), start=1):
        add(text(f"d{d}", f"Day {d}: {line}", "caption"))
        root_children.append(f"d{d}")

    add(divider("div"))
    root_children.append("div")
    # Total is data-bound: its value arrives via updateDataModel (demonstrates binding).
    add(text("total", {"path": "/totals/estimated"}, "body"))
    root_children.append("total")

    add(text("bookbl", "Confirm & book"))
    add(button("book", "bookbl", "book",
               {"airline": chosen_airline, "hotel": hotel["name"], "total": total, "currency": req["currency"]},
               primary=True))
    root_children.append("book")

    add(column("root", root_children, distribution="start"))

    return [
        event(create_surface(PLAN_SURFACE)),
        event(update_components(PLAN_SURFACE, comps)),
        event(update_data(PLAN_SURFACE, "/totals/estimated",
                          f"Estimated total: {total} {req['currency']} for the party")),
    ]


def booking_confirmation_surface(context: dict, code: str) -> list[CustomEvent]:
    """Shown after the user clicks 'Confirm & book' — the HITL result surface."""
    cur = context.get("currency", "EUR")
    comps = [
        text("ok", "✅ Booking confirmed", "h2"),
        text("d1", f"Flight: {context.get('airline', '?')}", "body"),
        text("d2", f"Hotel: {context.get('hotel', '?')}", "body"),
        text("d3", f"Total charged: {context.get('total', '?')} {cur}", "body"),
        text("code", f"Confirmation code: {code}", "caption"),
        column("root", ["ok", "d1", "d2", "d3", "code"]),
    ]
    return [event(create_surface(BOOKING_SURFACE)), event(update_components(BOOKING_SURFACE, comps))]


def trip_plan_surface(plan: dict) -> list[CustomEvent]:
    """Render a crew-authored TripPlan (backend.models.TripPlan, as a dict) as an
    A2UI surface: chosen flight, hotel, the full day-by-day itinerary, and a
    budget verdict — plus the same "Confirm & book" HITL gate.

    Falls back to a plain summary if the crew output didn't parse into a TripPlan
    (e.g. ``{"raw": "..."}``), so crew mode always renders *something* valid.
    """
    comps: list[dict] = []
    root: list[str] = []

    def add(c: dict) -> str:
        comps.append(c)
        return c["id"]

    # Fallback: unparsed / non-TripPlan output.
    if "itinerary" not in plan:
        add(text("hdr", "Trip plan", "h2"))
        add(text("body", str(plan.get("summary") or plan.get("raw") or plan)[:2000], "body"))
        add(column("root", ["hdr", "body"]))
        return [event(create_surface(PLAN_SURFACE)), event(update_components(PLAN_SURFACE, comps))]

    cur = plan.get("currency", "EUR")
    add(text("hdr", str(plan.get("summary") or "Your trip"), "h2"))
    root.append("hdr")

    # --- Flight ---
    f = plan.get("selected_flight") or {}
    add(text("fhdr", "Flight", "h3"))
    root.append("fhdr")
    add(text("ft", f"✈ {f.get('airline', '?')} — {f.get('stops', '?')} stop(s), "
                   f"{f.get('duration_hours', '?')}h, {f.get('price_per_person', '?')} {cur}/pp", "body"))
    add(text("fw", str(f.get("why", "")), "caption"))
    add(column("fc", ["ft", "fw"]))
    add(card("fcard", "fc"))
    root.append("fcard")

    # --- Hotel ---
    h = plan.get("selected_hotel") or {}
    add(text("hhdr", "Hotel", "h3"))
    root.append("hhdr")
    add(text("ht", f"\U0001f3e8 {h.get('name', '?')} — {h.get('area', '?')}", "body"))
    add(text("hm", f"{h.get('price_per_night', '?')} {cur}/night × {h.get('nights', '?')} nights", "caption"))
    add(text("hw", str(h.get("why", "")), "caption"))
    add(column("hc", ["ht", "hm", "hw"]))
    add(card("hcard", "hc"))
    root.append("hcard")

    # --- Itinerary (one card per day) ---
    add(text("ihdr", "Itinerary", "h3"))
    root.append("ihdr")
    for idx, day in enumerate(plan.get("itinerary", [])):
        p = f"d{idx}"
        child_ids = [f"{p}t", f"{p}am", f"{p}pm", f"{p}ev", f"{p}c"]
        add(text(f"{p}t", f"Day {day.get('day', idx + 1)}: {day.get('title', '')}", "body"))
        add(text(f"{p}am", f"AM: {day.get('morning', '')}", "caption"))
        add(text(f"{p}pm", f"PM: {day.get('afternoon', '')}", "caption"))
        add(text(f"{p}ev", f"EVE: {day.get('evening', '')}", "caption"))
        add(text(f"{p}c", f"~{day.get('estimated_cost', '?')} {cur}/pp", "caption"))
        add(column(f"{p}col", child_ids))
        add(card(p, f"{p}col"))
        root.append(p)

    # --- Budget verdict ---
    add(divider("div"))
    root.append("div")
    verdict = "✅ Within budget" if plan.get("within_budget") else "⚠ Over budget"
    add(text("btot", f"{verdict} — est. {plan.get('estimated_total', '?')} {cur} "
                     f"vs budget {plan.get('budget', '?')} {cur}", "body"))
    add(text("bnotes", str(plan.get("budget_notes", "")), "caption"))
    root += ["btot", "bnotes"]

    # --- HITL book gate ---
    add(text("bookbl", "Confirm & book"))
    add(button("book", "bookbl", "book",
               {"airline": f.get("airline", ""), "hotel": h.get("name", ""),
                "total": plan.get("estimated_total", ""), "currency": cur}, primary=True))
    root.append("book")

    add(column("root", root, distribution="start"))
    return [event(create_surface(PLAN_SURFACE)), event(update_components(PLAN_SURFACE, comps))]


def _itinerary_lines(req: dict) -> list[str]:
    """A tiny deterministic itinerary (no LLM) — ?mode=crew produces the real one."""
    interests = str(req.get("interests", "")).lower()
    pool = ["Arrival & settle in", "Food market & neighborhood walk", "Day hike + onsen",
            "Museums & local dining", "Coastal trail & temples", "Free day", "Departure"]
    if "food" not in interests:
        pool[1] = "City highlights"
    return pool[: int(req["days"])]
