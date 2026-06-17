"""Standalone A2A supplier agents for TripWeaver (Phase 2).

Each module here is an independent A2A server — a FlightSupplier and a
HotelSupplier — built on the official ``a2a-sdk`` (NOT CrewAI). They publish an
Agent Card at ``/.well-known/agent-card.json`` advertising their skills, and
answer A2A messages with structured data.

The point: these could be operated by entirely different vendors in any
language/framework. TripWeaver's crew discovers and calls them as a generic A2A
client, which is what makes this a real demonstration of agent interoperability.
"""
