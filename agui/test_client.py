"""POST a run to the AG-UI server and print/validate the decoded event stream.

Usage (with the AG-UI server + the two suppliers running):
    uv run python -m agui.test_client                  # demo mode (raw AG-UI events, no LLM)
    uv run python -m agui.test_client a2ui             # A2UI surfaces + HITL book round-trip (no LLM)
    uv run python -m agui.test_client crew             # real crew (needs API key)
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
            print(f"  TOOL_CALL_RESULT  -> {len(json.loads(e['content']).get('options', []))} options")
        elif t == "CUSTOM" and e.get("name") == "a2ui":
            print(f"  CUSTOM a2ui      {next(iter(k for k in e['value'] if k != 'version'))}")
        elif t in ("STEP_STARTED", "STEP_FINISHED"):
            print(f"  {t}  {e.get('stepName', '')}")
        elif t in ("STATE_SNAPSHOT", "STATE_DELTA", "RUN_STARTED", "RUN_FINISHED", "RUN_ERROR"):
            print(f"  {t}{('  ' + e.get('message', '')) if t == 'RUN_ERROR' else ''}")
        sys.stdout.flush()


def run(mode: str, forwarded_props: dict, debug: bool = False) -> list[dict]:
    body = {
        "threadId": "t-" + uuid.uuid4().hex[:8],
        "runId": "r-" + uuid.uuid4().hex[:8],
        "messages": [], "tools": [], "context": [], "state": {},
        "forwardedProps": forwarded_props,
    }
    events: list[dict] = []
    renderer = Renderer(debug=debug)
    with httpx.Client(timeout=120) as client:
        with client.stream("POST", f"{SERVER}?mode={mode}", json=body) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if line and line.startswith("data:"):
                    e = json.loads(line[len("data:"):].strip())
                    events.append(e)
                    renderer.feed(e)
    return events


def _a2ui_messages(events: list[dict]) -> list[dict]:
    return [e["value"] for e in events if e["type"] == "CUSTOM" and e.get("name") == "a2ui"]


def main() -> None:
    args = sys.argv[1:]
    debug = any(a in ("--debug", "-d", "--raw") for a in args)
    positional = [a for a in args if not a.startswith("-")]
    mode = positional[0] if positional else "demo"

    if mode == "a2ui":
        # validate A2UI messages on the wire against the real spec
        from crewai.a2a.extensions.a2ui.validator import validate_a2ui_message_v09

        print("=== leg 1: plan (renders A2UI surfaces) ===")
        events = run("a2ui", {}, debug=debug)
        msgs = _a2ui_messages(events)
        for m in msgs:
            validate_a2ui_message_v09(m)  # raises if any wire message is non-compliant
        kinds = [next(k for k in m if k != "version") for m in msgs]
        assert "createSurface" in kinds and "updateComponents" in kinds and "updateDataModel" in kinds, kinds
        assert [e["type"] for e in events].count("TOOL_CALL_START") == 2, "expected 2 real A2A tool calls"
        comps = next(m["updateComponents"]["components"] for m in msgs if "updateComponents" in m)
        book = next(c for c in comps if c["component"] == "Button" and c["action"]["event"]["name"] == "book")
        print(f"\n{len(msgs)} A2UI messages, all spec-valid; {len(comps)} components; found HITL 'book' button")

        print("\n=== leg 2: human-in-the-loop — click 'Confirm & book' ===")
        ctx = book["action"]["event"]["context"]
        events2 = run("a2ui", {"action": "book", **ctx}, debug=debug)
        msgs2 = _a2ui_messages(events2)
        for m in msgs2:
            validate_a2ui_message_v09(m)
        assert any(m.get("createSurface", {}).get("surfaceId") == "booking" for m in msgs2), "no booking surface"
        confirm_texts = [c.get("text", "") for m in msgs2 if "updateComponents" in m
                         for c in m["updateComponents"]["components"] if c["component"] == "Text"]
        assert any("confirmed" in str(t).lower() for t in confirm_texts), confirm_texts
        print("\nA2UI STREAM OK ✓  (spec-valid surfaces, 2 real A2A calls, HITL booking confirmed)")
        return

    events = run(mode, {}, debug=debug)
    if mode == "demo":
        seen = [e["type"] for e in events]
        for required in ("RUN_STARTED", "TOOL_CALL_START", "TOOL_CALL_RESULT", "STATE_DELTA", "RUN_FINISHED"):
            assert required in seen, f"missing expected event: {required}"
        assert seen.count("TOOL_CALL_START") == 2
        print("\nDEMO STREAM OK ✓  (2 real A2A tool calls + full state/run lifecycle)")


if __name__ == "__main__":
    main()
