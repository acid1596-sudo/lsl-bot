from typing import List, Optional

import anthropic
from anthropic import Anthropic

from .base import Message, Provider, ProviderError, UsageExhaustedError
from ._util import parse_retry_after


class AnthropicProvider(Provider):
    """Talks to Claude via the official Anthropic API."""

    name = "anthropic"
    DEFAULT_MODEL = "claude-opus-5-5"

    # Long enough to finish a complete script, and still within what the SDK
    # allows without streaming.
    DEFAULT_MAX_TOKENS = 16000

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, max_tokens: int = DEFAULT_MAX_TOKENS):
        if not api_key:
            raise ProviderError("ANTHROPIC_API_KEY is not set")
        self.model = model
        self.max_tokens = max_tokens
        self._client = Anthropic(api_key=api_key, max_retries=0)

    def generate(self, messages: List[Message], model: Optional[str] = None) -> str:
        system, turns = _split_system_prompt(messages)
        request = {"model": model or self.model, "max_tokens": self.max_tokens, "messages": turns}
        if system:
            request["system"] = system
        try:
            response = self._client.messages.create(**request)
        except anthropic.RateLimitError as exc:
            retry_after = parse_retry_after(getattr(exc.response, "headers", None))
            raise UsageExhaustedError(str(exc), retry_after=retry_after) from exc
        except anthropic.APIStatusError as exc:
            raise ProviderError(f"Anthropic request failed ({exc.status_code}): {exc}") from exc
        except anthropic.AnthropicError as exc:
            raise ProviderError(f"Anthropic request failed: {exc}") from exc

        return "".join(block.text for block in response.content if block.type == "text")


def _split_system_prompt(messages: List[Message]):
    """Claude takes the system prompt as a separate field rather than a
    "system" message in the list, unlike OpenAI/Ollama's convention."""
    system_parts = [m["content"] for m in messages if m.get("role") == "system"]
    turns = [m for m in messages if m.get("role") != "system"]
    return "\n".join(system_parts), turns
