from src.agent_utils import add_log

def schedule_followup(state: dict) -> dict:
    booking_status = state.get("booking_status", "")
    
    if not booking_status.startswith("Slot booked"):
        logs = add_log(state, "FollowupAgent: No successful booking to follow up on.")
        return {"followup_plan": "None", "logs": logs}
        
    logs = add_log(state, "FollowupAgent: Scheduling follow-up reminders.")
    plan = "Reminder scheduled 1 hour before appointment. Status update queued for after completion."
    
    return {"followup_plan": plan, "logs": logs}
