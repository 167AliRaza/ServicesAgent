# Placeholder shim for google.genai module

class _Models:
    def generate_content(self, *args, **kwargs):
        # In production, this would call the real Gemini API.
        # For test environments, this method will be patched.
        raise NotImplementedError("Google Generative AI client not configured.")

class Client:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key
        self.models = _Models()

class _Types:
    class GenerateContentConfig:
        def __init__(self, **kwargs):
            # Store config parameters if needed.
            self.__dict__.update(kwargs)

# Expose a "types" namespace similar to the real library.
class types(_Types):
    pass

__all__ = ["Client", "types"]
