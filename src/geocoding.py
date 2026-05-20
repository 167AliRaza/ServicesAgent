"""Small deterministic geocoding helpers for provider proximity ranking."""
from __future__ import annotations

from math import asin, cos, radians, sin, sqrt


GAZETTEER = {
    # Islamabad sectors used by the default mock providers.
    "g13": (33.6469, 72.9616),
    "g-13": (33.6469, 72.9616),
    "g10": (33.6762, 73.0149),
    "g-10": (33.6762, 73.0149),
    "f8": (33.7104, 73.0395),
    "f-8": (33.7104, 73.0395),
    "islamabad": (33.6844, 73.0479),
    # Lahore city and common areas.
    "lahore": (31.5204, 74.3587),
    "gulberg": (31.5206, 74.3499),
    "modeltown": (31.4828, 74.3239),
    "model town": (31.4828, 74.3239),
    "dha lahore": (31.4626, 74.4096),
    "johar town": (31.4697, 74.2728),
    "township": (31.4504, 74.3037),
    # Other broad Pakistani city fallbacks.
    "karachi": (24.8607, 67.0011),
    "rawalpindi": (33.5651, 73.0169),
    "faisalabad": (31.4504, 73.1350),
    "multan": (30.1575, 71.5249),
    "peshawar": (34.0151, 71.5249),
}


def normalize_place(value: str) -> str:
    return " ".join(str(value or "").strip().lower().replace("-", "").split())


def geocode_location(value: str) -> tuple[float, float] | None:
    """Return coordinates for a known city/area/sector, if available."""
    if not value:
        return None

    normalized = normalize_place(value)
    compact = normalized.replace(" ", "")
    return GAZETTEER.get(normalized) or GAZETTEER.get(compact)


def provider_coordinates(provider: dict) -> tuple[float, float] | None:
    """Read coordinates from a provider document or infer them from location text."""
    lat = provider.get("lat")
    lng = provider.get("lng")
    if lat is None:
        lat = provider.get("latitude")
    if lng is None:
        lng = provider.get("longitude")
    if lat is not None and lng is not None:
        try:
            return float(lat), float(lng)
        except (TypeError, ValueError):
            pass
    return geocode_location(str(provider.get("location", "")))


def haversine_km(left: tuple[float, float], right: tuple[float, float]) -> float:
    """Calculate great-circle distance between two lat/lng pairs."""
    lat1, lon1 = left
    lat2, lon2 = right
    radius_km = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * radius_km * asin(sqrt(a))
