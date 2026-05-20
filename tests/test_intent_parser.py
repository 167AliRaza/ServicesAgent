import os
import re
import unittest
from unittest.mock import patch

from src.agents.intent_agent import parse_intent


class MockResponse:
    def __init__(self, text: str):
        self.text = text


class MockModels:
    def generate_content(self, model, contents, config=None):
        text = str(contents).lower()
        user_match = re.search(r"user:\s*(.*)", text)
        user_text = user_match.group(1) if user_match else text
        if "plumber" in user_text:
            return MockResponse('{"service_type": "Plumber", "location": "", "time": "ASAP"}')
        if "electrician" in user_text:
            return MockResponse('{"service_type": "Electrician", "location": "", "time": "ASAP"}')
        if re.search(r"\\bac\\b|ac repair|ac technician|technition", user_text):
            return MockResponse('{"service_type": "AC Technician", "location": "", "time": "ASAP"}')
        return MockResponse('{"service_type": "", "location": "", "time": "ASAP"}')


class MockGenaiClient:
    def __init__(self, api_key=None):
        self.models = MockModels()


class IntentParserTests(unittest.TestCase):
    def setUp(self):
        self.old_key = os.environ.get("GEMINI_API_KEY")
        os.environ["GEMINI_API_KEY"] = "test-key"

    def tearDown(self):
        if self.old_key is None:
            os.environ.pop("GEMINI_API_KEY", None)
        else:
            os.environ["GEMINI_API_KEY"] = self.old_key

    def parse(self, text: str) -> dict:
        state = {"messages": [{"role": "user", "content": text}], "logs": []}
        return parse_intent(state)["parsed_intent"]

    @patch("google.genai.Client", MockGenaiClient)
    def test_extracts_city_location_for_known_service(self):
        parsed = self.parse("ac technition in lahore")
        self.assertEqual(parsed["service_type"], "AC Technician")
        self.assertEqual(parsed["location"], "Lahore")

    @patch("google.genai.Client", MockGenaiClient)
    def test_extracts_generic_service_and_city_location(self):
        parsed = self.parse("car wash in lahore")
        self.assertEqual(parsed["service_type"], "Car Wash")
        self.assertEqual(parsed["location"], "Lahore")

    @patch("google.genai.Client", MockGenaiClient)
    def test_extracts_generic_service_and_area_location(self):
        parsed = self.parse("home cleaning near model town tomorrow")
        self.assertEqual(parsed["service_type"], "Home Cleaning")
        self.assertEqual(parsed["location"], "Model Town")

    @patch("google.genai.Client", MockGenaiClient)
    def test_keeps_sector_location_format(self):
        parsed = self.parse("Need AC repair in g13")
        self.assertEqual(parsed["service_type"], "AC Technician")
        self.assertEqual(parsed["location"], "G-13")

    @patch("google.genai.Client", MockGenaiClient)
    def test_does_not_turn_greeting_into_service(self):
        parsed = self.parse("hello")
        self.assertEqual(parsed["service_type"], "")
        self.assertEqual(parsed["location"], "")

    @patch("google.genai.Client", MockGenaiClient)
    def test_extracts_price_rating_and_sort_filters(self):
        parsed = self.parse("cheap plumber in model town under 1500 rating above 4.5")
        self.assertEqual(parsed["service_type"], "Plumber")
        self.assertEqual(parsed["location"], "Model Town")
        self.assertEqual(parsed["filters"]["max_price"], 1500.0)
        self.assertEqual(parsed["filters"]["min_rating"], 4.5)
        self.assertEqual(parsed["filters"]["sort_by"], "cheapest")

    @patch("google.genai.Client", MockGenaiClient)
    def test_extracts_highest_rated_sort_filter(self):
        parsed = self.parse("best rated electrician in lahore")
        self.assertEqual(parsed["service_type"], "Electrician")
        self.assertEqual(parsed["location"], "Lahore")
        self.assertEqual(parsed["filters"]["sort_by"], "rating")

    @patch("google.genai.Client", MockGenaiClient)
    def test_extracts_distance_filter(self):
        parsed = self.parse("electrician in lahore within 10 km")
        self.assertEqual(parsed["service_type"], "Electrician")
        self.assertEqual(parsed["location"], "Lahore")
        self.assertEqual(parsed["filters"]["max_distance_km"], 10.0)


if __name__ == "__main__":
    unittest.main()
