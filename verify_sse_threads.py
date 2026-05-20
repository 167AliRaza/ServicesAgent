import os
import asyncio
import uuid
import sys
import json
import aiosqlite
from dotenv import load_dotenv
from unittest.mock import patch

class MockResponse:
    def __init__(self, text):
        self.text = text

class MockModels:
    def generate_content(self, model, contents, config=None):
        contents_str = str(contents).lower()
        if "rejection" in contents_str:
            return MockResponse('{"is_rejection": false}')
        elif "summarize" in contents_str or "title" in contents_str:
            return MockResponse('{"title": "AC Repair G-13"}')
        else:
            return MockResponse('{"service_type": "AC Technician", "location": "G-13", "time": "tomorrow at 10 AM"}')

class MockGenaiClient:
    def __init__(self, api_key=None):
        self.models = MockModels()

# Ensure we can import src
sys.path.append(os.path.abspath(os.path.dirname(__file__) + "/../../../../Music/informalServicesMPAgent"))

load_dotenv("c:/Users/User-1/Music/informalServicesMPAgent/.env")

from src.main import app, RequestBody, request_endpoint, list_user_threads, get_thread_messages, list_user_bookings
from src.db import get_threads, get_messages, get_bookings

async def run_sse_generator(generator):
    """Consume the SSE event stream and return the decoded payloads."""
    events = []
    async for item in generator:
        if item.startswith("data: "):
            content = item[6:].strip()
            if content:
                events.append(json.loads(content))
    return events

async def test_end_to_end():
    with patch("google.genai.Client", MockGenaiClient):
        print("Initializing FastAPI lifespan...")
        # Trigger lifespan startup programmatically
        async with app.router.lifespan_context(app):
            print("FastAPI Lifespan initialized successfully!")

        user_id = f"test_user_{uuid.uuid4().hex[:6]}"
        print(f"Creating a new service request for user: {user_id}")

        # Request body
        req = RequestBody(
            text="I need AC repair service in G-13 tomorrow morning at 10 AM",
            user_id=user_id,
            thread_id=None
        )

        # Call request_endpoint
        response = await request_endpoint(req)
        # Consume the streaming response
        events = await run_sse_generator(response.body_iterator)

        print(f"SSE stream events generated: {json.dumps(events, indent=2)}")
        done_events = [e for e in events if e.get("type") == "done"]
        assert len(done_events) == 1, "Expected exactly 1 final done payload event"
        payload = done_events[0]
        thread_id = payload.get("task_id")
        assert thread_id is not None, "Expected task_id in final payload"
        print(f"New Thread ID generated: {thread_id}")

        # Wait a moment for title background generation task to execute
        print("Waiting 3 seconds for the background thread title generation task...")
        await asyncio.sleep(3.0)

        # 1. Verify user threads list endpoint
        print("\n--- Testing GET /threads/{user_id} ---")
        threads = await list_user_threads(user_id)
        print("Threads response:", threads)
        assert len(threads) == 1
        assert threads[0]["thread_id"] == thread_id
        assert threads[0]["title"] != "New Conversation", "Title should have been updated by Gemini title agent"
        print("GET /threads/{user_id} passed!")

        # 2. Verify messages history endpoint
        print("\n--- Testing GET /threads/{thread_id}/messages ---")
        messages_resp = await get_thread_messages(thread_id)
        print("Messages history response:", messages_resp)
        assert len(messages_resp) > 0
        assert messages_resp[0]["role"] == "user"
        print("GET /threads/{thread_id}/messages passed!")

        # 3. Test continuation message (using existing thread_id)
        print("\n--- Testing continuation POST /request ---")
        req_continue = RequestBody(
            text="Yes, confirm the Zain AC Repair booking please",
            user_id=user_id,
            thread_id=thread_id
        )
        response_cont = await request_endpoint(req_continue)
        events_cont = await run_sse_generator(response_cont.body_iterator)
        print("SSE continuation response:", events_cont)
        done_events_cont = [e for e in events_cont if e.get("type") == "done"]
        assert len(done_events_cont) == 1
        print("Continuation POST /request passed!")

        # 4. Insert dummy booking and verify list_user_bookings
        print("\n--- Testing GET /bookings/{user_id} ---")
        async with aiosqlite.connect("service_agent.db") as conn:
            # Check a provider exists
            cursor = await conn.execute("SELECT id FROM providers LIMIT 1")
            provider_row = await cursor.fetchone()
            if provider_row:
                provider_id = provider_row[0]
                await conn.execute(
                    "INSERT INTO bookings (provider_id, user_id, booking_time, status) VALUES (?, ?, ?, ?)",
                    (provider_id, user_id, "10:00 AM", "CONFIRMED")
                )
                await conn.commit()
                print("Dummy booking inserted successfully.")

        bookings = await list_user_bookings(user_id)
        print("Bookings response:", bookings)
        assert len(bookings) == 1
        assert bookings[0]["status"] == "CONFIRMED"
        print("GET /bookings/{user_id} passed!")

        print("\n🎉 ALL TESTS PASSED SUCCESSFULLY! 🎉")

if __name__ == "__main__":
    asyncio.run(test_end_to_end())
