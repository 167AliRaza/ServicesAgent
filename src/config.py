"""Runtime configuration helpers."""
from __future__ import annotations

import os


def get_db_path() -> str:
    return os.getenv("SERVICE_AGENT_DB", "service_agent.db")


def get_checkpoint_path() -> str:
    return os.getenv("SERVICE_AGENT_CHECKPOINT_DB", "checkpoints.sqlite")


def get_gemini_model() -> str:
    return os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")


def get_gemini_api_key() -> str | None:
    return os.getenv("GEMINI_API_KEY")


def _split_csv_env(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def get_gemini_models() -> list[str]:
    models = _split_csv_env(os.getenv("GEMINI_MODELS"))
    if models:
        return models
    return [get_gemini_model()]


def get_gemini_api_keys() -> list[str]:
    api_keys = _split_csv_env(os.getenv("GEMINI_API_KEYS"))
    if api_keys:
        return api_keys
    api_key = get_gemini_api_key()
    return [api_key] if api_key else []
