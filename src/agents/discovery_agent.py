from src.agent_utils import add_log
from src.db import get_active_providers

def normalize_string(val: str) -> str:
    # Remove hyphens, spaces, and lowercase the string for highly robust comparisons
    if not val:
        return ""
    return "".join(c for c in val if c.isalnum()).lower()

async def discover_providers(state: dict) -> dict:
    parsed_intent = state.get("parsed_intent", {})

    service_type = parsed_intent.get("service_type", "")
    location = parsed_intent.get("location", "")

    logs = add_log(state, f"DiscoveryAgent: Searching for '{service_type}' in '{location}'")

    rows = await get_active_providers()

    norm_service = normalize_string(service_type)
    norm_location = normalize_string(location)

    exact_location_matches = []
    partial_location_matches = []
    for p in rows:
        db_service = normalize_string(p["service_type"])
        db_location = normalize_string(p["location"])
        service_matches = norm_service == db_service or norm_service in db_service or db_service in norm_service
        location_exact = norm_location == db_location
        location_partial = norm_location in db_location or db_location in norm_location

        if service_matches and (location_exact or location_partial):
            if location_exact:
                exact_location_matches.append(p)
            else:
                partial_location_matches.append(p)

    providers = exact_location_matches or partial_location_matches
    providers = sorted(providers, key=lambda p: (-float(p["rating"]), float(p["base_price"])))[:5]

    logs = [*logs, f"DiscoveryAgent: Found {len(providers)} providers"]
    return {"discovered_providers": providers, "logs": logs}
