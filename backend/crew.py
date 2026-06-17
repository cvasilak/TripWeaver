"""The TripWeaver crew: role-based agents collaborating on a trip plan.

Phase 1 uses a **sequential** process — the clearest way to see CrewAI's core
ideas (roles, tools, tasks, and context flowing from one task to the next).
Each researcher feeds the Itinerary Designer, who feeds the Budget Auditor, who
emits the final structured TripPlan.

(A hierarchical process with a delegating "Concierge" manager is a natural
upgrade — see the README — but sequential is more predictable and cheaper to
run while you're learning.)
"""

from __future__ import annotations

from crewai import Agent, Crew, Process, Task

from .config import get_llm
from .models import TripPlan
from .tools import search_activities, search_flights, search_hotels


def build_crew() -> Crew:
    llm = get_llm()

    # ---- Agents (the "who") ------------------------------------------------
    flight_researcher = Agent(
        role="Flight Researcher",
        goal="Find the best-value flights that fit the traveler's dates and budget.",
        backstory=(
            "A meticulous air-travel specialist who balances price, total travel "
            "time, and number of stops, and never recommends an option without a reason."
        ),
        tools=[search_flights],
        llm=llm,
        allow_delegation=False,
        verbose=True,
    )

    hotel_researcher = Agent(
        role="Hotel Researcher",
        goal="Find lodging that matches the traveler's style, location needs, and budget.",
        backstory=(
            "A well-traveled concierge who knows that the right neighborhood matters "
            "as much as the room, and matches hotels to how the traveler wants to spend their days."
        ),
        tools=[search_hotels],
        llm=llm,
        allow_delegation=False,
        verbose=True,
    )

    activities_curator = Agent(
        role="Activities Curator",
        goal="Surface experiences that genuinely match the traveler's interests.",
        backstory=(
            "A local-experiences curator who turns a list of interests into specific, "
            "well-paced things to actually do."
        ),
        tools=[search_activities],
        llm=llm,
        allow_delegation=False,
        verbose=True,
    )

    itinerary_designer = Agent(
        role="Itinerary Designer",
        goal="Weave flights, lodging, and activities into a coherent day-by-day plan.",
        backstory=(
            "A trip architect who sequences days so they flow well — not too packed, "
            "respecting arrival times and travel between areas. Picks one flight and one hotel."
        ),
        llm=llm,
        allow_delegation=False,
        verbose=True,
    )

    budget_auditor = Agent(
        role="Budget Auditor",
        goal="Make sure the plan adds up and fits the stated budget.",
        backstory=(
            "A sharp-eyed numbers person who totals every cost, compares it to the "
            "budget, and proposes concrete cuts when the plan runs over."
        ),
        llm=llm,
        allow_delegation=False,
        verbose=True,
    )

    # ---- Tasks (the "what", in order) -------------------------------------
    research_flights = Task(
        description=(
            "Find flight options from {origin} to {destination} for {travelers} traveler(s), "
            "departing {start_date} for a {days}-day trip. Use the Search Flights tool, then "
            "compare the options on price, duration, and stops. Recommend the best 2-3."
        ),
        expected_output=(
            "A short ranked list of 2-3 flights: airline, price per person in {currency}, "
            "total duration, stops, and a one-line reason for the ranking."
        ),
        agent=flight_researcher,
    )

    research_hotels = Task(
        description=(
            "Find hotels in {destination} for {travelers} traveler(s) for {days} nights that "
            "suit a trip themed around these interests: {interests}, and a total budget near "
            "{budget} {currency}. Use the Search Hotels tool and compare options."
        ),
        expected_output=(
            "A ranked list of 2-3 hotels: name, neighborhood, price per night in {currency}, "
            "estimated total for the stay, and a one-line reason."
        ),
        agent=hotel_researcher,
    )

    research_activities = Task(
        description=(
            "Suggest activities and experiences in {destination} that match these interests: "
            "{interests}, for a {days}-day trip. Use the Search Activities tool."
        ),
        expected_output=(
            "A list of recommended activities: name, category, duration, and price per person "
            "in {currency}."
        ),
        agent=activities_curator,
    )

    design_itinerary = Task(
        description=(
            "Using the flight, hotel, and activity research, design a day-by-day itinerary for "
            "the {days}-day trip to {destination} for {travelers} traveler(s). Choose exactly ONE "
            "flight and ONE hotel. Lay out each day with a morning, afternoon, and evening, and "
            "keep a running per-day cost estimate. Respect a realistic pace (account for the long "
            "flight on arrival day)."
        ),
        expected_output=(
            "A clear day-by-day plan (day number, theme, morning/afternoon/evening, per-day cost), "
            "plus the single chosen flight and hotel with reasons, and a rough running total."
        ),
        context=[research_flights, research_hotels, research_activities],
        agent=itinerary_designer,
    )

    audit_budget = Task(
        description=(
            "Review the proposed itinerary against the budget of {budget} {currency} for "
            "{travelers} traveler(s). Sum all costs: flights (per person x travelers) + hotel "
            "(per night x nights) + activities (per person x travelers). Decide whether the trip "
            "is within budget. If it is over, suggest specific, concrete cuts. Then produce the "
            "final structured trip plan."
        ),
        expected_output=(
            "A single JSON object for the final TripPlan, with ALL of these fields populated "
            "in one response (never a partial object): summary, selected_flight, selected_hotel, "
            "itinerary (one entry per day), currency, estimated_total (whole party), budget, "
            "within_budget, and budget_notes."
        ),
        context=[design_itinerary],
        agent=budget_auditor,
        output_pydantic=TripPlan,
    )

    return Crew(
        agents=[
            flight_researcher,
            hotel_researcher,
            activities_curator,
            itinerary_designer,
            budget_auditor,
        ],
        tasks=[
            research_flights,
            research_hotels,
            research_activities,
            design_itinerary,
            audit_budget,
        ],
        process=Process.sequential,
        verbose=True,
    )
