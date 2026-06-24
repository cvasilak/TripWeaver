"""POST a run to the AG-UI server and print the decoded event stream.

Usage (with the AG-UI server + the two suppliers running):
    uv run python -m agui.test_client                  # demo mode (no LLM)
    uv run python -m agui.test_client crew             # real crew (needs API credits)
    uv run python -m agui.test_client demo --debug     # also echo each raw AG-UI event
"""

from __future__ import annotations

import json
import sys
import uuid

import httpx

SERVER = "http://127.0.0.1:8000/agui"


class Renderer:
    """Pretty-prints the AG-UI stream.

    With ``debug=True`` it also echoes every raw event as JSON on its own line.
    In that mode assistant text is accumulated and flushed once per message (at
    ``TEXT_MESSAGE_END``) so the raw lines don't fragment the streamed reply.
    """

    def __init__(self, debug: bool = False) -> None:
        self.debug = debug
        self._text: dict[str | None, str] = {}

    def feed(self, e: dict) -> None:
        if self.debug:
            print(f"  raw › {json.dumps(e)}")
        self._render(e)

    def _render(self, e: dict) -> None:
        t = e["type"]
        if t == "TEXT_MESSAGE_START":
            if self.debug:
                self._text[e.get("messageId")] = ""
            else:
                sys.stdout.write("\n[assistant] ")
        elif t == "TEXT_MESSAGE_CONTENT":
            if self.debug:
                mid = e.get("messageId")
                self._text[mid] = self._text.get(mid, "") + e["delta"]
            else:
                sys.stdout.write(e["delta"])
        elif t == "TEXT_MESSAGE_END":
            if self.debug:
                print(f"  [assistant] {self._text.pop(e.get('messageId'), '')}")
            else:
                sys.stdout.write("\n")
        elif t == "TOOL_CALL_START":
            print(f"  TOOL_CALL_START  {e['toolCallName']} (id={e['toolCallId'][:6]})")
        elif t == "TOOL_CALL_RESULT":
            n = len(json.loads(e["content"]).get("options", []))
            print(f"  TOOL_CALL_RESULT  -> {n} options")
        elif t in ("STEP_STARTED", "STEP_FINISHED"):
            print(f"  {t}  {e.get('stepName', '')}")
        elif t in ("STATE_SNAPSHOT", "STATE_DELTA", "RUN_STARTED", "RUN_FINISHED", "RUN_ERROR"):
            extra = f"  {e.get('message', '')}" if t == "RUN_ERROR" else ""
            print(f"  {t}{extra}")
        sys.stdout.flush()


def main() -> None:
    args = sys.argv[1:]
    debug = any(a in ("--debug", "-d", "--raw") for a in args)
    positional = [a for a in args if not a.startswith("-")]
    mode = positional[0] if positional else "demo"

    body = {
        "threadId": "t-" + uuid.uuid4().hex[:8],
        "runId": "r-" + uuid.uuid4().hex[:8],
        "messages": [],
        "tools": [],
        "context": [],
        "state": {},
        "forwardedProps": {},
    }
    renderer = Renderer(debug=debug)
    seen: list[str] = []
    with httpx.Client(timeout=120) as client:
        with client.stream("POST", f"{SERVER}?mode={mode}", json=body) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line or not line.startswith("data:"):
                    continue
                event = json.loads(line[len("data:"):].strip())
                seen.append(event["type"])
                renderer.feed(event)

    print("\n\nevent types seen:", seen)
    if mode == "demo":
        for required in ("RUN_STARTED", "TEXT_MESSAGE_CONTENT", "TOOL_CALL_START",
                         "TOOL_CALL_RESULT", "STATE_DELTA", "STATE_SNAPSHOT", "RUN_FINISHED"):
            assert required in seen, f"missing expected event: {required}"
        assert seen.count("TOOL_CALL_START") == 2, f"expected 2 A2A tool calls, got {seen.count('TOOL_CALL_START')}"
        print("DEMO STREAM OK ✓  (2 real A2A tool calls + full state/run lifecycle)")


if __name__ == "__main__":
    main()
