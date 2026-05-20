from typing import TypedDict, Optional, List, Dict, Any

class AgentState(TypedDict):
    user_id: str
    messages: List[Dict[str, str]]
    parsed_intent: Optional[Dict[str, Any]]
    discovered_providers: List[Dict[str, Any]]
    selected_provider: Optional[Dict[str, Any]]
    shown_provider_ids: List[int]
    provider_preference: str
    requested_provider_name: str
    confirmation_prompt_override: str
    booking_id: Optional[int]
    reasoning: str
    booking_status: str
    confirmation_status: str
    followup_plan: str
    logs: List[str]
