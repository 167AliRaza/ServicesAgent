import asyncio
import unittest
from unittest.mock import patch

from src.agents.discovery_agent import discover_providers


TEST_PROVIDERS = [
    {"id": 1, "name": "Ali AC Services", "service_type": "AC Technician", "location": "G-13", "lat": 33.6469, "lng": 72.9616, "rating": 4.8, "base_price": 1500.0},
    {"id": 2, "name": "Zain AC Repair", "service_type": "AC Technician", "location": "G-13", "lat": 33.6469, "lng": 72.9616, "rating": 4.2, "base_price": 1200.0},
    {"id": 3, "name": "Bilal Cooling", "service_type": "AC Technician", "location": "F-8", "lat": 33.7104, "lng": 73.0395, "rating": 4.6, "base_price": 1800.0},
    {"id": 4, "name": "Hassan Plumbers", "service_type": "Plumber", "location": "Model Town", "lat": 31.4828, "lng": 74.3239, "rating": 4.5, "base_price": 1000.0},
    {"id": 5, "name": "Tariq Plumb Solutions", "service_type": "Plumber", "location": "Model Town", "lat": 31.4828, "lng": 74.3239, "rating": 4.1, "base_price": 700.0},
    {"id": 6, "name": "Nearby Lahore Electric", "service_type": "Electrician", "location": "Gulberg", "lat": 31.5206, "lng": 74.3499, "rating": 4.1, "base_price": 900.0},
    {"id": 7, "name": "Far Lahore Electric", "service_type": "Electrician", "location": "DHA Lahore", "lat": 31.4626, "lng": 74.4096, "rating": 4.9, "base_price": 1100.0},
]


async def mock_active_providers():
    return TEST_PROVIDERS


class DiscoveryAgentTests(unittest.TestCase):
    def discover(self, parsed_intent: dict) -> list[dict]:
        async def run():
            with patch("src.agents.discovery_agent.get_active_providers", mock_active_providers):
                result = await discover_providers({"parsed_intent": parsed_intent, "logs": []})
                return result["discovered_providers"]

        return asyncio.run(run())

    def test_fuzzy_service_typo_and_location_match(self):
        providers = self.discover({"service_type": "plubmer", "location": "modeltown", "filters": {}})
        self.assertEqual([p["name"] for p in providers], ["Hassan Plumbers", "Tariq Plumb Solutions"])

    def test_max_price_filter_and_cheapest_sort(self):
        providers = self.discover(
            {
                "service_type": "AC Technician",
                "location": "G-13",
                "filters": {"max_price": 1300, "sort_by": "cheapest"},
            }
        )
        self.assertEqual([p["name"] for p in providers], ["Zain AC Repair"])

    def test_min_rating_filter(self):
        providers = self.discover(
            {
                "service_type": "AC Technician",
                "location": "G-13",
                "filters": {"min_rating": 4.5, "sort_by": "rating"},
            }
        )
        self.assertEqual([p["name"] for p in providers], ["Ali AC Services"])

    def test_service_synonym_matches_provider_category(self):
        providers = self.discover({"service_type": "leaky pipe", "location": "Model Town", "filters": {}})
        self.assertEqual([p["service_type"] for p in providers], ["Plumber", "Plumber"])

    def test_nearby_providers_are_ranked_by_distance_before_rating(self):
        providers = self.discover({"service_type": "Electrician", "location": "Lahore", "filters": {"max_distance_km": 15}})
        self.assertEqual([p["name"] for p in providers], ["Nearby Lahore Electric", "Far Lahore Electric"])
        self.assertIn("distance_km", providers[0])

    def test_distance_radius_filters_far_providers(self):
        providers = self.discover({"service_type": "Electrician", "location": "Lahore", "filters": {"max_distance_km": 4}})
        self.assertEqual([p["name"] for p in providers], ["Nearby Lahore Electric"])


if __name__ == "__main__":
    unittest.main()
