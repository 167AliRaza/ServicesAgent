"""Runtime configuration helpers."""
from __future__ import annotations

import os


def get_mongodb_uri() -> str:
    return os.getenv("MONGODB_URI", "mongodb://localhost:27017")


def get_mongodb_db() -> str:
    return os.getenv("MONGODB_DB", "ServicesAgentDB")


def get_mongodb_checkpoint_db() -> str:
    return os.getenv("MONGODB_CHECKPOINT_DB", get_mongodb_db())


def get_mongodb_server_selection_timeout_ms() -> int:
    try:
        return int(os.getenv("MONGODB_SERVER_SELECTION_TIMEOUT_MS", "10000"))
    except ValueError:
        return 10000


def get_cron_secret() -> str | None:
    return os.getenv("CRON_SECRET")



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
