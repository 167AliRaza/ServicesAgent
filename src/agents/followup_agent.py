from datetime import datetime, timedelta, timezone

from src.agent_utils import add_log
from src.db import create_followup_tasks


def _parse_booking_time(value: str) -> datetime | None:
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _build_followup_tasks(state: dict) -> list[dict]:
    now = datetime.now(timezone.utc)
    booking_time = _parse_booking_time(str(state.get("parsed_intent", {}).get("time", "")))
    booking_id = state.get("booking_id")
    user_id = state.get("user_id", "")
    provider = state.get("selected_provider") or {}
    provider_id = provider.get("id")

    if not booking_id or not user_id:
        return []

    tasks = []
    if booking_time is not None:
        tasks.append(
            {
                "booking_id": booking_id,
                "user_id": user_id,
                "provider_id": provider_id,
                "type": "pre_service_reminder",
                "channel": "in_app",
                "scheduled_for": booking_time - timedelta(hours=1),
            }
        )
        tasks.append(
            {
                "booking_id": booking_id,
                "user_id": user_id,
                "provider_id": provider_id,
                "type": "post_service_checkin",
                "channel": "in_app",
                "scheduled_for": booking_time + timedelta(hours=2),
            }
        )
    else:
        tasks.append(
            {
                "booking_id": booking_id,
                "user_id": user_id,
                "provider_id": provider_id,
                "type": "post_service_checkin",
                "channel": "in_app",
                "scheduled_for": now + timedelta(hours=2),
            }
        )
    return tasks


async def schedule_followup(state: dict) -> dict:
    booking_status = state.get("booking_status", "")

    if not booking_status.startswith("Slot booked"):
        logs = add_log(state, "FollowupAgent: No successful booking to follow up on.")
        return {"followup_plan": "None", "logs": logs}

    tasks = _build_followup_tasks(state)
    created = await create_followup_tasks(tasks)
    logs = add_log(state, f"FollowupAgent: Created/updated {created} follow-up tasks.")

    task_types = {task["type"] for task in tasks}
    if "pre_service_reminder" in task_types:
        plan = "Follow-ups created: pre-service reminder and post-service check-in."
    else:
        plan = "Follow-up created: post-service check-in."

    return {"followup_plan": plan, "logs": logs}
