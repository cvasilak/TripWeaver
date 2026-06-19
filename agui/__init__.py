"""AG-UI server for TripWeaver (Phase 3).

Exposes the crew over the **Agent-User Interaction Protocol** (AG-UI): a POST
endpoint that accepts a ``RunAgentInput`` and streams standard AG-UI events
(RUN_STARTED, TEXT_MESSAGE_*, TOOL_CALL_*, STATE_*, RUN_FINISHED) over SSE — the
event vocabulary a frontend (CopilotKit, or the bundled vanilla-JS page) consumes
to show live agent activity.

Two runners (pick with ``?mode=``):
  - ``demo``  no LLM; makes *real* A2A calls to the Phase 2 suppliers — testable
              without API credits.
  - ``crew``  runs the real CrewAI crew, mapping its callbacks to AG-UI events.
"""
