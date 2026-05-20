import os
import unittest
from unittest.mock import patch

from pydantic import BaseModel

from src.config import get_gemini_api_keys, get_gemini_models
from src.llm import generate_json, generate_text


class ExampleOutput(BaseModel):
    value: str


class MockResponse:
    def __init__(self, text: str):
        self.text = text


class MockApiError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


class SequencedModels:
    def __init__(self, responses: list):
        self.responses = responses
        self.calls = []

    def generate_content(self, model, contents, config=None):
        self.calls.append({"model": model, "contents": contents, "config": config})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class SequencedClient:
    created_keys = []
    models = None

    def __init__(self, api_key=None):
        self.created_keys.append(api_key)
        self.models = self.__class__.models


class LlmFallbackTests(unittest.TestCase):
    def setUp(self):
        self.saved_env = {
            key: os.environ.get(key)
            for key in ("GEMINI_API_KEY", "GEMINI_API_KEYS", "GEMINI_MODEL", "GEMINI_MODELS")
        }
        for key in self.saved_env:
            os.environ.pop(key, None)
        SequencedClient.created_keys = []
        SequencedClient.models = None

    def tearDown(self):
        for key, value in self.saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_config_parses_legacy_single_values(self):
        os.environ["GEMINI_API_KEY"] = "primary"
        os.environ["GEMINI_MODEL"] = "gemini-one"

        self.assertEqual(get_gemini_api_keys(), ["primary"])
        self.assertEqual(get_gemini_models(), ["gemini-one"])

    def test_config_parses_csv_values(self):
        os.environ["GEMINI_API_KEYS"] = " primary, fallback ,, "
        os.environ["GEMINI_MODELS"] = " model-a, model-b ,, "

        self.assertEqual(get_gemini_api_keys(), ["primary", "fallback"])
        self.assertEqual(get_gemini_models(), ["model-a", "model-b"])

    def test_generate_json_falls_back_after_quota_error(self):
        os.environ["GEMINI_API_KEYS"] = "key-one,key-two"
        os.environ["GEMINI_MODELS"] = "model-a"
        SequencedClient.models = SequencedModels(
            [
                MockApiError(429, "quota exceeded"),
                MockResponse('{"value": "ok"}'),
            ]
        )

        with patch("src.llm.genai.Client", SequencedClient):
            result = generate_json("prompt", ExampleOutput, {"value": "default"})

        self.assertEqual(result, {"value": "ok"})
        self.assertEqual(SequencedClient.created_keys, ["key-one", "key-two"])
        self.assertEqual([call["model"] for call in SequencedClient.models.calls], ["model-a", "model-a"])

    def test_generate_json_invalid_response_uses_next_fallback_then_default(self):
        os.environ["GEMINI_API_KEY"] = "key-one"
        os.environ["GEMINI_MODELS"] = "model-a,model-b"
        SequencedClient.models = SequencedModels(
            [
                MockResponse("not-json"),
                MockResponse('["not", "object"]'),
            ]
        )

        with patch("src.llm.genai.Client", SequencedClient):
            result = generate_json("prompt", ExampleOutput, {"value": "default"})

        self.assertEqual(result, {"value": "default"})
        self.assertEqual([call["model"] for call in SequencedClient.models.calls], ["model-a", "model-b"])

    def test_generate_text_falls_back_after_api_error(self):
        os.environ["GEMINI_API_KEY"] = "key-one"
        os.environ["GEMINI_MODELS"] = "model-a,model-b"
        SequencedClient.models = SequencedModels(
            [
                MockApiError(500, "server error"),
                MockResponse("fallback text"),
            ]
        )

        with patch("src.llm.genai.Client", SequencedClient):
            result = generate_text("prompt", "default text")

        self.assertEqual(result, "fallback text")
        self.assertEqual([call["model"] for call in SequencedClient.models.calls], ["model-a", "model-b"])

    def test_generate_text_blank_response_returns_default_after_exhaustion(self):
        os.environ["GEMINI_API_KEY"] = "key-one"
        os.environ["GEMINI_MODEL"] = "model-a"
        SequencedClient.models = SequencedModels([MockResponse("  ")])

        with patch("src.llm.genai.Client", SequencedClient):
            result = generate_text("prompt", "default text")

        self.assertEqual(result, "default text")
