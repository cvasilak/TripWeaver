"""The TripWeaver crew: role-based agents collaborating on a trip plan.

Phase 1 uses a **sequential** process — the clearest way to see CrewAI's core
ideas (roles, tools, tasks, and context flowing from one task to the next).
Each researcher feeds the Itinerary Designer, who feeds the Budget Auditor, who
emits the final structured TripPlan.

For the **human-in-the-loop** flow the crew is split into two cooperating crews:

* ``build_research_crew()`` — the Flight/Hotel Researchers produce a *ranked list
  of pickable options* (structured ``FlightOptions`` / ``HotelOptions``).
* ``build_planning_crew()`` — once the traveler has picked one flight and one
  hotel, the Activities Curator, Itinerary Designer, and Budget Auditor plan the
  trip *around that choice* (the pick is injected via ``kickoff`` inputs).

``build_crew()`` keeps the original single autonomous run (used by the CLI),
where the crew picks the flight and hotel itself.

(A hierarchical process with a delegating "Concierge" manager is a natural
upgrade — see the README — but sequential is more predictable and cheaper to
run while you're learning.)
"""

from __future__ import annotations

from crewai import Agent, Crew, Process, Task

from .config import get_llm
from .models import FlightOptions, HotelOptions, TripPlan
from .tools import search_activities, search_flights, search_hotels


def _build_agents(llm) -> dict[str, Agent]:
    """The five role-based agents, shared by every crew variant."""
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

    return {
        "flight_researcher": flight_researcher,
        "hotel_researcher": hotel_researcher,
        "activities_curator": activities_curator,
        "itinerary_designer": itinerary_designer,
        "budget_auditor": budget_auditor,
    }


# ---- Task builders (reused across crew variants) --------------------------
def _research_flights_task(agent: Agent) -> Task:
    return Task(
        description=(
            "Find flight options from {origin} to {destination} for {travelers} traveler(s), "
            "departing {start_date} for a {days}-day trip. Use the Search Flights tool, then "
            "compare the options on price, duration, and stops. Recommend the best 2-3 so the "
            "traveler can pick one."
        ),
        expected_output=(
            "A ranked list of 2-3 flight options. For EACH option set: ref (a short stable id "
            "like 'F1', 'F2', in ranked order), airline, stops, duration_hours, "
            "price_per_person in {currency}, and a one-line 'why'."
        ),
        agent=agent,
        output_pydantic=FlightOptions,
    )


def _research_hotels_task(agent: Agent) -> Task:
    return Task(
        description=(
            "Find hotels in {destination} for {travelers} traveler(s) for {days} nights that "
            "suit a trip themed around these interests: {interests}, and a total budget near "
            "{budget} {currency}. Use the Search Hotels tool and compare options so the traveler "
            "can pick one."
        ),
        expected_output=(
            "A ranked list of 2-3 hotel options. For EACH option set: ref (a short stable id "
            "like 'H1', 'H2', in ranked order), name, area (neighborhood), price_per_night in "
            "{currency}, and a one-line 'why'."
        ),
        agent=agent,
        output_pydantic=HotelOptions,
    )


def _research_activities_task(agent: Agent) -> Task:
    return Task(
        description=(
            "Suggest activities and experiences in {destination} that match these interests: "
            "{interests}, for a {days}-day trip. Use the Search Activities tool."
        ),
        expected_output=(
            "A list of recommended activities: name, category, duration, and price per person "
            "in {currency}."
        ),
        agent=agent,
    )


def build_crew(step_callback=None, task_callback=None) -> Crew:
    """Build the full autonomous TripWeaver crew (the crew picks flight + hotel).

    Used by the CLI (``backend.main``). ``step_callback`` / ``task_callback`` are
    optional hooks CrewAI invokes during a run (per agent step, and per completed
    task); the AG-UI server passes them to translate live crew activity into AG-UI
    events. Left unset, behavior is identical to Phases 1-2.
    """
    llm = get_llm()
    a = _build_agents(llm)

    research_flights = _research_flights_task(a["flight_researcher"])
    research_hotels = _research_hotels_task(a["hotel_researcher"])
    research_activities = _research_activities_task(a["activities_curator"])

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
        agent=a["itinerary_designer"],
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
        agent=a["budget_auditor"],
        output_pydantic=TripPlan,
    )

    return Crew(
        agents=[
            a["flight_researcher"],
            a["hotel_researcher"],
            a["activities_curator"],
            a["itinerary_designer"],
            a["budget_auditor"],
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
        step_callback=step_callback,
        task_callback=task_callback,
    )


def build_research_crew(step_callback=None, task_callback=None) -> Crew:
    """Phase-1 crew for the human-in-the-loop flow: produce *pickable* options.

    The Flight and Hotel Researchers each emit a ranked list of structured options
    (``FlightOptions`` / ``HotelOptions``). After ``kickoff`` the caller reads the
    two task outputs (``result.tasks_output[i].pydantic``) and presents them to the
    traveler to choose from — the crew deliberately does NOT pick for them here.
    """
    llm = get_llm()
    a = _build_agents(llm)

    return Crew(
        agents=[a["flight_researcher"], a["hotel_researcher"]],
        tasks=[
            _research_flights_task(a["flight_researcher"]),
            _research_hotels_task(a["hotel_researcher"]),
        ],
        process=Process.sequential,
        verbose=True,
        step_callback=step_callback,
        task_callback=task_callback,
    )


def build_planning_crew(step_callback=None, task_callback=None) -> Crew:
    """Phase-2 crew for the human-in-the-loop flow: plan around the human's pick.

    The traveler has already chosen one flight and one hotel; pass them in via
    ``kickoff`` inputs as the ``chosen_flight`` and ``chosen_hotel`` keys (readable
    JSON/text). The Itinerary Designer builds the plan *around* those choices
    (it does not re-pick), and the Budget Auditor emits the final ``TripPlan``.
    """
    llm = get_llm()
    a = _build_agents(llm)

    research_activities = _research_activities_task(a["activities_curator"])

    design_itinerary = Task(
        description=(
            "The traveler has ALREADY chosen their flight and hotel — do not pick different ones.\n"
            "Chosen flight: {chosen_flight}\n"
            "Chosen hotel: {chosen_hotel}\n\n"
            "Using those choices and the activity research, design a day-by-day itinerary for the "
            "{days}-day trip to {destination} for {travelers} traveler(s). Lay out each day with a "
            "morning, afternoon, and evening, and keep a running per-day cost estimate. Respect a "
            "realistic pace (account for the long flight on arrival day)."
        ),
        expected_output=(
            "A clear day-by-day plan (day number, theme, morning/afternoon/evening, per-day cost), "
            "built around the chosen flight and hotel, with a rough running total."
        ),
        context=[research_activities],
        agent=a["itinerary_designer"],
    )

    audit_budget = Task(
        description=(
            "Review the proposed itinerary against the budget of {budget} {currency} for "
            "{travelers} traveler(s). The traveler's chosen flight and hotel are:\n"
            "Flight: {chosen_flight}\n"
            "Hotel: {chosen_hotel}\n\n"
            "Sum all costs: flights (per person x travelers) + hotel (per night x nights) + "
            "activities (per person x travelers). Decide whether the trip is within budget. If it "
            "is over, suggest specific, concrete cuts. Then produce the final structured trip plan, "
            "using the chosen flight and hotel as selected_flight and selected_hotel."
        ),
        expected_output=(
            "A single JSON object for the final TripPlan, with ALL of these fields populated "
            "in one response (never a partial object): summary, selected_flight (the chosen "
            "flight), selected_hotel (the chosen hotel), itinerary (one entry per day), currency, "
            "estimated_total (whole party), budget, within_budget, and budget_notes."
        ),
        context=[design_itinerary],
        agent=a["budget_auditor"],
        output_pydantic=TripPlan,
    )

    return Crew(
        agents=[a["activities_curator"], a["itinerary_designer"], a["budget_auditor"]],
        tasks=[research_activities, design_itinerary, audit_budget],
        process=Process.sequential,
        verbose=True,
        step_callback=step_callback,
        task_callback=task_callback,
    )
