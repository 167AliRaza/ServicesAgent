import asyncio
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import motor.motor_asyncio
from langgraph.checkpoint.mongodb import MongoDBSaver

import src.db as db_module
from src.agents.booking_agent import simulate_booking
from src.agents.discovery_agent import discover_providers
from src.agents.intent_agent import load_valid_services, parse_intent
from src.agents.ranking_agent import rank_providers
from src.db import close_mongodb, init_mongodb, migrate_database_schema
from src.workflow import create_workflow


TEST_PROVIDERS = [
    {"id": 1, "name": "Ali AC Services", "service_type": "AC Technician", "location": "G-13", "rating": 4.8, "base_price": 1500.0, "available": True},
    {"id": 2, "name": "Zain AC Repair", "service_type": "AC Technician", "location": "G-13", "rating": 4.8, "base_price": 1200.0, "available": True},
    {"id": 3, "name": "Bilal Cooling", "service_type": "AC Technician", "location": "F-8", "rating": 4.6, "base_price": 1800.0, "available": True},
    {"id": 4, "name": "Raza Electricians", "service_type": "Electrician", "location": "G-13", "rating": 4.7, "base_price": 1200.0, "available": True},
    {"id": 5, "name": "Hassan Plumbers", "service_type": "Plumber", "location": "G-13", "rating": 4.5, "base_price": 1000.0, "available": True},
]


class MockResponse:
    def __init__(self, text: str):
        self.text = text


class MockModels:
    def generate_content(self, model, contents, config=None):
        text = str(contents).lower()
        if "classify the user's latest reply" in text:
            reply_match = re.search(r'user reply:\s*"([^"]*)"', text)
            reply = reply_match.group(1) if reply_match else text
            if "actually i need" in reply or "instead i need" in reply:
                return MockResponse('{"decision": "new_service_request", "preference": "none", "requested_provider_name": ""}')
            if "what time" in reply or "how much" in reply or "price" in reply:
                return MockResponse('{"decision": "info_requested", "preference": "none", "requested_provider_name": ""}')
            if "ali" in reply:
                return MockResponse('{"decision": "alternative_requested", "preference": "specific_provider", "requested_provider_name": "Ali AC Services"}')
            if "cheaper" in reply or "low price" in reply or "lower price" in reply:
                return MockResponse('{"decision": "alternative_requested", "preference": "cheapest", "requested_provider_name": ""}')
            if "other provider" in reply or "another provider" in reply or "not this one" in reply:
                return MockResponse('{"decision": "alternative_requested", "preference": "any_other", "requested_provider_name": ""}')
            if reply.startswith("yes") or reply.startswith("confirm"):
                return MockResponse('{"decision": "confirmed", "preference": "none", "requested_provider_name": ""}')
            if reply.startswith("no") or reply.startswith("cancel"):
                return MockResponse('{"decision": "cancelled", "preference": "none", "requested_provider_name": ""}')
            return MockResponse('{"decision": "unclear", "preference": "none", "requested_provider_name": ""}')
        if "unfortunately, you do not have any providers matching" in text:
            return MockResponse("I'm sorry, but we don't have any providers available for that service in your area right now.")
        if "summarize this service request" in text:
            return MockResponse('{"title": "AC Repair G-13"}')
        if "milk provider" in text:
            return MockResponse('{"service_type": "", "location": "", "time": "ASAP"}')
        if "plumber" in text:
            return MockResponse('{"service_type": "Plumber", "location": "G-13", "time": "ASAP"}')
        if "ac repair" in text or "ac technician" in text:
            if "g-13" in text:
                return MockResponse('{"service_type": "AC Technician", "location": "G-13", "time": "tomorrow 10 AM"}')
            if "f-8" in text:
                return MockResponse('{"service_type": "AC Technician", "location": "F-8", "time": "ASAP"}')
        if "electrician" in text:
            return MockResponse('{"service_type": "Electrician", "location": "G-13", "time": "ASAP"}')
        return MockResponse('{"service_type": "", "location": "", "time": "ASAP"}')


class MockGenaiClient:
    def __init__(self, api_key=None):
        self.models = MockModels()


async def setup_mongo_test_db(uri: str, db_name: str) -> None:
    init_mongodb(uri, db_name)
    await db_module.db.client.drop_database(db_name)
    await migrate_database_schema()
    await db_module.db.providers.insert_many(TEST_PROVIDERS)
    await db_module.db.counters.update_one({"_id": "bookings"}, {"$set": {"seq": 0}}, upsert=True)
    await load_valid_services()


class ReliabilityWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.mongo_uri = os.getenv("MONGODB_TEST_URI")
        if not self.mongo_uri:
            self.tmp.cleanup()
            raise unittest.SkipTest("MONGODB_TEST_URI is not configured")
        self.db_name = f"test_workflow_{Path(self.tmp.name).name}"
        self.checkpoint_db_name = f"{self.db_name}_checkpoints"
        os.environ["GEMINI_API_KEY"] = "test-key"
        os.environ["MONGODB_URI"] = self.mongo_uri
        os.environ["MONGODB_DB"] = self.db_name
        os.environ["MONGODB_CHECKPOINT_DB"] = self.checkpoint_db_name
        asyncio.run(setup_mongo_test_db(self.mongo_uri, self.db_name))

    def tearDown(self):
        client = motor.motor_asyncio.AsyncIOMotorClient(self.mongo_uri)
        asyncio.run(client.drop_database(self.db_name))
        asyncio.run(client.drop_database(self.checkpoint_db_name))
        client.close()
        close_mongodb()
        self.tmp.cleanup()
        os.environ.pop("MONGODB_URI", None)
        os.environ.pop("MONGODB_DB", None)
        os.environ.pop("MONGODB_CHECKPOINT_DB", None)

    def compile_graph(self):
        return MongoDBSaver.from_conn_string(self.mongo_uri, db_name=self.checkpoint_db_name)

    async def booking_count(self) -> int:
        return await db_module.db.bookings.count_documents({})

    @patch("google.genai.Client", MockGenaiClient)
    def test_discovery_exact_location_and_ranking_price_tiebreaker(self):
        async def run():
            state = {
                "parsed_intent": {"service_type": "AC Technician", "location": "G-13", "time": "ASAP"},
                "logs": [],
            }
            discovered = await discover_providers(state)
            self.assertEqual([p["location"] for p in discovered["discovered_providers"]], ["G-13", "G-13"])
            ranked = rank_providers(discovered)
            self.assertEqual(ranked["selected_provider"]["name"], "Zain AC Repair")

        asyncio.run(run())

    @patch("google.genai.Client", MockGenaiClient)
    def test_intent_preserves_unsupported_requested_service(self):
        state = {
            "messages": [
                {"role": "user", "content": "hi there"},
                {"role": "assistant", "content": "Please share the service type and location."},
                {"role": "user", "content": "find milk provider in g23"},
                {"role": "assistant", "content": "Please share the service type and location."},
                {"role": "user", "content": "milk provider in g13"},
            ],
            "logs": [],
        }
        result = parse_intent(state)
        self.assertEqual(result["parsed_intent"]["service_type"], "Milk")
        self.assertEqual(result["parsed_intent"]["location"], "G-13")

    @patch("google.genai.Client", MockGenaiClient)
    def test_workflow_unsupported_service_reaches_no_providers(self):
        async def run():
            with self.compile_graph() as checkpointer:
                graph = create_workflow().compile(checkpointer=checkpointer, interrupt_before=["simulate_booking"])
                config = {"configurable": {"thread_id": "thread-milk"}}
                result = await graph.ainvoke(
                    {"user_id": "u1", "messages": [{"role": "user", "content": "milk provider in g13"}], "logs": []},
                    config,
                )
                self.assertEqual(result["parsed_intent"]["service_type"], "Milk")
                self.assertEqual(result["parsed_intent"]["location"], "G-13")
                self.assertEqual(result["discovered_providers"], [])
                self.assertIn("providers available", result["messages"][-1]["content"])

        asyncio.run(run())

    @patch("google.genai.Client", MockGenaiClient)
    def test_booking_requires_clear_confirmation(self):
        async def run():
            base_state = {
                "user_id": "u1",
                "messages": [
                    {"role": "user", "content": "Need AC repair in G-13"},
                    {"role": "assistant", "content": "I found Zain. Do you want me to book this?"},
                    {"role": "user", "content": "what time is it"},
                ],
                "parsed_intent": {"time": "tomorrow 10 AM"},
                "selected_provider": {"id": 1, "name": "Ali AC Services"},
                "logs": [],
            }
            unclear = await simulate_booking(base_state)
            self.assertEqual(unclear["confirmation_status"], "unclear")
            self.assertEqual(await self.booking_count(), 0)

            yes_state = {**base_state, "messages": [*base_state["messages"], {"role": "user", "content": "Yes"}]}
            confirmed = await simulate_booking(yes_state)
            self.assertEqual(confirmed["confirmation_status"], "confirmed")
            self.assertEqual(await self.booking_count(), 1)

        asyncio.run(run())

    @patch("google.genai.Client", MockGenaiClient)
    def test_workflow_interrupt_then_reject_does_not_book(self):
        async def run():
            with self.compile_graph() as checkpointer:
                graph = create_workflow().compile(checkpointer=checkpointer, interrupt_before=["simulate_booking"])
                config = {"configurable": {"thread_id": "thread-1"}}
                result = await graph.ainvoke(
                    {"user_id": "u1", "messages": [{"role": "user", "content": "I need AC repair in G-13 tomorrow 10 AM"}], "logs": []},
                    config,
                )
                self.assertEqual(result["selected_provider"]["name"], "Zain AC Repair")
                self.assertIn("simulate_booking", (await graph.aget_state(config)).next)

                await graph.aupdate_state(config, {"messages": [*result["messages"], {"role": "user", "content": "No, cancel it"}]})
                final = await graph.ainvoke(None, config)
                self.assertEqual(final["confirmation_status"], "cancelled")
                self.assertEqual(await self.booking_count(), 0)

        asyncio.run(run())

    @patch("google.genai.Client", MockGenaiClient)
    def test_workflow_cheaper_provider_then_confirm_books_alternative(self):
        async def run():
            with self.compile_graph() as checkpointer:
                graph = create_workflow().compile(checkpointer=checkpointer, interrupt_before=["simulate_booking"])
                config = {"configurable": {"thread_id": "thread-cheaper"}}
                result = await graph.ainvoke(
                    {"user_id": "u1", "messages": [{"role": "user", "content": "I need AC repair in G-13 tomorrow 10 AM"}], "logs": []},
                    config,
                )
                self.assertEqual(result["selected_provider"]["name"], "Zain AC Repair")

                await graph.aupdate_state(config, {"messages": [*result["messages"], {"role": "user", "content": "no, show cheaper one"}]})
                alternative = await graph.ainvoke(None, config)
                self.assertEqual(alternative["selected_provider"]["name"], "Ali AC Services")

                await graph.aupdate_state(config, {"messages": [*alternative["messages"], {"role": "user", "content": "yes"}]})
                confirmed = await graph.ainvoke(None, config)
                self.assertEqual(confirmed["confirmation_status"], "confirmed")
                booking = await db_module.db.bookings.find_one({})
                self.assertEqual(booking["provider_id"], 1)

        asyncio.run(run())

    @patch("google.genai.Client", MockGenaiClient)
    def test_workflow_no_alternative_does_not_book(self):
        async def run():
            with self.compile_graph() as checkpointer:
                graph = create_workflow().compile(checkpointer=checkpointer, interrupt_before=["simulate_booking"])
                config = {"configurable": {"thread_id": "thread-no-alt"}}
                result = await graph.ainvoke(
                    {"user_id": "u1", "messages": [{"role": "user", "content": "I need electrician in G-13"}], "logs": []},
                    config,
                )

                await graph.aupdate_state(config, {"messages": [*result["messages"], {"role": "user", "content": "any other provider?"}]})
                no_alt = await graph.ainvoke(None, config)
                self.assertEqual(no_alt["confirmation_status"], "awaiting")
                self.assertIn("do not have another matching provider", no_alt["messages"][-1]["content"])
                self.assertEqual(await self.booking_count(), 0)

        asyncio.run(run())

    @patch("google.genai.Client", MockGenaiClient)
    def test_workflow_specific_provider_request_selects_named_provider(self):
        async def run():
            with self.compile_graph() as checkpointer:
                graph = create_workflow().compile(checkpointer=checkpointer, interrupt_before=["simulate_booking"])
                config = {"configurable": {"thread_id": "thread-specific"}}
                result = await graph.ainvoke(
                    {"user_id": "u1", "messages": [{"role": "user", "content": "I need AC repair in G-13 tomorrow 10 AM"}], "logs": []},
                    config,
                )
                await graph.aupdate_state(config, {"messages": [*result["messages"], {"role": "user", "content": "I want Ali instead"}]})
                selected = await graph.ainvoke(None, config)
                self.assertEqual(selected["selected_provider"]["name"], "Ali AC Services")

        asyncio.run(run())

    @patch("google.genai.Client", MockGenaiClient)
    def test_workflow_new_service_request_restarts_intent(self):
        async def run():
            with self.compile_graph() as checkpointer:
                graph = create_workflow().compile(checkpointer=checkpointer, interrupt_before=["simulate_booking"])
                config = {"configurable": {"thread_id": "thread-new-service"}}
                result = await graph.ainvoke(
                    {"user_id": "u1", "messages": [{"role": "user", "content": "I need AC repair in G-13 tomorrow 10 AM"}], "logs": []},
                    config,
                )
                await graph.aupdate_state(config, {"messages": [*result["messages"], {"role": "user", "content": "actually I need plumber in G-13"}]})
                restarted = await graph.ainvoke(None, config)
                self.assertEqual(restarted["parsed_intent"]["service_type"], "Plumber")
                self.assertEqual(restarted["selected_provider"]["name"], "Hassan Plumbers")

        asyncio.run(run())

    @patch("google.genai.Client", MockGenaiClient)
    def test_booking_duplicate_confirmation_reuses_existing_booking(self):
        async def run():
            state = {
                "user_id": "u1",
                "messages": [{"role": "user", "content": "Yes"}],
                "parsed_intent": {"time": "tomorrow 10 AM"},
                "selected_provider": {"id": 1, "name": "Ali AC Services"},
                "discovered_providers": [],
                "logs": [],
            }
            first = await simulate_booking(state)
            second = await simulate_booking(state)
            self.assertEqual(first["booking_id"], second["booking_id"])
            self.assertEqual(await self.booking_count(), 1)

        asyncio.run(run())

    @patch("google.genai.Client", MockGenaiClient)
    def test_booking_rechecks_provider_availability(self):
        async def run():
            await db_module.db.providers.update_one({"id": 1}, {"$set": {"available": False}})
            state = {
                "user_id": "u1",
                "messages": [{"role": "user", "content": "Yes"}],
                "parsed_intent": {"time": "tomorrow 10 AM"},
                "selected_provider": {"id": 1, "name": "Ali AC Services"},
                "discovered_providers": [{"id": 1, "name": "Ali AC Services", "rating": 4.8, "base_price": 1500}],
                "logs": [],
            }
            result = await simulate_booking(state)
            self.assertEqual(result["confirmation_status"], "alternative_requested")
            self.assertEqual(result["provider_preference"], "next_best")
            self.assertEqual(await self.booking_count(), 0)

        asyncio.run(run())

    @patch("google.genai.Client", MockGenaiClient)
    def test_mongo_checkpoint_continues_conversation(self):
        async def run():
            with self.compile_graph() as checkpointer:
                graph = create_workflow().compile(checkpointer=checkpointer, interrupt_before=["simulate_booking"])
                config = {"configurable": {"thread_id": "thread-continuation"}}
                result = await graph.ainvoke(
                    {"user_id": "u1", "messages": [{"role": "user", "content": "I need AC repair in G-13 tomorrow 10 AM"}], "logs": []},
                    config,
                )
                await graph.aupdate_state(config, {"messages": [*result["messages"], {"role": "user", "content": "Yes"}]})
                confirmed = await graph.ainvoke(None, config)
                self.assertEqual(confirmed["confirmation_status"], "confirmed")
                snap = await graph.aget_state(config)
                self.assertEqual(snap.values["booking_id"], confirmed["booking_id"])

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
