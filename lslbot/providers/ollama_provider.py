from typing import List

import requests

from ..ollama_host import DEFAULT_URL, ollama_url
from .base import Message, Provider, ProviderError


def _error_text(response) -> str:
    try:
        return str(response.json().get("error") or response.text)[:300]
    except ValueError:
        return response.text[:300] or f"HTTP {response.status_code}"


class OllamaProvider(Provider):
    """Talks to a local Ollama server. This is the fallback: a local model has
    no usage cap to run out of, so it never raises UsageExhaustedError - only
    ProviderError, worded so the person at the chat page can act on it.
    """

    name = "ollama"

    def __init__(
        self,
        host: str = DEFAULT_URL,
        model: str = "llama3",
        num_ctx: int = 8192,
        timeout: float = 600.0,
    ):
        self.host = ollama_url(host)
        self.model = model
        self.num_ctx = num_ctx
        self.timeout = timeout

    def generate(self, messages: List[Message]) -> str:
        try:
            response = requests.post(
                f"{self.host}/api/chat",
                json={
                    "model": self.model,
                    "messages": messages,
                    "stream": False,
                    # Ollama's default window is small and it silently drops
                    # the start of anything longer - exactly the history a
                    # handed-over task needs to continue.
                    "options": {"num_ctx": self.num_ctx},
                },
                timeout=self.timeout,
            )
        except requests.ConnectTimeout as exc:
            raise ProviderError(f"Ollama isn't reachable at {self.host}") from exc
        except requests.ReadTimeout as exc:
            raise ProviderError(
                f"Ollama took longer than {self.timeout:.0f}s to answer (raise OLLAMA_TIMEOUT for a slow PC)"
            ) from exc
        except requests.ConnectionError as exc:
            raise ProviderError(f"Ollama isn't reachable at {self.host}") from exc
        except (requests.exceptions.InvalidSchema, requests.exceptions.InvalidURL) as exc:
            raise ProviderError(f"{self.host} isn't an address the bot can use - check OLLAMA_HOST") from exc
        except requests.RequestException as exc:
            raise ProviderError(f"Ollama request failed: {exc}") from exc

        if response.status_code >= 400:
            raise ProviderError(f"Ollama said: {_error_text(response)}")
        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderError(f"{self.host} answered, but not like Ollama does - is OLLAMA_HOST right?") from exc
        return data.get("message", {}).get("content", "")

    def health(self) -> dict:
        try:
            response = requests.get(f"{self.host}/api/tags", timeout=3)
            response.raise_for_status()
            installed = {m.get("name") for m in response.json().get("models") or [] if isinstance(m, dict)}
        except (requests.exceptions.InvalidSchema, requests.exceptions.InvalidURL):
            return {"available": False, "problem": f"{self.host} isn't an address the bot can use - check OLLAMA_HOST"}
        except (requests.RequestException, ValueError, AttributeError, TypeError):
            return {"available": False, "problem": f"Ollama isn't reachable at {self.host}"}
        wanted = self.model if ":" in self.model else f"{self.model}:latest"
        if wanted not in installed:
            return {
                "available": False,
                "problem": f"Ollama doesn't have the model '{self.model}' yet - run: ollama pull {self.model}",
            }
        return {"available": True, "problem": None}
