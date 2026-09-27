from typing import List, Optional

import openai
from openai import OpenAI

from .base import Message, Provider, ProviderError, UsageExhaustedError
from ._util import parse_retry_after


class OpenAIProvider(Provider):
    """Talks to ChatGPT via the official OpenAI API."""

    name = "openai"
    DEFAULT_MODEL = "gpt-4o-mini"

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL):
        if not api_key:
            raise ProviderError("OPENAI_API_KEY is not set")
        self.model = model
        self._client = OpenAI(api_key=api_key, max_retries=0)

    def generate(self, messages: List[Message], model: Optional[str] = None) -> str:
        try:
            response = self._client.chat.completions.create(
                model=model or self.model,
                messages=messages,
            )
        except openai.RateLimitError as exc:
            retry_after = parse_retry_after(getattr(exc.response, "headers", None))
            raise UsageExhaustedError(str(exc), retry_after=retry_after) from exc
        except openai.APIStatusError as exc:
            raise ProviderError(f"OpenAI request failed ({exc.status_code}): {exc}") from exc
        except openai.OpenAIError as exc:
            raise ProviderError(f"OpenAI request failed: {exc}") from exc

        choice = response.choices[0]
        return choice.message.content or ""
