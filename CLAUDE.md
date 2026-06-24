# TripWeaver — Claude Code guide

A conversational trip-planning concierge that stacks four agent technologies —
**CrewAI** (orchestration), **A2A** (supplier agents), **AG-UI** (event streaming),
**A2UI** (declarative UI) — behind a **CopilotKit** frontend. Built phase-by-phase;
see [README.md](README.md) for the narrative. The current work adds a
**human-in-the-loop** booking flow in crew mode.

## Layout

```
backend/        CrewAI crew + tools + models + LLM config + CLI
  config.py     LLM config — Claude Sonnet 4.5 via CrewAI's native Anthropic provider
  models.py     TripPlan, FlightOption(s)/HotelOption(s), BookingConfirmation (Pydantic)
  tools.py      search_flights/hotels (A2A), search_activities + book_flight/hotel (mock)
  crew.py       build_crew (autonomous CLI) + build_research/planning/booking_crew (HITL)
  a2a_client.py A2A discovery + query (sync query_supplier + async aquery_supplier)
  main.py       CLI entry point — runs the autonomous crew on SAMPLE_REQUEST
a2a_suppliers/  standalone A2A servers (a2a-sdk): FlightSupplier :8001, HotelSupplier :8002
agui/           AG-UI server + runners
  server.py     FastAPI: POST /agui (SSE) + serves the static demo page at /  (:8000)
  runners.py    demo_runner, crew_runner (HITL 3-run state machine), a2ui_runner
  a2ui.py       A2UI v0.9 surface builders + carrier (CUSTOM events or render_a2ui tool)
  static/       zero-build demo page (the :8000 page)
frontend/       CopilotKit Next.js app (:3000) — see frontend/CLAUDE.md before editing
  app/page.tsx                  A2UI renderer + agent_step + select_options/confirm_booking
  app/api/copilotkit/route.ts   CopilotRuntime -> HttpAgent -> :8000 ?mode=crew&a2ui=tool
```

## Two frontends — don't confuse them

- **Demo page** at `http://127.0.0.1:8000/` (served by `agui.server`, file
  `agui/static/index.html`): dependency-free, renders raw AG-UI/A2UI, mode via `?mode=`.
- **CopilotKit app** at `http://127.0.0.1:3000` (`frontend/`, `npm run dev`): the
  production frontend; always drives **crew** mode. **All HITL work lives here.**

## Modes (`?mode=` on `/agui`)

- `demo` — no LLM; real A2A calls; full AG-UI lifecycle.
- `crew` — the real CrewAI crew (needs `ANTHROPIC_API_KEY`). **Build features against this.**
- `a2ui` — no LLM; real A2A; renders A2UI surfaces + a "Confirm & book" gate.
- `?a2ui=tool` makes A2UI ride as a `render_a2ui` tool call (required by CopilotKit)
  instead of `CUSTOM` events; set per-request.

## HITL flow (crew mode)

Three runs, because an AG-UI run is one-directional SSE and each human decision
returns on the next run as a `role:"tool"` message:

```
Run 1  research crew  → select_options  (await) → pick flight + hotel
Run 2  planning crew  → TripPlan → confirm_booking (await) → confirm
Run 3  booking crew   → 🎉 booking confirmed
```

Each gate is a **result-less** tool call (`TOOL_CALL_START/ARGS/END` + `RUN_FINISHED`).
CopilotKit's `renderAndWaitForResponse` renders it with a `respond(...)` callback; the
reply arrives on the next run and is parsed by `_read_selection` / `_read_confirmation`
in [agui/runners.py](agui/runners.py) (phase order: confirmation → pick → fresh).

## Run it

```bash
uv venv --python 3.12 && uv pip install -r requirements.txt
cp .env.example .env            # set ANTHROPIC_API_KEY
uv run python -m a2a_suppliers.flight_supplier &     # :8001
uv run python -m a2a_suppliers.hotel_supplier  &     # :8002
uv run python -m agui.server                         # :8000
cd frontend && npm install && npm run dev            # :3000 (CopilotKit app)
```

CLI only (no UI): `uv run python -m backend.main`.

## Gotchas

- **`agui.server` does NOT hot-reload.** Restart it after any backend change, or run
  `uv run uvicorn agui.server:app --reload --port 8000` while iterating. (Next dev
  fast-refreshes `page.tsx` on its own.)
- LLM defaults to **Claude Sonnet 4.5** (native structured-outputs path → reliable
  `output_pydantic`); override with `TRIPWEAVER_MODEL`.
- Supplier URLs via `TRIPWEAVER_FLIGHT_SUPPLIER_URL` / `TRIPWEAVER_HOTEL_SUPPLIER_URL`.
- `book_flight`/`book_hotel` are **local mocks** — there's no A2A "book" supplier skill yet.
- CrewAI `output_pydantic` lists: read each task's output via `result.tasks_output[i].pydantic`.

## Conventions

- Keep each distinct change as its own commit.
- `frontend/` ships its own [frontend/CLAUDE.md](frontend/CLAUDE.md) — read it before
  writing Next.js code (its APIs differ from stock Next.js).
