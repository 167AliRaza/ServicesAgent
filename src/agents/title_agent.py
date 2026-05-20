"""Generate a short thread title from the first user message using Gemini."""
from pydantic import BaseModel, Field

from src.llm import generate_json


class TitleOutput(BaseModel):
    title: str = Field(description="A concise title of at most 5 words summarizing the service request.")


async def generate_title(first_message: str) -> str:
    """Call Gemini to produce a short title. Falls back to truncation on failure."""
    parsed = generate_json(
        f'Summarize this service request in at most 5 words as a short title:\n"{first_message}"',
        TitleOutput,
        {"title": first_message[:40]},
    )
    return parsed.get("title", first_message[:40])[:60]
