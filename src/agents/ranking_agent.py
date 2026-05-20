from src.agent_utils import add_log

def rank_providers(state: dict) -> dict:
    providers = state.get("discovered_providers", [])
    
    if not providers:
        logs = add_log(state, "RankingAgent: No providers found. Cannot recommend.")
        return {"selected_provider": None, "reasoning": "No providers found for the given location and service.", "logs": logs}
    
    logs = add_log(state, f"RankingAgent: Evaluating {len(providers)} providers to pick the best one.")
    selected_provider = sorted(
        providers,
        key=lambda p: (-float(p["rating"]), float(p["base_price"])),
    )[0]
    reasoning = (
        f"Selected for the highest rating ({selected_provider['rating']}) "
        f"with a competitive price of {selected_provider['base_price']} PKR."
    )
    logs = [*logs, f"RankingAgent: Selected provider '{selected_provider['name']}'. Reasoning: {reasoning}"]
    
    return {"selected_provider": selected_provider, "reasoning": reasoning, "logs": logs}
