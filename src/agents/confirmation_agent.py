from src.agent_utils import add_log, append_message

def ask_confirmation(state: dict) -> dict:
    selected_provider = state.get("selected_provider")
    
    if not selected_provider:
        logs = add_log(state, "ConfirmationAgent: No provider to confirm.")
        return {"logs": logs}
        
    msg = state.get("confirmation_prompt_override") or (
        f"I found {selected_provider['name']} for {selected_provider['base_price']} PKR. "
        "Do you want me to book this, show a cheaper option, show another provider, or cancel?"
    )
    logs = add_log(state, f"ConfirmationAgent: Asking confirmation -> {msg}")

    shown_provider_ids = list(state.get("shown_provider_ids", []))
    provider_id = selected_provider.get("id")
    if provider_id is not None and provider_id not in shown_provider_ids:
        shown_provider_ids.append(provider_id)

    return {
        "messages": append_message(state, "assistant", msg),
        "logs": logs,
        "confirmation_status": "awaiting",
        "confirmation_prompt_override": "",
        "shown_provider_ids": shown_provider_ids,
    }
