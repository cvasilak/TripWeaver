# TripWeaver

A conversational trip-planning concierge, built as a hands-on example of four
agent technologies stacked together:

| Tech | Role in TripWeaver | Phase |
|------|--------------------|-------|
| **CrewAI** | The orchestration brain — a crew of role-based agents | 1 ✓ |
| **A2A** | Reaching external supplier agents (flights, hotels) | 2 ✓ |
| **AG-UI** | Streaming the live agent activity to a frontend | 3 ✓ |
| **A2UI** | Declarative, interactive UI rendered from the agent | **4 (this phase)** |

Each phase is added on top of a working baseline, so when something breaks you
know which layer to blame.

---

## Phase 1 — CrewAI orchestration (no UI, mocked suppliers)

A crew of five specialists plans a multi-day trip and returns a structured plan:

```
Flight Researcher ─┐
Hotel Researcher  ─┼─►  Itinerary Designer ─►  Budget Auditor ─►  TripPlan (structured)
Activities Curator ┘
```

- **Flight / Hotel / Activities researchers** each use a mock "supplier" tool
  ([backend/tools.py](backend/tools.py)) that returns realistic canned data — no
  external API needed yet. In Phase 2 these tools become real **A2A** calls; the
  agents won't change, because the tool interface stays the same.
- **Itinerary Designer** weaves the research into a day-by-day plan.
- **Budget Auditor** totals the costs, checks the budget, and emits the final
  [`TripPlan`](backend/models.py) — a Pydantic object, not just prose. That
  structured output is what later phases render as interactive UI.

The process is **sequential** here (the clearest way to see roles, tools, and
context flowing task→task). See [Going further](#going-further) to switch to a
hierarchical, delegating "Concierge" manager.

### Project layout

```
backend/
  config.py   # LLM config — Claude Sonnet 4.5 via CrewAI's native Anthropic provider
  tools.py    # Search Flights/Hotels (A2A calls since Phase 2) + Activities (local mock)
  models.py   # TripPlan Pydantic schema (the structured deliverable)
  crew.py     # agents + tasks + crew assembly
  main.py     # entry point — runs the crew on a sample request
```

### Run it

Requires Python 3.12+ and an Anthropic API key.

```bash
# 1. Install (uv shown; plain `python -m venv` + pip also works)
uv venv --python 3.12
uv pip install -r requirements.txt

# 2. Add your key
cp .env.example .env        # then edit .env and set ANTHROPIC_API_KEY

# 3. Run
uv run python -m backend.main
# (or, with the venv active:  python -m backend.main)
```

You'll see each agent think and call its tool (`verbose=True`), then a formatted
trip plan. Edit `SAMPLE_REQUEST` in [backend/main.py](backend/main.py) to change
the trip (origin, destination, dates, budget, interests).

### Model & cost

Agents default to **Claude Sonnet 4.5** — the latest Sonnet that CrewAI 1.14.7
routes through Anthropic's *native* structured-outputs path, which makes the final
`TripPlan` reliably schema-conforming. A full run makes several LLM calls (one or
more per agent). You can switch model — to something stronger or cheaper — without
touching code (these are also on the native allow-list, so structured output stays
reliable):

```bash
# in .env
TRIPWEAVER_MODEL=anthropic/claude-opus-4-5    # stronger
TRIPWEAVER_MODEL=anthropic/claude-haiku-4-5   # cheaper
```

### What "done" looks like for Phase 1

- The crew runs end-to-end and prints a coherent day-by-day plan.
- The final result is a valid `TripPlan` object (structured, not free text).
- Swapping the model via `TRIPWEAVER_MODEL` works.

---

## Going further (still Phase 1)

- **Hierarchical process:** set `process=Process.hierarchical` on the `Crew`,
  add `manager_llm=get_llm()` (or a dedicated `manager_agent`), and set
  `allow_delegation=True` on a "Concierge" agent. The manager then decides what
  to delegate instead of you fixing the order.
- **Reasoning:** try `LLM(model=..., reasoning_effort="high")` in
  [config.py](backend/config.py) for harder planning.
- **More agents/tools:** add a "Local Transport" or "Weather" agent + tool.

---

## Phase 2 — A2A supplier agents

The flight and hotel tools are no longer canned local data. They're now
**standalone A2A agents** — independent HTTP services that publish an *Agent
Card* and answer A2A messages. The crew discovers and calls them as a generic
A2A client. This is the "agents talking to other vendors' agents" story: the
suppliers could be operated by anyone, in any framework.

```
                 TripWeaver crew (CrewAI)
   Flight Researcher ──┐                       A2A (JSON-RPC over HTTP)
   Hotel Researcher  ──┤  search_flights ──────────────►  FlightSupplier  :8001
   Activities Curator │  search_hotels  ──────────────►  HotelSupplier   :8002
        (local mock) ◄─┘                                  (a2a-sdk servers)
```

Crucially, **the agents and tasks in [crew.py](backend/crew.py) didn't change** —
only the *bodies* of the `search_flights`/`search_hotels` tools, because the
Phase 1 tool interface was kept stable on purpose.

### What got added

```
a2a_suppliers/            # standalone A2A servers (official a2a-sdk, NOT CrewAI)
  flight_supplier.py      #   FlightSupplier: AgentCard + AgentSkill + executor (:8001)
  hotel_supplier.py       #   HotelSupplier  (:8002)
  protocol.py             #   tiny DataPart <-> dict helpers
backend/
  a2a_client.py           # discovers a supplier's Agent Card, sends a query, reads the result
  tools.py                # search_flights/hotels now call a2a_client.query_supplier(...)
```

How one call works: the client fetches `<supplier>/.well-known/agent-card.json`
(discovery), sends a `Message` whose `DataPart` carries the search params, and
reads the `DataPart` out of the response.

### Run it

Start the two supplier agents, then the crew (3 terminals, or background the
suppliers):

```bash
uv run python -m a2a_suppliers.flight_supplier &   # listens on 127.0.0.1:8001
uv run python -m a2a_suppliers.hotel_supplier  &   # listens on 127.0.0.1:8002
uv run python -m backend.main                      # the crew calls them over A2A
```

The crew (and the commands below) discover each supplier from an env var,
defaulting to those local ports. Export them so the commands are copy-pasteable —
or point them at suppliers hosted elsewhere (any host/vendor):

```bash
export TRIPWEAVER_FLIGHT_SUPPLIER_URL=http://127.0.0.1:8001
export TRIPWEAVER_HOTEL_SUPPLIER_URL=http://127.0.0.1:8002
```

Inspect a supplier's Agent Card (pure A2A discovery, no crew needed):

```bash
curl "$TRIPWEAVER_FLIGHT_SUPPLIER_URL/.well-known/agent-card.json"
```

Sample response — this is how one agent advertises *what it can do* to another:

```json
{
    "name": "FlightSupplier",
    "description": "Searches round-trip flights between two cities and returns ranked options.",
    "url": "http://127.0.0.1:8001/",
    "version": "1.0.0",
    "protocolVersion": "0.3.0",
    "preferredTransport": "JSONRPC",
    "capabilities": { "pushNotifications": false, "streaming": false },
    "defaultInputModes": ["application/json"],
    "defaultOutputModes": ["application/json"],
    "skills": [
        {
            "id": "search_flights",
            "name": "Search Flights",
            "description": "Given origin, destination, depart_date and travelers, return flight options (airline, stops, duration, price per person).",
            "tags": ["flights", "travel", "air"],
            "examples": ["Find flights from Athens to Tokyo departing 2026-10-05 for 2 travelers"]
        }
    ]
}
```

### Query a supplier directly (no crew, no LLM)

[backend/a2a_client.py](backend/a2a_client.py) has a small CLI so you can drive
`query_supplier(...)` by hand — handy for understanding the round trip without
running the whole crew. With the FlightSupplier running:

```bash
uv run python -m backend.a2a_client "$TRIPWEAVER_FLIGHT_SUPPLIER_URL" \
    origin=Athens destination=Tokyo depart_date=2026-10-05 travelers=2
```

Sample response (the structured `DataPart` the agent returns):

```json
{
  "travelers": 2,
  "options": [
    { "from": "Athens", "to": "Tokyo", "depart_date": "2026-10-05", "currency": "EUR",
      "airline": "Aegean + ANA (codeshare)", "stops": 1, "duration_hours": 16.5, "price_per_person": 920 },
    { "from": "Athens", "to": "Tokyo", "depart_date": "2026-10-05", "currency": "EUR",
      "airline": "Qatar Airways", "stops": 1, "duration_hours": 18.0, "price_per_person": 845 },
    { "from": "Athens", "to": "Tokyo", "depart_date": "2026-10-05", "currency": "EUR",
      "airline": "Emirates", "stops": 2, "duration_hours": 22.5, "price_per_person": 780 }
  ]
}
```

The HotelSupplier works the same way — `city=Tokyo nights=7 travelers=2` against
`"$TRIPWEAVER_HOTEL_SUPPLIER_URL"`. (A harmless `DeprecationWarning` about
`A2AClient` may print to stderr; the result on stdout is unaffected — it's the
a2a-sdk 1.x `ClientFactory` migration notice.)

### Testing without an API key

The whole A2A layer (discovery, client calls, the rewired tools, graceful
handling when a supplier is down) is exercisable **without any LLM** — start the
suppliers and call `backend.a2a_client.query_supplier` / the tools directly. Only
the *full crew run* (`backend.main`) needs `ANTHROPIC_API_KEY`.

### Why `a2a-sdk<1.0`

a2a-sdk 1.x is a protobuf/gRPC-centric rewrite; the mature **0.3.x** line matches
the official A2A Python docs (`A2AStarletteApplication`, `AgentExecutor`,
`TextPart`/`DataPart`, `A2ACardResolver`) and keeps the example readable. We use
the official SDK directly rather than CrewAI's own `a2a` wrapper so the protocol —
not the framework — stays front and center.

---

## Phase 3 — AG-UI (streaming agent activity to a UI)

The crew (and the suppliers) now sit behind an **AG-UI** server: a FastAPI
endpoint that accepts a `RunAgentInput` and streams standard **AG-UI events**
over SSE — the event vocabulary a frontend consumes to show what the agent is
doing, live: streaming text, tool calls, evolving shared state, and run
lifecycle.

```
 Browser (vanilla-JS page, or CopilotKit)
        │  POST /agui            ▲  SSE: RUN_STARTED, TEXT_MESSAGE_*, TOOL_CALL_*,
        ▼  (RunAgentInput)       │       STATE_SNAPSHOT/DELTA, RUN_FINISHED
 AG-UI server (FastAPI + ag-ui-protocol)  ──►  runner  ──►  (A2A suppliers / CrewAI crew)
```

### What got added

```
agui/
  server.py          # FastAPI: POST /agui (SSE) + serves the demo page at /
  runners.py         # demo_runner (no LLM) and crew_runner (real crew)
  test_client.py     # Python SSE consumer — prints/asserts the event stream
  static/index.html  # zero-build browser page that renders the live stream
backend/
  a2a_client.py      # + aquery_supplier() async variant (the server is async)
  crew.py            # build_crew() now accepts step/task callbacks for event mapping
```

Two runners, chosen with `?mode=`:

| Mode | What it does | Needs |
|------|--------------|-------|
| `demo` (default) | Emits the full AG-UI event lifecycle and makes **real A2A calls** to the Phase 2 suppliers — great for seeing the protocol without spending anything | the two suppliers running |
| `crew` | Runs the **real CrewAI crew**, mapping its step/task callbacks to AG-UI events | suppliers + `ANTHROPIC_API_KEY` |

### Run it

```bash
# suppliers (Phase 2) + the AG-UI server
uv run python -m a2a_suppliers.flight_supplier &
uv run python -m a2a_suppliers.hotel_supplier  &
uv run python -m agui.server                       # http://127.0.0.1:8000
```

Then either open the browser page or use the Python client:

```bash
# Browser: open http://127.0.0.1:8000/  and click "Plan my trip"
# Terminal:
uv run python -m agui.test_client demo     # or: crew  (needs API credits)
```

A demo run produces this AG-UI event stream on the wire (real output, trimmed —
each line is one SSE frame; long payloads abbreviated with `…`):

```text
data: {"type":"RUN_STARTED","threadId":"t1","runId":"r1"}
data: {"type":"STATE_SNAPSHOT","snapshot":{"request":{"origin":"Athens","destination":"Tokyo","days":8,"travelers":2,…},"flights":null,"hotels":null,"plan":null}}
data: {"type":"TEXT_MESSAGE_START","messageId":"7e3c…","role":"assistant"}
data: {"type":"TEXT_MESSAGE_CONTENT","messageId":"7e3c…","delta":"Planning your 8-day trip"}
data: {"type":"TEXT_MESSAGE_CONTENT","messageId":"7e3c…","delta":" to Tokyo for 2 traveler"}
…                                                       # streamed in chunks
data: {"type":"TEXT_MESSAGE_END","messageId":"7e3c…"}
data: {"type":"STEP_STARTED","stepName":"research_flights"}
data: {"type":"TOOL_CALL_START","toolCallId":"9777…","toolCallName":"search_flights"}
data: {"type":"TOOL_CALL_ARGS","toolCallId":"9777…","delta":"{\"origin\": \"Athens\", \"destination\": \"Tokyo\", \"depart_date\": \"2026-10-05\", \"travelers\": 2}"}
data: {"type":"TOOL_CALL_END","toolCallId":"9777…"}
data: {"type":"TOOL_CALL_RESULT","toolCallId":"9777…","role":"tool","content":"{\"travelers\": 2, \"options\": [ … 3 flights from the A2A FlightSupplier … ]}"}
data: {"type":"STATE_DELTA","delta":[{"op":"replace","path":"/flights","value":[ … ]}]}
data: {"type":"STEP_FINISHED","stepName":"research_flights"}
…  # research_hotels emits the same STEP/TOOL_CALL_*/STATE_DELTA sequence (real A2A call to HotelSupplier)
data: {"type":"TEXT_MESSAGE_CONTENT","messageId":"bb15…","delta":"Picked Emirates (780 EUR/pp) and Hotel Ryumeikan …"}
data: {"type":"STATE_SNAPSHOT","snapshot":{"request":{…},"flights":[…],"hotels":[…],"plan":{…}}}
data: {"type":"RUN_FINISHED","threadId":"t1","runId":"r1","result":{"selected_flight":{"airline":"Emirates",…},"estimated_total":2855,"currency":"EUR",…}}
```

Note the wire format: every event is a JSON object on a `data:` line (AG-UI uses
camelCase — `threadId`, `toolCallName`), and `STATE_DELTA` carries a JSON-Patch
(RFC 6902) op the frontend applies to its local copy of the shared state.

### Using CopilotKit (the production-grade frontend)

The bundled page is deliberately dependency-free so you can *see* the raw AG-UI
events. For a real app you'd point **CopilotKit** (`@copilotkit/react-core` +
`@ag-ui/client`) at the same `/agui` endpoint and get chat, generative UI, shared
state, and human-in-the-loop out of the box — which is exactly what Phase 4
(A2UI) builds on.

### Testing without an API key

`demo` mode exercises the entire AG-UI layer (SSE encoding, every event type, the
browser renderer) **without an LLM**, by driving the real A2A suppliers. Only
`crew` mode needs `ANTHROPIC_API_KEY`.

---

## Phase 4 — A2UI (declarative, interactive UI from the agent)

Instead of plain text + a JSON state panel, the agent now emits **A2UI** — a
declarative description of the UI (flight cards, a chosen hotel, an itinerary, a
"Confirm & book" button). It's **data, not code**: the client renders it with its
own trusted component catalog, so an LLM can't inject markup. A2UI rides over the
Phase 3 AG-UI stream as `CUSTOM` events, and button presses round-trip back to the
agent — that's the **human-in-the-loop** approval gate.

```
 agent ──(AG-UI CUSTOM event: A2UI v0.9 message)──▶ browser A2UI renderer ──renders──▶ cards/buttons
   ▲                                                                                        │
   └────────────── new /agui run: {action:"book", …}  ◀── user clicks "Confirm & book" ─────┘
```

### What got added

```
agui/
  a2ui.py            # builds A2UI v0.9 surfaces (plan + booking) and VALIDATES each
                     #   message against crewai's bundled v0.9 spec validator
  runners.py         # + a2ui_runner: real A2A research -> A2UI surfaces -> HITL "book"
  static/index.html  # + an A2UI renderer (catalog subset, data binding, action round-trip)
  test_client.py     # + a2ui mode: re-validates surfaces on the wire + drives the HITL leg
```

We use the **A2UI v0.9 "basic catalog"** — emitting `createSurface` /
`updateComponents` / `updateDataModel` messages, with flat components (`Text`,
`Card`, `Column`, `Row`, `Button`, `TextField`, `Divider`), `{ "path": "/ptr" }`
data-model bindings, and `{ "event": { … } }` actions. The A2UI models, catalog,
and JSON-Schema validator all ship inside CrewAI (`crewai.a2a.extensions.a2ui`) —
we build messages and validate them against that spec before sending.

### Run it

Same stack as Phase 3 (suppliers + AG-UI server), then pick `a2ui`:

```bash
uv run python -m a2a_suppliers.flight_supplier &
uv run python -m a2a_suppliers.hotel_supplier  &
uv run python -m agui.server

# Browser: open http://127.0.0.1:8000/ , choose "a2ui", click "Plan my trip"
#          -> flight cards render; "Confirm & book" triggers the HITL booking surface
# Terminal:
uv run python -m agui.test_client a2ui     # validates surfaces + drives the booking round-trip
```

### What the agent emits (real, trimmed)

A2UI message #1 creates the surface; #2 sends the component tree (one component is
the `root`). Here's the create plus an excerpt of the components — a flight card
and the HITL **book** button:

```json
{ "version": "v0.9", "createSurface": { "surfaceId": "trip-plan",
    "catalogId": "https://a2ui.org/specification/v0_9/basic_catalog.json",
    "theme": { "primaryColor": "#5db0ff", "agentDisplayName": "TripWeaver" } } }
```
```json
{ "version": "v0.9", "updateComponents": { "surfaceId": "trip-plan", "components": [
  { "id": "root", "component": "Column", "children": ["f0", "book"] },
  { "id": "f0",  "component": "Card",   "child": "f0c" },
  { "id": "f0c", "component": "Column", "children": ["f0t", "f0m", "f0b"] },
  { "id": "f0t", "component": "Text",   "text": "Qatar Airways", "usageHint": "body" },
  { "id": "f0m", "component": "Text",   "text": "1 stop(s) · 18.0h · 845 EUR/pp", "usageHint": "caption" },
  { "id": "f0b", "component": "Button", "child": "f0bl",
    "action": { "event": { "name": "choose_flight", "context": { "airline": "Qatar Airways" } } } },
  { "id": "book", "component": "Button", "child": "bookbl", "primary": true,
    "action": { "event": { "name": "book", "context": { "airline": "Emirates", "total": 2855, "currency": "EUR" } } } }
] } }
```

When the user clicks **book**, the renderer posts a new run with
`forwardedProps = { action: "book", … }`; the agent responds with a `booking`
surface ("✅ Booking confirmed" + a confirmation code). Nothing is "booked" until
that human action — the HITL gate.

### Testing without an API key

`a2ui` mode (like `demo`) needs **no LLM** — it does the real A2A research and
renders A2UI surfaces; the test client re-validates every surface against the v0.9
spec and exercises the booking round-trip. Use `?mode=crew` to have the real crew
drive it (needs `ANTHROPIC_API_KEY`).

---

## All four phases, together

A single conversation now exercises the full stack: **CrewAI** orchestrates,
calls **A2A** supplier agents, streams everything over **AG-UI**, and renders it
as interactive **A2UI** — with a human-in-the-loop gate before booking. From here
the natural next steps are a production **CopilotKit** frontend (it consumes this
exact `/agui` stream and renders A2UI as generative UI) and richer LLM-authored
surfaces in `crew` mode.
