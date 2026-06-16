"""Entry point: run the TripWeaver crew on a sample request.

Usage:
    cp .env.example .env          # then add your ANTHROPIC_API_KEY
    uv run python -m backend.main
    # or, with the venv active:  python -m backend.main
"""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv

from .crew import build_crew
from .models import TripPlan

# A sample request. Edit these, or wire them to real user input later.
SAMPLE_REQUEST = {
    "origin": "Athens",
    "destination": "Tokyo",
    "start_date": "2026-10-05",
    "days": 8,
    "travelers": 2,
    "budget": 6000,
    "currency": "EUR",
    "interests": "food and hiking",
}


def pretty_print(plan: TripPlan) -> None:
    print("\n" + "=" * 70)
    print("  TRIPWEAVER — PROPOSED PLAN")
    print("=" * 70)
    print(f"\n{plan.summary}\n")
    f = plan.selected_flight
    print(f"Flight : {f.airline} — {f.stops} stop(s), {f.duration_hours}h, "
          f"{f.price_per_person} {plan.currency}/person")
    print(f"         {f.why}")
    h = plan.selected_hotel
    print(f"Hotel  : {h.name} ({h.area}) — {h.price_per_night} {plan.currency}/night "
          f"x {h.nights} nights")
    print(f"         {h.why}\n")
    for d in plan.itinerary:
        print(f"  Day {d.day} — {d.title}  (~{d.estimated_cost} {plan.currency}/person)")
        print(f"     AM: {d.morning}")
        print(f"     PM: {d.afternoon}")
        print(f"     EVE: {d.evening}")
    verdict = "WITHIN BUDGET" if plan.within_budget else "OVER BUDGET"
    print(f"\nEstimated total (party): {plan.estimated_total} {plan.currency}  "
          f"| Budget: {plan.budget} {plan.currency}  -> {verdict}")
    print(f"Notes: {plan.budget_notes}")
    print("=" * 70 + "\n")


def main() -> None:
    load_dotenv()
    if not os.getenv("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key.")

    crew = build_crew()
    result = crew.kickoff(inputs=SAMPLE_REQUEST)

    # The last task has output_pydantic=TripPlan, so result.pydantic is a TripPlan.
    if result.pydantic is not None:
        pretty_print(result.pydantic)
    else:
        print("\n[Could not parse structured output; raw result below]\n")
        print(result.raw)


if __name__ == "__main__":
    main()
