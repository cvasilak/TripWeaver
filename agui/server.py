"""AG-UI FastAPI server.

    POST /agui[?mode=demo|crew]   -> streams AG-UI events as SSE
    GET  /                        -> the bundled vanilla-JS demo page

Run it:
    uv run python -m agui.server                 # http://127.0.0.1:8000
    # then open http://127.0.0.1:8000/ in a browser, or POST to /agui
"""

from __future__ import annotations

import os
from pathlib import Path

from ag_ui.core import RunAgentInput, RunErrorEvent
from ag_ui.encoder import EventEncoder
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from agui import a2ui
from agui.runners import RUNNERS, demo_runner

app = FastAPI(title="TripWeaver AG-UI server")


@app.post("/agui")
async def agui(input: RunAgentInput, request: Request) -> StreamingResponse:
    """Accept a RunAgentInput and stream the run back as AG-UI events (SSE)."""
    mode = request.query_params.get("mode") or os.getenv("TRIPWEAVER_AGUI_MODE", "demo")
    # A2UI carrier: ?a2ui=tool makes surfaces ride as render_a2ui tool calls
    # (CopilotKit); default "custom" emits CUSTOM events (our vanilla renderer).
    carrier = request.query_params.get("a2ui")
    runner = RUNNERS.get(mode, demo_runner)
    encoder = EventEncoder()

    async def stream():
        if carrier:
            a2ui.set_carrier(carrier)
        try:
            async for event in runner(input):
                yield encoder.encode(event)
        except Exception as e:  # noqa: BLE001 - report as a protocol RUN_ERROR, not an HTTP 500
            yield encoder.encode(RunErrorEvent(message=str(e)))

    return StreamingResponse(stream(), media_type=encoder.get_content_type())


# Serve the demo browser page from the same origin (so the page's fetch() to
# /agui has no CORS issues). Mounted last so it doesn't shadow /agui.
_STATIC = Path(__file__).parent / "static"
app.mount("/", StaticFiles(directory=str(_STATIC), html=True), name="static")


def main() -> None:
    import uvicorn
    from dotenv import load_dotenv

    load_dotenv()  # so crew mode picks up ANTHROPIC_API_KEY from .env, like backend.main

    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    print(f"TripWeaver AG-UI server on http://{host}:{port}  (open / in a browser, or POST /agui)")
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
