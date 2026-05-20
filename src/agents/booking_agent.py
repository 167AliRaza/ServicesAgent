from pydantic import BaseModel, Field
from src.agent_utils import add_log, append_message, last_user_message
from src.db import check_provider_availability, find_confirmed_booking, create_booking
from src.llm import generate_json


class ConfirmationCheckOutput(BaseModel):
    decision: str = Field(description="One of: confirmed, cancelled, alternative_requested, info_requested, new_service_request, unclear.")
    preference: str = Field(description="One of: cheapest, next_best, higher_rating, specific_provider, any_other, none.")
    requested_provider_name: str = Field(description="Provider name requested by the user, otherwise empty.")


YES_WORDS = {"yes", "y", "yeah", "yep", "ok", "okay", "confirm", "confirmed", "book", "sure", "haan", "han", "jee", "ji"}
NO_WORDS = {"no", "n", "nope", "cancel", "reject", "stop", "nah", "nahi", "na"}
ALTERNATIVE_PHRASES = {
    "other provider": "any_other",
    "another provider": "any_other",
    "different provider": "any_other",
    "any other": "any_other",
    "someone else": "any_other",
    "not this": "any_other",
    "not this one": "any_other",
    "cheaper": "cheapest",
    "cheap": "cheapest",
    "low price": "cheapest",
    "lower price": "cheapest",
    "less price": "cheapest",
    "better rating": "higher_rating",
    "higher rating": "higher_rating",
    "best rating": "higher_rating",
    "too costly": "cheapest",
    "too expensive": "cheapest",
    "expensive": "cheapest",
    "budget": "cheapest",
    "sasta": "cheapest",
    "mehnga": "cheapest",
    "affordable": "cheapest",
}
INFO_PHRASES = {
    "how much",
    "price",
    "cost",
    "charges",
    "rating",
    "where",
    "location",
    "what time",
    "available",
    "warranty",
    "tell me more",
}
NEW_SERVICE_PHRASES = {
    "actually i need",
    "instead i need",
    "now i need",
    "i need plumber",
    "i need electrician",
    "i need ac",
}


def _normalize_text(text: str) -> str:
    return " ".join("".join(c.lower() if c.isalnum() else " " for c in text).split())


def _detect_preference(normalized_text: str) -> str:
    for phrase, preference in ALTERNATIVE_PHRASES.items():
        if phrase in normalized_text:
            return preference
    return "none"


def _detect_specific_provider(normalized_text: str, providers: list[dict]) -> str:
    first_name_matches = []
    for provider in providers:
        name = str(provider.get("name", ""))
        normalized_name = _normalize_text(name)
        if normalized_name and normalized_name in normalized_text:
            return name
        first_token = normalized_name.split()[0] if normalized_name else ""
        if first_token and first_token in normalized_text.split():
            first_name_matches.append(name)
    return first_name_matches[0] if len(first_name_matches) == 1 else ""


def _provider_info_message(state: dict) -> str:
    provider = state.get("selected_provider") or {}
    parsed_intent = state.get("parsed_intent") or {}
    if not provider:
        return "I do not have a selected provider yet."

    parts = [
        f"{provider.get('name')} charges {provider.get('base_price')} PKR",
        f"has rating {provider.get('rating')}",
        f"and serves {provider.get('location')}",
    ]
    if parsed_intent.get("time"):
        parts.append(f"for your requested time: {parsed_intent['time']}")
    return " ".join(parts) + "."


def _deterministic_confirmation(text: str, providers: list[dict]) -> dict:
    normalized_text = _normalize_text(text)
    words = set(normalized_text.split())

    if any(phrase in normalized_text for phrase in NEW_SERVICE_PHRASES):
        return {"decision": "new_service_request", "preference": "none", "requested_provider_name": ""}

    requested_provider_name = _detect_specific_provider(normalized_text, providers)
    if requested_provider_name:
        return {"decision": "alternative_requested", "preference": "specific_provider", "requested_provider_name": requested_provider_name}

    preference = _detect_preference(normalized_text)
    if preference != "none":
        return {"decision": "alternative_requested", "preference": preference, "requested_provider_name": ""}

    if any(phrase in normalized_text for phrase in INFO_PHRASES):
        return {"decision": "info_requested", "preference": "none", "requested_provider_name": ""}

    if words & NO_WORDS:
        return {"decision": "cancelled", "preference": "none", "requested_provider_name": ""}
    if words & YES_WORDS:
        return {"decision": "confirmed", "preference": "none", "requested_provider_name": ""}
    return {"decision": "unclear", "preference": "none", "requested_provider_name": ""}


async def simulate_booking(state: dict) -> dict:
    selected_provider = state.get("selected_provider")
    discovered_providers = state.get("discovered_providers", [])
    parsed_intent = state.get("parsed_intent", {})
    messages = state.get("messages", [])
    user_id = state.get("user_id", "anonymous")

    ans = last_user_message(messages)
    classification = _deterministic_confirmation(ans, discovered_providers)
    if ans:
        provider_names = ", ".join(str(p.get("name", "")) for p in discovered_providers)
        prompt = f"""
        Classify the user's latest reply to a booking confirmation question.
        Reply with JSON only. Use:
        - confirmed: the user clearly wants the proposed provider booked
        - cancelled: the user wants to stop or says no without asking for another provider
        - alternative_requested: the user still wants service but asks for another, cheaper, better-rated, or specific provider
        - info_requested: the user asks about price, time, rating, warranty, provider details, or availability
        - new_service_request: the user changes to a different service or location
        - unclear: anything else

        Also return preference:
        - cheapest: cheaper, low price, lower price
        - higher_rating: better rating, higher rating
        - specific_provider: user asks for a provider by name
        - any_other: another provider, different provider, not this one
        - next_best: general alternative with no specific preference
        - none: no provider preference
        Return requested_provider_name only when the user requested one of these providers: {provider_names}

        User reply: "{ans}"
        """
        parsed = generate_json(prompt, ConfirmationCheckOutput, classification)
        decision = parsed.get("decision", classification["decision"])
        preference = parsed.get("preference", classification["preference"])
        requested_provider_name = parsed.get("requested_provider_name", classification.get("requested_provider_name", ""))
    else:
        decision = classification["decision"]
        preference = classification["preference"]
        requested_provider_name = classification.get("requested_provider_name", "")

    if decision == "rejected":
        decision = "cancelled"
    if decision not in {"confirmed", "cancelled", "alternative_requested", "info_requested", "new_service_request", "unclear"}:
        decision = "unclear"
    if preference not in {"cheapest", "next_best", "higher_rating", "specific_provider", "any_other", "none"}:
        preference = "none"
    if decision == "alternative_requested" and preference == "none":
        preference = "next_best"

    logs = add_log(state, f"BookingAgent: Confirmation decision -> {decision}, preference -> {preference}")

    if decision == "cancelled":
        msg = "No problem, I will not book this provider."
        return {
            "booking_status": "Failed: Cancelled by user",
            "confirmation_status": "cancelled",
            "provider_preference": "none",
            "requested_provider_name": "",
            "confirmation_prompt_override": "",
            "messages": append_message(state, "assistant", msg),
            "logs": [*logs, "BookingAgent: User cancelled the booking."],
        }

    if decision == "new_service_request":
        return {
            "booking_status": "",
            "confirmation_status": "new_service_request",
            "provider_preference": "none",
            "requested_provider_name": "",
            "confirmation_prompt_override": "",
            "discovered_providers": [],
            "selected_provider": None,
            "shown_provider_ids": [],
            "logs": [*logs, "BookingAgent: User changed the service request."],
        }

    if decision == "alternative_requested":
        return {
            "booking_status": "Pending: Alternative provider requested",
            "confirmation_status": "alternative_requested",
            "provider_preference": preference,
            "requested_provider_name": requested_provider_name,
            "confirmation_prompt_override": "",
            "logs": [*logs, "BookingAgent: User requested an alternative provider."],
        }

    if decision == "info_requested":
        info = _provider_info_message(state)
        return {
            "booking_status": "Pending: Confirmation required",
            "confirmation_status": "unclear",
            "provider_preference": "none",
            "requested_provider_name": "",
            "confirmation_prompt_override": f"{info} Do you want me to book this, show another provider, or cancel?",
            "logs": [*logs, "BookingAgent: User requested provider information."],
        }

    if decision == "unclear":
        return {
            "booking_status": "Pending: Confirmation required",
            "confirmation_status": "unclear",
            "provider_preference": "none",
            "requested_provider_name": "",
            "confirmation_prompt_override": "I can book this provider, show a cheaper option, show another provider, or cancel. What would you like me to do?",
            "logs": [*logs, "BookingAgent: Confirmation unclear. Asking again."],
        }

    if not selected_provider:
        return {
            "booking_status": "Failed: No provider selected",
            "confirmation_status": "failed",
            "provider_preference": "none",
            "requested_provider_name": "",
            "confirmation_prompt_override": "",
            "logs": [*logs, "BookingAgent: No provider selected. Skipping booking."],
        }

    time_slot = parsed_intent.get("time", "ASAP")
    logs = [*logs, f"BookingAgent: Simulating booking for user '{user_id}' with {selected_provider['name']} at {time_slot}"]

    provider_available = await check_provider_availability(selected_provider["id"])
    if not provider_available:
        return {
            "booking_status": "Pending: Provider unavailable",
            "confirmation_status": "alternative_requested",
            "provider_preference": "next_best",
            "requested_provider_name": "",
            "confirmation_prompt_override": f"{selected_provider['name']} is no longer available. I can show another provider or cancel.",
            "logs": [*logs, "BookingAgent: Provider unavailable at booking time."],
        }

    existing = await find_confirmed_booking(selected_provider["id"], user_id, time_slot)
    if existing:
        status = f"Slot already booked for {time_slot} with {selected_provider['name']}. Confirmation sent."
        return {
            "booking_status": status,
            "confirmation_status": "confirmed",
            "provider_preference": "none",
            "requested_provider_name": "",
            "confirmation_prompt_override": "",
            "booking_id": existing.get("id"),
            "messages": append_message(state, "assistant", status),
            "logs": [*logs, "BookingAgent: Existing confirmed booking reused."],
        }

    booking_id = await create_booking(selected_provider["id"], user_id, time_slot, "CONFIRMED")

    status = f"Slot booked for {time_slot} with {selected_provider['name']}. Confirmation sent."
    return {
        "booking_status": status,
        "confirmation_status": "confirmed",
        "provider_preference": "none",
        "requested_provider_name": "",
        "confirmation_prompt_override": "",
        "booking_id": booking_id,
        "messages": append_message(state, "assistant", status),
        "logs": [*logs, "BookingAgent: Booking confirmed."],
    }
