"""Structured output schema for the final trip plan.

CrewAI can force a task's output into a Pydantic model (``output_pydantic=...``).
We use that on the final task so the crew returns *typed data*, not just prose.

This matters beyond Phase 1: in Phase 4 the A2UI layer renders interactive UI
(flight cards, an itinerary editor) directly from a structured object like this.
A clean schema now is what lets later phases stay declarative.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class FlightChoice(BaseModel):
    airline: str
    stops: int
    duration_hours: float
    price_per_person: float
    why: str = Field(description="One line on why this flight was chosen.")


class HotelChoice(BaseModel):
    name: str
    area: str
    price_per_night: float
    nights: int
    why: str = Field(description="One line on why this hotel was chosen.")


class FlightOption(BaseModel):
    """One flight candidate the traveler can pick from.

    The research crew emits a ranked list of these (``FlightOptions``); the human
    picks one in the UI, and the chosen option is fed into the planning crew.
    """

    ref: str = Field(description="Short stable id for this option, e.g. 'F1'.")
    airline: str
    stops: int
    duration_hours: float
    price_per_person: float
    why: str = Field(description="One line on why this option is worth considering.")


class FlightOptions(BaseModel):
    options: list[FlightOption]


class HotelOption(BaseModel):
    """One hotel candidate the traveler can pick from."""

    ref: str = Field(description="Short stable id for this option, e.g. 'H1'.")
    name: str
    area: str
    price_per_night: float
    why: str = Field(description="One line on why this option is worth considering.")


class HotelOptions(BaseModel):
    options: list[HotelOption]


class ItineraryDay(BaseModel):
    day: int
    title: str = Field(description="Short theme for the day, e.g. 'Arrival & Shibuya'.")
    morning: str
    afternoon: str
    evening: str
    estimated_cost: float = Field(description="Per-person activity/food cost for the day.")


class TripPlan(BaseModel):
    """The final, structured deliverable of the crew."""

    summary: str = Field(description="A 2-3 sentence overview of the trip.")
    selected_flight: FlightChoice
    selected_hotel: HotelChoice
    itinerary: list[ItineraryDay]
    currency: str
    estimated_total: float = Field(
        description="Total estimated cost for the whole party (flights + hotel + activities)."
    )
    budget: float
    within_budget: bool
    budget_notes: str = Field(
        description="How the total compares to budget, and any suggested cuts if over."
    )


class BookingConfirmation(BaseModel):
    """The result of the Booking Coordinator placing the reservations.

    Emitted by the booking crew once the traveler confirms (the final HITL leg),
    and rendered as the booking-confirmation surface.
    """

    code: str = Field(description="Overall confirmation code (combines the flight + hotel refs).")
    flight_status: str = Field(description="Flight reservation status, e.g. 'confirmed'.")
    hotel_status: str = Field(description="Hotel reservation status, e.g. 'confirmed'.")
    total: float = Field(description="Total amount charged for the whole party.")
    currency: str
    message: str = Field(description="A short, friendly confirmation message for the traveler.")
