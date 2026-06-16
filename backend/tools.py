"""Mock travel-supplier tools for Phase 1.

These return canned (but realistic) data so we can prove the CrewAI
orchestration end-to-end without any external API or key beyond the LLM.

In Phase 2 these tools get replaced by real **A2A** calls to standalone
FlightSupplier / HotelSupplier agents — but the agents and tasks that use them
won't have to change, because the tool *interface* (name + args) stays the same.
"""

from __future__ import annotations

import json

from crewai.tools import tool


@tool("Search Flights")
def search_flights(origin: str, destination: str, depart_date: str, travelers: int = 1) -> str:
    """Search for round-trip flights between two cities.

    Args:
        origin: Departure city or airport (e.g. "Athens" or "ATH").
        destination: Arrival city or airport (e.g. "Tokyo" or "TYO").
        depart_date: Outbound date in YYYY-MM-DD.
        travelers: Number of travelers.

    Returns:
        A JSON string with a list of flight options (price is per person).
    """
    options = [
        {
            "airline": "Aegean + ANA (codeshare)",
            "from": origin,
            "to": destination,
            "depart_date": depart_date,
            "stops": 1,
            "duration_hours": 16.5,
            "price_per_person": 920,
            "currency": "EUR",
        },
        {
            "airline": "Qatar Airways",
            "from": origin,
            "to": destination,
            "depart_date": depart_date,
            "stops": 1,
            "duration_hours": 18.0,
            "price_per_person": 845,
            "currency": "EUR",
        },
        {
            "airline": "Emirates",
            "from": origin,
            "to": destination,
            "depart_date": depart_date,
            "stops": 2,
            "duration_hours": 22.5,
            "price_per_person": 780,
            "currency": "EUR",
        },
    ]
    return json.dumps({"travelers": travelers, "options": options}, indent=2)


@tool("Search Hotels")
def search_hotels(city: str, nights: int, travelers: int = 1) -> str:
    """Search for hotels in a city.

    Args:
        city: City to search in.
        nights: Number of nights.
        travelers: Number of travelers (affects room choice).

    Returns:
        A JSON string with a list of hotel options (price is per night, per room).
    """
    options = [
        {
            "name": "Hotel Ryumeikan Tokyo",
            "city": city,
            "area": "Marunouchi (near Tokyo Station)",
            "stars": 4,
            "price_per_night": 185,
            "currency": "EUR",
            "tags": ["central", "great transit access", "ryokan-style rooms"],
        },
        {
            "name": "Shibuya Stream Excel Hotel Tokyu",
            "city": city,
            "area": "Shibuya",
            "stars": 4,
            "price_per_night": 160,
            "currency": "EUR",
            "tags": ["nightlife", "food scene", "young/vibrant"],
        },
        {
            "name": "UNPLAN Kagurazaka (private room)",
            "city": city,
            "area": "Kagurazaka",
            "stars": 3,
            "price_per_night": 95,
            "currency": "EUR",
            "tags": ["budget", "quiet neighborhood", "local feel"],
        },
    ]
    return json.dumps({"nights": nights, "travelers": travelers, "options": options}, indent=2)


@tool("Search Activities")
def search_activities(city: str, interests: str) -> str:
    """Search for activities and experiences in a city.

    Args:
        city: City to search in.
        interests: Free-text interests (e.g. "food, hiking").

    Returns:
        A JSON string with a list of activity options (price is per person).
    """
    options = [
        {
            "name": "Tsukiji Outer Market food walk",
            "category": "food",
            "duration_hours": 3,
            "price_per_person": 75,
            "currency": "EUR",
        },
        {
            "name": "Mt. Takao day hike + onsen",
            "category": "hiking",
            "duration_hours": 7,
            "price_per_person": 60,
            "currency": "EUR",
        },
        {
            "name": "Ramen & izakaya night tour (Shinjuku)",
            "category": "food",
            "duration_hours": 3.5,
            "price_per_person": 90,
            "currency": "EUR",
        },
        {
            "name": "Kamakura hiking trail + Great Buddha",
            "category": "hiking",
            "duration_hours": 6,
            "price_per_person": 40,
            "currency": "EUR",
        },
        {
            "name": "teamLab Borderless digital art museum",
            "category": "culture",
            "duration_hours": 3,
            "price_per_person": 28,
            "currency": "EUR",
        },
    ]
    return json.dumps({"city": city, "interests": interests, "options": options}, indent=2)
