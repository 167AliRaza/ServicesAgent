from difflib import SequenceMatcher

from src.agent_utils import add_log
from src.db import get_active_providers
from src.geocoding import geocode_location, haversine_km, provider_coordinates

SERVICE_ALIASES = {
    "AC Technician": ("ac", "a/c", "air conditioner", "air conditioning", "cooling", "ac repair"),
    "Plumber": ("plumber", "plumbing", "pipe", "leak", "leaky pipe", "water tap", "drain"),
    "Electrician": ("electrician", "electrical", "electrical repair", "bijli", "wiring", "switch", "fan"),
}
DEFAULT_RADIUS_KM = 6.0

def normalize_string(val: str) -> str:
    # Remove hyphens, spaces, and lowercase the string for highly robust comparisons
    if not val:
        return ""
    return "".join(c for c in val if c.isalnum()).lower()


def similarity(left: str, right: str) -> float:
    left_norm = normalize_string(left)
    right_norm = normalize_string(right)
    if not left_norm or not right_norm:
        return 0.0
    if left_norm == right_norm:
        return 1.0
    if left_norm in right_norm or right_norm in left_norm:
        return 0.9
    return SequenceMatcher(None, left_norm, right_norm).ratio()


def service_matches(query: str, provider_service: str) -> bool:
    terms = (provider_service, *SERVICE_ALIASES.get(provider_service, ()))
    return any(similarity(query, term) >= 0.74 for term in terms)


def location_score(query: str, provider_location: str) -> float:
    score = similarity(query, provider_location)
    if score >= 0.82:
        return score
    return 0.0


def distance_for(query_coordinates: tuple[float, float] | None, provider: dict) -> float | None:
    if query_coordinates is None:
        return None
    coordinates = provider_coordinates(provider)
    if coordinates is None:
        return None
    return round(haversine_km(query_coordinates, coordinates), 2)


def passes_filters(provider: dict, filters: dict) -> bool:
    max_price = filters.get("max_price")
    if max_price not in (None, "") and float(provider.get("base_price", 0)) > float(max_price):
        return False

    min_rating = filters.get("min_rating")
    if min_rating not in (None, "") and float(provider.get("rating", 0)) < float(min_rating):
        return False

    return True


def sort_key(provider: dict, sort_by: str):
    rating = float(provider.get("rating", 0))
    price = float(provider.get("base_price", 0))
    if sort_by == "cheapest":
        return (price, -rating)
    return (-rating, price)


async def discover_providers(state: dict) -> dict:
    parsed_intent = state.get("parsed_intent", {})

    service_type = parsed_intent.get("service_type", "")
    location = parsed_intent.get("location", "")
    filters = parsed_intent.get("filters") or {}
    sort_by = filters.get("sort_by") or "rating"
    try:
        radius_km = float(filters.get("max_distance_km") or DEFAULT_RADIUS_KM)
    except (TypeError, ValueError):
        radius_km = DEFAULT_RADIUS_KM
    user_coordinates = geocode_location(location)

    logs = add_log(state, f"DiscoveryAgent: Searching for '{service_type}' in '{location}'")

    rows = await get_active_providers()

    matches = []
    for p in rows:
        if not service_matches(service_type, p["service_type"]) or not passes_filters(p, filters):
            continue

        distance_km = distance_for(user_coordinates, p)
        if distance_km is not None:
            if distance_km <= radius_km:
                provider = {**p, "distance_km": distance_km}
                matches.append((1.0, distance_km, provider))
            continue

        score = location_score(location, p["location"])
        if score:
            matches.append((score, None, p))

    providers = [
        p
        for _, _, p in sorted(
            matches,
            key=lambda item: (
                item[1] if item[1] is not None else 9999.0,
                -item[0],
                *sort_key(item[2], sort_by),
            ),
        )[:5]
    ]

    logs = [*logs, f"DiscoveryAgent: Found {len(providers)} providers"]
    return {"discovered_providers": providers, "logs": logs}
