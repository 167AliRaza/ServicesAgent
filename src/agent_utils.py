"""Small helpers shared by workflow agents."""
from __future__ import annotations

from typing import Any


def add_log(state: dict, message: str) -> list[str]:
    return [*state.get("logs", []), message]


def append_message(state: dict, role: str, content: str) -> list[dict[str, str]]:
    return [*state.get("messages", []), {"role": role, "content": content}]


def message_role(message: Any) -> str:
    if isinstance(message, dict):
        return message.get("role", "")
    return getattr(message, "type", "")


def message_content(message: Any) -> str:
    if isinstance(message, dict):
        return message.get("content", "")
    return getattr(message, "content", "")


def last_user_message(messages: list[Any]) -> str:
    for message in reversed(messages):
        if message_role(message) in ("user", "human"):
            return message_content(message)
    return ""


def assistant_messages(messages: list[Any]) -> list[dict[str, str]]:
    output = []
    for message in messages:
        role = message_role(message)
        if role in ("user", "assistant", "human", "ai"):
            output.append(
                {
                    "role": "user" if role == "human" else "assistant" if role == "ai" else role,
                    "content": message_content(message),
                }
            )
    return output
