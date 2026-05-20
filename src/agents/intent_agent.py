import aiosqlite
import re

from pydantic import BaseModel, Field

from src.agent_utils import add_log, message_content, message_role
from src.config import get_db_path
from src.llm import generate_json

# Module-level cache populated at app startup
_valid_services: list[str] = []
_SERVICE_ALIASES = {
    "AC Technician": ("ac", "a/c", "air conditioner", "air conditioning", "cooling"),
    "Plumber": ("plumber", "plumbing", "pipe", "leak", "water tap", "drain"),
    "Electrician": ("electrician", "electric", "bijli", "wiring", "switch", "fan"),
}
_LOCATION_RE = re.compile(r"\b([a-zA-Z])\s*-?\s*(\d{1,2})\b")

class IntentOutput(BaseModel):
    service_type: str = Field(description="The service requested by the user. Prefer a canonical service type when it matches the catalog; otherwise keep the user's requested service.")
    location: str = Field(description="The location specified by the user. Empty if not mentioned.")
    time: str = Field(description="The scheduled time for the service request. Default to 'ASAP' if not specified.")

async def load_valid_services():
    """Call once at startup to cache valid service types from DB."""
    global _valid_services
    async with aiosqlite.connect(get_db_path()) as conn:
        cursor = await conn.execute("SELECT DISTINCT service_type FROM providers")
        rows = await cursor.fetchall()
    _valid_services = [r[0] for r in rows]


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
    if not matches:
        return ""
    letter, number = matches[-1]
    return f"{letter.upper()}-{number}"


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
    ignored = {"hi", "hello", "there", "who are you", "i am"}
    for pattern in patterns:
        match = re.search(pattern, lowered)
        if not match:
            continue
        candidate = " ".join(match.group(1).split()).strip(" -/")
        if not candidate or candidate in ignored:
            continue
        return candidate.title()
    return ""


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

    return {
        "service_type": service_type,
        "location": location,
        "time": parsed.get("time") or "ASAP",
    }

def parse_intent(state: dict) -> dict:
    messages = state.get("messages", [])

    valid_services_str = ", ".join(f'"{s}"' for s in _valid_services) if _valid_services else '"AC Technician", "Plumber", "Electrician"'

    chat_history = "".join(
        f"{message_role(m).capitalize()}: {message_content(m)}\n" for m in messages
    )

    logs = add_log(state, "IntentAgent: Parsing intent from history.")

    prompt = f"""
    You are an expert at parsing service requests in English, Urdu, and Roman Urdu.
    Prioritize the latest user message when it changes or corrects earlier service details.
    Extract the following information from the conversation history:
    - service_type (If the user asks for a service, always extract it. If it matches one of {valid_services_str}, use that exact canonical value. If it is a service outside the catalog, keep the user's requested service, e.g. "Milk Provider". If the user is not asking for any service, set to "")
    - location (e.g., "G-13", "F-8". If not mentioned, set to "")
    - time (e.g., "Tomorrow morning", "10:00 AM". Default to "ASAP" if not specified)

    If the user has not provided a specific service_type or location yet, set the value to "".

    Conversation History:
    {chat_history}
    """

    parsed_intent = generate_json(
        prompt,
        IntentOutput,
        {"service_type": "", "location": "", "time": "ASAP"},
    )
    parsed_intent = _normalize_parsed_intent(parsed_intent, messages)
    logs = [*logs, f"IntentAgent: Parsed intent -> {parsed_intent}"]

    return {"parsed_intent": parsed_intent, "logs": logs}
