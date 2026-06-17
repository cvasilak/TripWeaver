# TripWeaver

A conversational trip-planning concierge, built as a hands-on example of four
agent technologies stacked together:

| Tech | Role in TripWeaver | Phase |
|------|--------------------|-------|
| **CrewAI** | The orchestration brain — a crew of role-based agents | 1 ✓ |
| **A2A** | Reaching external supplier agents (flights, hotels) | **2 (this phase)** |
| **AG-UI** | Streaming the live agent activity to a frontend | 3 |
| **A2UI** | Declarative, interactive UI rendered from the agent | 4 |

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

## Next phase

Phase 3 wraps the crew in an **AG-UI** server and connects a frontend, streaming
the live agent activity (text, tool calls, shared state, human-in-the-loop) to
the user.
