# TripWeaver — CopilotKit frontend (full runtime)

A **Next.js** app that drives the TripWeaver AG-UI agent through the **full
CopilotKit stack**: a `CopilotRuntime` (the extra Node dependency) + the
`<CopilotKit>` provider + `<CopilotChat>`. A2UI surfaces render via CopilotKit's
**native A2UI middleware** (`@ag-ui/a2ui-middleware`, shipped with the runtime).

> This is the heavier sibling of the `copilotkit` branch, which connects to
> `/agui` directly with `@ag-ui/client` and renders A2UI with a hand-written
> renderer. Here, CopilotKit's runtime + UI do that work for you.

## Architecture

```
Browser ──▶ /api/copilotkit  (CopilotRuntime, Node)  ──▶ HttpAgent ──▶ AG-UI server :8000 ──▶ A2A suppliers
 (CopilotChat UI)            app/api/copilotkit/route.ts    (@ag-ui/client)    (agui.server)       (Phase 2)
```

- The browser only talks to `/api/copilotkit` (same origin → no CORS). The
  **runtime** forwards to the AG-UI server server-to-server.
- `agents: { tripweaver: new HttpAgent({ url }) }` registers our agent;
  `ExperimentalEmptyAdapter` is used because our AG-UI agent *is* the LLM (no
  OpenAI/Anthropic adapter needed).
- `a2ui: {}` on the runtime enables CopilotKit's native A2UI rendering.

## Run

Backend first (from the repo root):

```bash
uv run python -m a2a_suppliers.flight_supplier &
uv run python -m a2a_suppliers.hotel_supplier  &
uv run python -m agui.server                       # :8000
```

Then the app:

```bash
cd frontend
npm install        # first time
npm run dev        # http://localhost:3000
```

Open http://localhost:3000 and ask **“Plan my 8-day trip to Tokyo.”**

The agent it talks to is set by `AGUI_URL` (default
`http://127.0.0.1:8000/agui?mode=a2ui`). Point it at `?mode=crew` for the real
CrewAI run (needs `ANTHROPIC_API_KEY`), or `?mode=demo` for raw events.

## Key files

```
app/api/copilotkit/route.ts   # CopilotRuntime + HttpAgent(-> /agui) + EmptyAdapter + a2ui middleware
app/page.tsx                  # <CopilotKit runtimeUrl agent="tripweaver"> + <CopilotChat>
app/layout.tsx, app/globals.css
```

## Status / caveats

Verified: `next build` is clean (TypeScript passes), the page serves, and the
`/api/copilotkit` runtime route is mounted and responds. **Not** automated-tested
in a browser: the live chat handshake and the native A2UI rendering — open the
app to exercise those. A2UI rendering depends on CopilotKit's middleware
consuming the agent's A2UI stream; if surfaces don't appear, the chat (text +
tool calls) still works, and the direct-renderer app on the `copilotkit` branch
is the reference for A2UI rendering.
