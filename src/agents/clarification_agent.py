from src.agent_utils import add_log, append_message
from src.llm import generate_text

def ask_clarification(state: dict) -> dict:
    parsed_intent = state.get("parsed_intent", {})
    
    logs = add_log(state, "ClarificationAgent: Missing required fields, asking user for clarification.")
    
    missing = []
    if not parsed_intent.get("service_type"):
        missing.append("service_type")
    if not parsed_intent.get("location"):
        missing.append("location")
        
    default_msg = "Please share the service type and location so I can find the right provider."
    if missing == ["service_type"]:
        default_msg = "What service do you need?"
    elif missing == ["location"]:
        default_msg = "Which area should I search in?"
    
    prompt = f"""
    You are a polite service booking assistant. The user wants to book a service, but you are missing the following information: {', '.join(missing)}.
    Ask the user for this missing information in a natural, friendly way.
    If the user spoke in Roman Urdu, respond in Roman Urdu.
    Keep it to one short sentence.
    """
    
    clarification_msg = generate_text(prompt, default_msg)
    logs = [*logs, f"ClarificationAgent: Generated message: {clarification_msg}"]
    
    return {"messages": append_message(state, "assistant", clarification_msg), "logs": logs}
