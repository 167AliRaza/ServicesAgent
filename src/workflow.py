from langgraph.graph import StateGraph, END

from src.state import AgentState
from src.agents.intent_agent import parse_intent
from src.agents.clarification_agent import ask_clarification
from src.agents.discovery_agent import discover_providers
from src.agents.ranking_agent import rank_providers
from src.agents.confirmation_agent import ask_confirmation
from src.agents.booking_agent import simulate_booking
from src.agents.followup_agent import schedule_followup
from src.agents.no_providers_agent import handle_no_providers
from src.agents.provider_preference_agent import handle_provider_preference

def route_intent(state: dict):
    parsed = state.get("parsed_intent", {})
    if not parsed.get("service_type") or not parsed.get("location"):
        return "ask_clarification"
    return "discover_providers"

def route_discovery(state: dict):
    providers = state.get("discovered_providers", [])
    if not providers:
        return "handle_no_providers"
    return "rank_providers"

def route_booking(state: dict):
    if state.get("confirmation_status") == "new_service_request":
        return "parse_intent"
    if state.get("confirmation_status") == "alternative_requested":
        return "handle_provider_preference"
    if state.get("confirmation_status") == "unclear":
        return "ask_confirmation"
    if state.get("confirmation_status") == "confirmed":
        return "schedule_followup"
    return END

def create_workflow():
    workflow = StateGraph(AgentState)
    
    workflow.add_node("parse_intent", parse_intent)
    workflow.add_node("ask_clarification", ask_clarification)
    workflow.add_node("discover_providers", discover_providers)
    workflow.add_node("rank_providers", rank_providers)
    workflow.add_node("ask_confirmation", ask_confirmation)
    workflow.add_node("simulate_booking", simulate_booking)
    workflow.add_node("schedule_followup", schedule_followup)
    workflow.add_node("handle_no_providers", handle_no_providers)
    workflow.add_node("handle_provider_preference", handle_provider_preference)
    
    workflow.set_entry_point("parse_intent")
    
    workflow.add_conditional_edges("parse_intent", route_intent)
    
    # If we ask for clarification, we go to END to pause and wait for user's reply.
    workflow.add_edge("ask_clarification", END)
    
    # Route based on discovered providers count
    workflow.add_conditional_edges("discover_providers", route_discovery)
    
    workflow.add_edge("handle_no_providers", END)
    workflow.add_edge("rank_providers", "ask_confirmation")
    
    # Ask confirmation, then simulate booking (will be interrupted before simulate_booking in main.py)
    workflow.add_edge("ask_confirmation", "simulate_booking")
    
    workflow.add_conditional_edges("simulate_booking", route_booking)
    workflow.add_edge("handle_provider_preference", "ask_confirmation")
    workflow.add_edge("schedule_followup", END)
    
    return workflow
