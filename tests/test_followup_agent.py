import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from src.agents.followup_agent import schedule_followup


class FollowupAgentTests(unittest.TestCase):
    def run_async(self, coro):
        return asyncio.run(coro)

    @patch("src.agents.followup_agent.create_followup_tasks", new_callable=AsyncMock)
    def test_no_followup_for_unsuccessful_booking(self, mock_create):
        state = {"booking_status": "Failed: No provider selected", "logs": []}
        result = self.run_async(schedule_followup(state))
        self.assertEqual(result["followup_plan"], "None")
        mock_create.assert_not_awaited()

    @patch("src.agents.followup_agent.create_followup_tasks", new_callable=AsyncMock)
    def test_creates_pre_and_post_tasks_when_time_is_iso(self, mock_create):
        mock_create.return_value = 2
        state = {
            "booking_status": "Slot booked for 2026-05-22T10:00:00+00:00 with Ali AC Services. Confirmation sent.",
            "booking_id": 11,
            "user_id": "u1@example.com",
            "selected_provider": {"id": 1, "name": "Ali AC Services"},
            "parsed_intent": {"time": "2026-05-22T10:00:00+00:00"},
            "logs": [],
        }
        result = self.run_async(schedule_followup(state))
        self.assertIn("pre-service reminder", result["followup_plan"])
        mock_create.assert_awaited_once()
        tasks = mock_create.await_args.args[0]
        self.assertEqual({task["type"] for task in tasks}, {"pre_service_reminder", "post_service_checkin"})

    @patch("src.agents.followup_agent.create_followup_tasks", new_callable=AsyncMock)
    def test_creates_post_only_for_unparseable_time(self, mock_create):
        mock_create.return_value = 1
        state = {
            "booking_status": "Slot booked for ASAP with Ali AC Services. Confirmation sent.",
            "booking_id": 12,
            "user_id": "u1@example.com",
            "selected_provider": {"id": 1, "name": "Ali AC Services"},
            "parsed_intent": {"time": "ASAP"},
            "logs": [],
        }
        result = self.run_async(schedule_followup(state))
        self.assertIn("post-service check-in", result["followup_plan"])
        tasks = mock_create.await_args.args[0]
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["type"], "post_service_checkin")


if __name__ == "__main__":
    unittest.main()
