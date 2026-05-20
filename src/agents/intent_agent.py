import re
from typing import Any

from pydantic import BaseModel, Field

from src.agent_utils import add_log, message_content, message_role
from src.db import get_distinct_service_types
from src.llm import generate_json

# Module-level cache populated at app startup
_valid_services: list[str] = []
_SERVICE_ALIASES = {
    "AC Technician": ("ac", "a/c", "air conditioner", "air conditioning", "cooling"),
    "Plumber": ("plumber", "plumbing", "pipe", "leak", "water tap", "drain"),
    "Electrician": ("electrician", "electric", "bijli", "wiring", "switch", "fan"),
}
_LOCATION_RE = re.compile(r"\b([a-zA-Z])\s*-?\s*(\d{1,2})\b")
_LOCATION_PHRASE_RE = re.compile(
    r"\b(?:in|at|near|around|from)\s+([a-zA-Z][a-zA-Z\s-]{1,40}?)(?=\s+(?:today|tomorrow|tonight|morning|evening|afternoon|asap|now|please|for|to|with|and|on|by|after|before|under|below|less|maximum|max|upto|up|within|budget|around|rating|rated|stars?)\b|[.,!?]|$)",
    re.IGNORECASE,
)
_LOCATION_STOPWORDS = {
    "a",
    "an",
    "the",
    "service",
    "provider",
    "technician",
    "repair",
    "please",
    "asap",
    "now",
    "today",
    "tomorrow",
}
_REQUEST_PREFIX_RE = re.compile(
    r"^(?:please\s+)?(?:i\s+)?(?:am\s+)?(?:need|want|book|find|get|send|hire|require|looking\s+for|searching\s+for|can\s+you\s+find|can\s+you\s+book)\s+",
    re.IGNORECASE,
)
_SERVICE_BOUNDARY_RE = re.compile(
    r"\b(?:in|at|near|around|from|today|tomorrow|tonight|morning|evening|afternoon|asap|now|please|for|with|on|by|after|before)\b",
    re.IGNORECASE,
)
_SERVICE_FILLER_RE = re.compile(r"^(?:a|an|the)\s+|\s+(?:a|an|the)$", re.IGNORECASE)
_PRICE_RE = re.compile(
    r"\b(?:under|below|less than|less then|maximum|max|upto|up to|within|budget(?: is)?|around)\s+(?:rs\.?|pkr)?\s*(\d+(?:,\d{3})*(?:\.\d+)?)\b|\b(?:rs\.?|pkr)\s*(\d+(?:,\d{3})*(?:\.\d+)?)\s*(?:or less|max|maximum)?\b",
    re.IGNORECASE,
)
_RATING_RE = re.compile(
    r"\b(?:rating|rated|stars?)\s*(?:above|over|more than|greater than|at least|minimum|min)?\s*(\d(?:\.\d)?)\b|\b(\d(?:\.\d)?)\s*(?:\+|or above|or more)\s*(?:rating|rated|stars?)\b",
    re.IGNORECASE,
)
_DISTANCE_RE = re.compile(
    r"\b(?:within|under|inside|nearby within)\s+(\d+(?:\.\d+)?)\s*(?:km|kilometers?|kms?)\b",
    re.IGNORECASE,
)
_CHEAP_RE = re.compile(r"\b(?:cheap|cheapest|low price|lowest price|affordable|budget)\b", re.IGNORECASE)
_RATING_SORT_RE = re.compile(r"\b(?:best|best rated|highest rated|top rated|high rating|better rating)\b", re.IGNORECASE)

class IntentOutput(BaseModel):
    service_type: str = Field(description="The service requested by the user. Prefer a canonical service type when it matches the catalog; otherwise keep the user's requested service.")
    location: str = Field(description="The location specified by the user. Empty if not mentioned.")
    time: str = Field(description="The scheduled time for the service request. Default to 'ASAP' if not specified.")
    filters: dict[str, Any] = Field(default_factory=dict, description="Optional search filters such as max_price, min_rating, and sort_by.")

async def load_valid_services():
    """Call once at startup to cache valid service types from DB."""
    global _valid_services
    _valid_services = await get_distinct_service_types()


def _user_text(messages: list[dict]) -> str:
    return "\n".join(
        message_content(m)
        for m in messages
        if message_role(m) in ("user", "human")
    )


def _latest_user_text(messages: list[dict]) -> str:
    for message in reversed(messages):
        if message_role(message) in ("user", "human"):
            return message_content(message)
    return ""


def _extract_location(text: str) -> str:
    matches = _LOCATION_RE.findall(text)
    if matches:
        letter, number = matches[-1]
        return f"{letter.upper()}-{number}"

    phrase_matches = _LOCATION_PHRASE_RE.findall(text)
    for phrase in reversed(phrase_matches):
        words = [
            word.strip("-").lower()
            for word in phrase.split()
            if word.strip("-").lower() not in _LOCATION_STOPWORDS
        ]
        if words:
            return " ".join(words).title()

    return ""


def _clean_requested_service(candidate: str) -> str:
    candidate = candidate.strip().strip(" -/.,!?")
    candidate = _REQUEST_PREFIX_RE.sub("", candidate)
    candidate = _SERVICE_FILLER_RE.sub("", candidate)
    candidate = " ".join(candidate.split()).strip(" -/.,!?")

    ignored = {
        "hi",
        "hello",
        "there",
        "who are you",
        "i am",
        "i need",
        "need",
        "want",
        "book",
    }
    if not candidate or candidate in ignored or not re.search(r"[a-z]", candidate):
        return ""
    if len(candidate) < 2 or len(candidate) > 60:
        return ""
    return candidate.title()


def _canonical_service(text: str) -> str:
    lowered = text.lower()
    valid_services = _valid_services or ["AC Technician", "Plumber", "Electrician"]
    for service in valid_services:
        service_terms = [service.lower(), *_SERVICE_ALIASES.get(service, ())]
        for term in service_terms:
            if len(term) <= 2:
                if re.search(rf"\b{re.escape(term)}\b", lowered):
                    return service
            elif term in lowered:
                return service
    return ""


def _requested_service(text: str) -> str:
    lowered = text.lower()
    patterns = (
        r"\b(?:find|need|want|book|looking for|get me|send)\s+(?:a|an)?\s*([a-z][a-z\s/-]{1,40}?)(?:\s+(?:service|provider|technician|repair|in|at|near)\b|$)",
        r"\b([a-z][a-z\s/-]{1,40}?)\s+(?:service|provider|technician|repair)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, lowered)
        if not match:
            continue
        service = _clean_requested_service(match.group(1))
        if service:
            return service

    boundary = _SERVICE_BOUNDARY_RE.search(lowered)
    candidate = lowered[: boundary.start()] if boundary else lowered
    return _clean_requested_service(candidate)


def _first_number(match: re.Match) -> str:
    for group in match.groups():
        if group:
            return group
    return ""


def _extract_filters(text: str, parsed_filters: dict | None = None) -> dict[str, Any]:
    filters: dict[str, Any] = {}
    if isinstance(parsed_filters, dict):
        filters.update({k: v for k, v in parsed_filters.items() if v not in ("", None)})

    price_match = _PRICE_RE.search(text)
    if price_match:
        price = _first_number(price_match).replace(",", "")
        try:
            filters["max_price"] = float(price)
        except ValueError:
            pass

    rating_match = _RATING_RE.search(text)
    if rating_match:
        try:
            rating = float(_first_number(rating_match))
            if 0 <= rating <= 5:
                filters["min_rating"] = rating
        except ValueError:
            pass

    distance_match = _DISTANCE_RE.search(text)
    if distance_match:
        try:
            filters["max_distance_km"] = float(distance_match.group(1))
        except ValueError:
            pass

    if _CHEAP_RE.search(text):
        filters["sort_by"] = "cheapest"
    elif _RATING_SORT_RE.search(text):
        filters["sort_by"] = "rating"

    return filters


def _normalize_parsed_intent(parsed: dict, messages: list[dict]) -> dict:
    text = _user_text(messages)
    latest_text = _latest_user_text(messages)
    valid_services = set(_valid_services or ["AC Technician", "Plumber", "Electrician"])

    service_type = parsed.get("service_type") or ""
    latest_service = _canonical_service(latest_text) or _requested_service(latest_text)
    if latest_service:
        service_type = latest_service
    elif service_type not in valid_services:
        service_type = _canonical_service(text) or service_type or _requested_service(text)

    location = _extract_location(latest_text) or parsed.get("location") or _extract_location(text)
    location_match = _extract_location(location)
    if location_match:
        location = location_match

    filters = _extract_filters(latest_text or text, parsed.get("filters"))

    return {
        "service_type": service_type,
        "location": location,
        "time": parsed.get("time") or "ASAP",
        "filters": filters,
    }

def parse_intent(state: dict) -> dict:
    messages = state.get("messages", [])

    valid_services_str = ", ".join(f'"{s}"' for s in _valid_services) if _valid_services else '"AC Technician", "Plumber", "Electrician"'

    chat_history = "".join(
        f"{message_role(m).capitalize()}: {message_content(m)}\n" for m in messages
    )

    logs = add_log(state, "IntentAgent: Understanding user requirements...")

    prompt = f"""
    You are an expert at parsing service requests in English, Urdu, and Roman Urdu.
    Prioritize the latest user message when it changes or corrects earlier service details.
    Extract the following information from the conversation history:
    - service_type (If the user asks for any service, always extract it. If it matches one of {valid_services_str}, use that exact canonical value. If it is outside the catalog, keep the user's requested service, e.g. "Milk Provider", "Car Wash", "Home Cleaning". If the user is not asking for any service, set to "")
    - location (Extract any city, area, neighborhood, sector, or locality, e.g., "G-13", "F-8", "Lahore", "Gulberg", "Model Town". If not mentioned, set to "")
    - time (e.g., "Tomorrow morning", "10:00 AM". Default to "ASAP" if not specified)
    - filters (Optional object. Extract max_price for "under 1500" or "budget 2000", min_rating for "rating above 4.5", max_distance_km for "within 10 km", and sort_by as "cheapest" for cheap/budget requests or "rating" for best/highest-rated requests.)

    If the user has not provided a specific service_type or location yet, set the value to "".

    Conversation History:
    {chat_history}
    """

    parsed_intent = generate_json(
        prompt,
        IntentOutput,
        {"service_type": "", "location": "", "time": "ASAP", "filters": {}},
    )
    parsed_intent = _normalize_parsed_intent(parsed_intent, messages)
    logs = [*logs, f"IntentAgent: Parsed intent -> {parsed_intent}"]

    return {"parsed_intent": parsed_intent, "logs": logs}
