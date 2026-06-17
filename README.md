# TripWeaver

A conversational trip-planning concierge, built as a hands-on example of four
agent technologies stacked together:

| Tech | Role in TripWeaver | Phase |
|------|--------------------|-------|
| **CrewAI** | The orchestration brain — a crew of role-based agents | **1 (this phase)** |
| **A2A** | Reaching external supplier agents (flights, hotels) | 2 |
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
  tools.py    # mock Search Flights / Hotels / Activities tools (@tool)
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

## Next phase

Phase 2 pulls the flight and hotel tools out into standalone **A2A** agents with
Agent Cards, and has this crew discover and call them — proving cross-vendor
agent interoperability.
