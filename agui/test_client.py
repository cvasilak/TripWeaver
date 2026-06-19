"""POST a run to the AG-UI server and print the decoded event stream.

Usage (with the AG-UI server + the two suppliers running):
    uv run python -m agui.test_client            # demo mode (no LLM)
    uv run python -m agui.test_client crew        # real crew (needs API credits)
"""

from __future__ import annotations

import json
import sys
import uuid

import httpx

SERVER = "http://127.0.0.1:8000/agui"


def _render(e: dict) -> None:
    t = e["type"]
    if t == "TEXT_MESSAGE_START":
        sys.stdout.write("\n[assistant] ")
    elif t == "TEXT_MESSAGE_CONTENT":
        sys.stdout.write(e["delta"])
    elif t == "TEXT_MESSAGE_END":
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
    mode = sys.argv[1] if len(sys.argv) > 1 else "demo"
    body = {
        "threadId": "t-" + uuid.uuid4().hex[:8],
        "runId": "r-" + uuid.uuid4().hex[:8],
        "messages": [],
        "tools": [],
        "context": [],
        "state": {},
        "forwardedProps": {},
    }
    seen: list[str] = []
    with httpx.Client(timeout=120) as client:
        with client.stream("POST", f"{SERVER}?mode={mode}", json=body) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line or not line.startswith("data:"):
                    continue
                event = json.loads(line[len("data:"):].strip())
                seen.append(event["type"])
                _render(event)

    print("\n\nevent types seen:", seen)
    if mode == "demo":
        for required in ("RUN_STARTED", "TEXT_MESSAGE_CONTENT", "TOOL_CALL_START",
                         "TOOL_CALL_RESULT", "STATE_DELTA", "STATE_SNAPSHOT", "RUN_FINISHED"):
            assert required in seen, f"missing expected event: {required}"
        assert seen.count("TOOL_CALL_START") == 2, f"expected 2 A2A tool calls, got {seen.count('TOOL_CALL_START')}"
        print("DEMO STREAM OK ✓  (2 real A2A tool calls + full state/run lifecycle)")


if __name__ == "__main__":
    main()
