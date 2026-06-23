"""Tools the crew's agents use.

Phase 2 change: flights and hotels are no longer canned local data — they're
fetched from standalone **A2A supplier agents** (see ``a2a_suppliers/``). The
``@tool`` *interface* is unchanged from Phase 1, so the agents and tasks in
``crew.py`` didn't have to change at all; only the tool bodies now make A2A
calls. Activities stays a local mock, to show a crew mixing remote A2A agents
with ordinary local tools.

The supplier URLs are configurable so you can point at remote/other-vendor
agents:
    TRIPWEAVER_FLIGHT_SUPPLIER_URL (default http://127.0.0.1:8001)
    TRIPWEAVER_HOTEL_SUPPLIER_URL  (default http://127.0.0.1:8002)
"""

from __future__ import annotations

import json
import os
import uuid

from crewai.tools import tool

from .a2a_client import query_supplier

FLIGHT_SUPPLIER_URL = os.getenv("TRIPWEAVER_FLIGHT_SUPPLIER_URL", "http://127.0.0.1:8001")
HOTEL_SUPPLIER_URL = os.getenv("TRIPWEAVER_HOTEL_SUPPLIER_URL", "http://127.0.0.1:8002")


@tool("Search Flights")
def search_flights(origin: str, destination: str, depart_date: str, travelers: int = 1) -> str:
    """Search for round-trip flights between two cities (via the FlightSupplier A2A agent).

    Args:
        origin: Departure city or airport (e.g. "Athens" or "ATH").
        destination: Arrival city or airport (e.g. "Tokyo" or "TYO").
        depart_date: Outbound date in YYYY-MM-DD.
        travelers: Number of travelers.

    Returns:
        A JSON string with a list of flight options (price is per person).
    """
    try:
        data = query_supplier(
            FLIGHT_SUPPLIER_URL,
            {"origin": origin, "destination": destination,
             "depart_date": depart_date, "travelers": travelers},
        )
        return json.dumps(data, indent=2)
    except Exception as e:  # supplier down / unreachable — tell the agent, don't crash the crew
        return json.dumps({"error": f"FlightSupplier ({FLIGHT_SUPPLIER_URL}) unavailable: {e}"})


@tool("Search Hotels")
def search_hotels(city: str, nights: int, travelers: int = 1) -> str:
    """Search for hotels in a city (via the HotelSupplier A2A agent).

    Args:
        city: City to search in.
        nights: Number of nights.
        travelers: Number of travelers (affects room choice).

    Returns:
        A JSON string with a list of hotel options (price is per night, per room).
    """
    try:
        data = query_supplier(
            HOTEL_SUPPLIER_URL,
            {"city": city, "nights": nights, "travelers": travelers},
        )
        return json.dumps(data, indent=2)
    except Exception as e:
        return json.dumps({"error": f"HotelSupplier ({HOTEL_SUPPLIER_URL}) unavailable: {e}"})


@tool("Search Activities")
def search_activities(city: str, interests: str) -> str:
    """Search for activities and experiences in a city (local mock — not an A2A supplier).

    Args:
        city: City to search in.
        interests: Free-text interests (e.g. "food, hiking").

    Returns:
        A JSON string with a list of activity options (price is per person).
    """
    options = [
        {"name": "Tsukiji Outer Market food walk", "category": "food",
         "duration_hours": 3, "price_per_person": 75, "currency": "EUR"},
        {"name": "Mt. Takao day hike + onsen", "category": "hiking",
         "duration_hours": 7, "price_per_person": 60, "currency": "EUR"},
        {"name": "Ramen & izakaya night tour (Shinjuku)", "category": "food",
         "duration_hours": 3.5, "price_per_person": 90, "currency": "EUR"},
        {"name": "Kamakura hiking trail + Great Buddha", "category": "hiking",
         "duration_hours": 6, "price_per_person": 40, "currency": "EUR"},
        {"name": "teamLab Borderless digital art museum", "category": "culture",
         "duration_hours": 3, "price_per_person": 28, "currency": "EUR"},
    ]
    return json.dumps({"city": city, "interests": interests, "options": options}, indent=2)


@tool("Book Flight")
def book_flight(airline: str, amount: float = 0.0, currency: str = "EUR") -> str:
    """Reserve the traveler's chosen flight (local mock reservation system).

    Args:
        airline: The airline of the chosen flight.
        amount: Total flight charge for the whole party.
        currency: ISO currency code.

    Returns:
        A JSON string with the reservation reference and status.
    """
    ref = "FL-" + uuid.uuid4().hex[:6].upper()
    return json.dumps(
        {"reference": ref, "status": "confirmed", "airline": airline,
         "amount": amount, "currency": currency}
    )


@tool("Book Hotel")
def book_hotel(hotel_name: str, amount: float = 0.0, currency: str = "EUR") -> str:
    """Reserve the traveler's chosen hotel (local mock reservation system).

    Args:
        hotel_name: The name of the chosen hotel.
        amount: Total hotel charge for the stay.
        currency: ISO currency code.

    Returns:
        A JSON string with the reservation reference and status.
    """
    ref = "HT-" + uuid.uuid4().hex[:6].upper()
    return json.dumps(
        {"reference": ref, "status": "confirmed", "hotel_name": hotel_name,
         "amount": amount, "currency": currency}
    )
