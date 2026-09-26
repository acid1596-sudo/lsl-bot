from typing import List

import requests

from .base import Message, Provider, ProviderError


class OllamaProvider(Provider):
    """Talks to a local Ollama server. This is the fallback: a local model has
    no usage cap to run out of, so it never raises UsageExhaustedError - only
    ProviderError if the server can't be reached at all.
    """

    name = "ollama"

    def __init__(self, host: str = "http://localhost:11434", model: str = "llama3", timeout: float = 120.0):
        self.host = host.rstrip("/")
        self.model = model
        self.timeout = timeout

    def generate(self, messages: List[Message]) -> str:
        try:
            response = requests.post(
                f"{self.host}/api/chat",
                json={"model": self.model, "messages": messages, "stream": False},
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise ProviderError(f"Ollama request failed: {exc}") from exc

        data = response.json()
        return data.get("message", {}).get("content", "")
