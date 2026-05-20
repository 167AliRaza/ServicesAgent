from src.agent_utils import add_log, append_message
from src.llm import generate_text

def handle_no_providers(state: dict) -> dict:
    parsed_intent = state.get("parsed_intent", {})
    
    service_type = parsed_intent.get("service_type", "requested service")
    location = parsed_intent.get("location", "your location")
    
    logs = add_log(state, "NoProvidersAgent: No matching providers found, reporting to user.")
    default_msg = f"I'm sorry, but we don't have any providers available for {service_type} in {location} right now. Please try a different location or check back later."
    
    prompt = f"""
    You are a polite service booking assistant. The user is looking for "{service_type}" in "{location}".
    Unfortunately, you do not have any providers matching this service in their area right now.
    Politely explain this to the user, suggesting they try a different location or check back later.
    If they used Roman Urdu or Urdu, respond in Roman Urdu.
    Keep it to one short, friendly sentence.
    Conversation: {state.get("messages", [])}
    """
    msg = generate_text(prompt, default_msg)
        
    logs = [*logs, f"NoProvidersAgent: Generated message: {msg}"]
    
    return {"messages": append_message(state, "assistant", msg), "logs": logs}
