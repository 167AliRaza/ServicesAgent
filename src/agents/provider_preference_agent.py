from src.agent_utils import add_log


def _provider_id(provider: dict) -> int | None:
    value = provider.get("id")
    return int(value) if value is not None else None


def _sort_candidates(providers: list[dict], preference: str) -> list[dict]:
    if preference == "cheapest":
        return sorted(providers, key=lambda p: (float(p["base_price"]), -float(p["rating"])))
    if preference == "higher_rating":
        return sorted(providers, key=lambda p: (-float(p["rating"]), float(p["base_price"])))
    return sorted(providers, key=lambda p: (-float(p["rating"]), float(p["base_price"])))


def _find_specific_provider(providers: list[dict], requested_name: str) -> dict | None:
    requested = requested_name.lower().strip()
    if not requested:
        return None
    for provider in providers:
        name = str(provider.get("name", ""))
        if name.lower() == requested or requested in name.lower():
            return provider
    return None


def handle_provider_preference(state: dict) -> dict:
    providers = state.get("discovered_providers", [])
    selected_provider = state.get("selected_provider")
    preference = state.get("provider_preference") or "next_best"
    requested_provider_name = state.get("requested_provider_name", "")
    shown_ids = set(state.get("shown_provider_ids", []))

    if selected_provider and _provider_id(selected_provider) is not None:
        shown_ids.add(_provider_id(selected_provider))

    logs = add_log(state, f"ProviderPreferenceAgent: Looking for alternative provider with preference '{preference}'.")

    if preference == "specific_provider":
        requested_provider = _find_specific_provider(providers, requested_provider_name)
        if requested_provider:
            provider_id = _provider_id(requested_provider)
            if provider_id is not None:
                shown_ids.add(provider_id)
            return {
                "selected_provider": requested_provider,
                "reasoning": f"Selected the provider requested by name: {requested_provider['name']}.",
                "booking_status": "",
                "confirmation_status": "awaiting",
                "provider_preference": "none",
                "requested_provider_name": "",
                "confirmation_prompt_override": "",
                "shown_provider_ids": list(shown_ids),
                "logs": [*logs, f"ProviderPreferenceAgent: Selected requested provider '{requested_provider['name']}'."],
            }

        return {
            "booking_status": "Pending: Requested provider not found",
            "confirmation_status": "unclear",
            "provider_preference": "none",
            "requested_provider_name": "",
            "confirmation_prompt_override": f"I could not find {requested_provider_name} in the matching providers. You can book the current option, show another provider, or cancel.",
            "shown_provider_ids": list(shown_ids),
            "logs": [*logs, "ProviderPreferenceAgent: Requested provider name was not found."],
        }

    candidates = [
        provider
        for provider in providers
        if _provider_id(provider) not in shown_ids
    ]

    if not candidates:
        if preference == "cheapest" and selected_provider:
            cheapest = _sort_candidates(providers, "cheapest")[0] if providers else None
            if cheapest and _provider_id(cheapest) == _provider_id(selected_provider):
                msg = f"{selected_provider['name']} is already the cheapest matching provider at {selected_provider['base_price']} PKR. You can book this option, show another provider, or cancel."
            else:
                msg = "I do not have a cheaper matching provider available. You can book the current option, show another provider, or cancel."
        else:
            msg = "I do not have another matching provider available. You can book the current option or cancel."
        return {
            "booking_status": "Pending: No alternative providers",
            "confirmation_status": "unclear",
            "provider_preference": "none",
            "requested_provider_name": "",
            "confirmation_prompt_override": msg,
            "shown_provider_ids": list(shown_ids),
            "logs": [*logs, "ProviderPreferenceAgent: No alternative providers available."],
        }

    new_provider = _sort_candidates(candidates, preference)[0]
    new_id = _provider_id(new_provider)
    if new_id is not None:
        shown_ids.add(new_id)

    if preference == "cheapest":
        reasoning = f"Selected the lowest-price alternative at {new_provider['base_price']} PKR."
    elif preference == "higher_rating":
        reasoning = f"Selected the highest-rated alternative with rating {new_provider['rating']}."
    else:
        reasoning = "Selected the next best available alternative."

    return {
        "selected_provider": new_provider,
        "reasoning": reasoning,
        "booking_status": "",
        "confirmation_status": "awaiting",
        "provider_preference": "none",
        "requested_provider_name": "",
        "confirmation_prompt_override": "",
        "shown_provider_ids": list(shown_ids),
        "logs": [*logs, f"ProviderPreferenceAgent: Selected alternative provider '{new_provider['name']}'. {reasoning}"],
    }
