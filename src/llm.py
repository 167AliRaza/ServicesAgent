"""Gemini access with consistent parsing and fallbacks."""
from __future__ import annotations

import json
import logging
from typing import Any, Type

from google import genai
from pydantic import BaseModel

from src.config import get_gemini_api_keys, get_gemini_models


logger = logging.getLogger(__name__)


def _client(api_key: str) -> genai.Client:
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured")
    return genai.Client(api_key=api_key)


def _fallback_targets() -> list[tuple[int, str, str]]:
    api_keys = get_gemini_api_keys()
    models = get_gemini_models()
    if not api_keys:
        raise RuntimeError("GEMINI_API_KEY is not configured")
    return [
        (key_index, api_key, model)
        for key_index, api_key in enumerate(api_keys, start=1)
        for model in models
    ]


def _error_status(error: Exception) -> int | None:
    for attr in ("status_code", "code"):
        value = getattr(error, attr, None)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)

    response = getattr(error, "response", None)
    value = getattr(response, "status_code", None)
    if isinstance(value, int):
        return value

    return None


def _error_category(error: Exception) -> str:
    status = _error_status(error)
    if status == 429:
        return "quota_or_rate_limit"
    if status == 403 and "quota" in str(error).lower():
        return "quota_or_permission"
    if status and status >= 500:
        return "server_error"
    if status:
        return f"api_error_{status}"
    text = str(error).lower()
    if "quota" in text or "rate limit" in text or "resource exhausted" in text:
        return "quota_or_rate_limit"
    return error.__class__.__name__


def _log_fallback_error(kind: str, key_index: int, model: str, error: Exception) -> None:
    logger.warning(
        "Gemini %s attempt failed for key #%s, model %s: %s",
        kind,
        key_index,
        model,
        _error_category(error),
    )


def generate_json(prompt: str, schema: Type[BaseModel], default: dict[str, Any]) -> dict[str, Any]:
    try:
        targets = _fallback_targets()
    except Exception as error:
        logger.warning("Gemini JSON unavailable: %s", _error_category(error))
        return default

    for key_index, api_key, model in targets:
        try:
            response = _client(api_key).models.generate_content(
                model=model,
                contents=prompt,
                config=genai.types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=schema,
                    temperature=0.0,
                ),
            )
            parsed = json.loads(response.text)
            if isinstance(parsed, dict):
                return parsed
            raise ValueError("Gemini JSON response was not an object")
        except Exception as error:
            _log_fallback_error("JSON", key_index, model, error)

    logger.warning("Gemini JSON fallback exhausted; returning default")
    return default


def generate_text(prompt: str, default: str) -> str:
    try:
        targets = _fallback_targets()
    except Exception as error:
        logger.warning("Gemini text unavailable: %s", _error_category(error))
        return default

    for key_index, api_key, model in targets:
        try:
            response = _client(api_key).models.generate_content(
                model=model,
                contents=prompt,
            )
            text = response.text.strip()
            if text:
                return text
            raise ValueError("Gemini text response was blank")
        except Exception as error:
            _log_fallback_error("text", key_index, model, error)

    logger.warning("Gemini text fallback exhausted; returning default")
    return default
