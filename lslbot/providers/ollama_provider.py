import re
import threading
import time
from typing import Dict, List, Optional, Tuple

import requests

from ..ollama_host import DEFAULT_URL, ollama_url
from .base import Message, Provider, ProviderError

# Local models tend to answer with an outline, part of the work or a question
# back where ChatGPT and Claude would just do the job, so they're told to.
INSTRUCTIONS = (
    "You may be taking over this conversation from ChatGPT or Claude, and should work as well as they "
    "would. Carry on exactly where the conversation stands and do the whole job: when something is asked "
    "for, deliver it complete - full code, full scripts, full text - rather than an outline, a partial "
    "version or a question back, unless something essential is missing."
)

# Tokens kept free in the context window for the reply itself.
_REPLY_ROOM = 4096
# Some thinking models put their reasoning in the reply; only the answer is kept.
_THINKING = re.compile(r"^\s*<think>.*?</think>\s*", re.S)
_OWN_NUM_CTX = re.compile(r"^num_ctx\s+(\d+)\s*$", re.M)
_BAD_ADDRESS = (requests.exceptions.InvalidSchema, requests.exceptions.InvalidURL)


def _error_text(response) -> str:
    try:
        return str(response.json().get("error") or response.text)[:300]
    except ValueError:
        return response.text[:300] or f"HTTP {response.status_code}"


def _estimated_tokens(messages: List[Message]) -> int:
    # About 3 characters a token errs on the big side for code-heavy chats,
    # which costs a little memory rather than silently losing the start.
    return sum(len(m.get("content") or "") for m in messages) // 3 + 4 * len(messages)


def _one_system_message(messages: List[Message]) -> List[Message]:
    """Our instructions, the task's and any others as a single leading system
    message, because some model templates only use one system prompt."""
    system = [INSTRUCTIONS] + [m["content"] for m in messages if m.get("role") == "system"]
    turns = [m for m in messages if m.get("role") != "system"]
    return [{"role": "system", "content": "\n\n".join(system)}] + turns


class OllamaProvider(Provider):
    """Talks to a local Ollama server. This is the fallback: a local model has
    no usage cap to run out of, so it never raises UsageExhaustedError - only
    ProviderError, worded so the person at the chat page can act on it.
    """

    name = "ollama"
    # Seconds the list of installed models is reused; the status bar asks often.
    MODELS_MAX_AGE = 10.0

    def __init__(
        self,
        host: str = DEFAULT_URL,
        model: str = "llama3",
        num_ctx: int = 8192,
        max_ctx: int = 32768,
        timeout: float = 600.0,
    ):
        self.host = ollama_url(host)
        self.model = model
        self.num_ctx = num_ctx
        self.max_ctx = max(max_ctx, num_ctx)
        self.timeout = timeout
        self._lock = threading.Lock()
        self._installed: Optional[Tuple[float, Optional[List[dict]]]] = None
        self._windows: Dict[str, Tuple[Optional[int], Optional[int]]] = {}

    def generate(self, messages: List[Message], model: Optional[str] = None) -> str:
        model = model or self.model
        messages = _one_system_message(messages)
        try:
            response = requests.post(
                f"{self.host}/api/chat",
                json={
                    "model": model,
                    "messages": messages,
                    "stream": False,
                    # Ollama's default window is small and it silently drops
                    # the start of anything longer - exactly the history a
                    # handed-over task needs to continue.
                    "options": {"num_ctx": self.context_window(model, messages)},
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
        except _BAD_ADDRESS as exc:
            raise ProviderError(f"{self.host} isn't an address the bot can use - check OLLAMA_HOST") from exc
        except requests.RequestException as exc:
            raise ProviderError(f"Ollama request failed: {exc}") from exc

        if response.status_code >= 400:
            raise ProviderError(f"Ollama said: {_error_text(response)}")
        try:
            content = response.json()["message"]["content"]
        except (ValueError, KeyError, TypeError) as exc:
            raise ProviderError(f"{self.host} answered, but not like Ollama does - is OLLAMA_HOST right?") from exc
        answer = _THINKING.sub("", content, count=1) if isinstance(content, str) else ""
        if not answer.strip():
            raise ProviderError(f"{model} gave an empty answer. Try again, or pick another Ollama model for this task.")
        return answer

    def context_window(self, model: str, messages: List[Message]) -> int:
        """The smallest window that holds the conversation plus a reply,
        doubling from the usual size up to the model's own maximum and
        OLLAMA_MAX_CTX. A new size makes Ollama reload the model, so it
        grows in a few big steps rather than every message."""
        start, limit = self._window_limits(model)
        needed = _estimated_tokens(messages) + _REPLY_ROOM
        window = start
        while window < needed and window < limit:
            window = min(window * 2, limit)
        return window

    def installed_models(self) -> Optional[List[dict]]:
        """The models Ollama has, as {"name", "size"}, or None if it can't be asked."""
        now = time.monotonic()
        with self._lock:
            if self._installed and now - self._installed[0] < self.MODELS_MAX_AGE:
                return self._installed[1]
        try:
            response = requests.get(f"{self.host}/api/tags", timeout=3)
            response.raise_for_status()
            models = [
                {"name": m["name"], "size": m.get("size") or 0}
                for m in response.json().get("models") or []
                if isinstance(m, dict) and isinstance(m.get("name"), str)
            ]
        except (requests.RequestException, ValueError, AttributeError, TypeError):
            models = None
        with self._lock:
            self._installed = (now, models)
        return models

    def health(self, model: Optional[str] = None) -> dict:
        model = model or self.model
        try:
            response = requests.get(f"{self.host}/api/tags", timeout=3)
            response.raise_for_status()
            installed = {m.get("name") for m in response.json().get("models") or [] if isinstance(m, dict)}
        except _BAD_ADDRESS:
            return {"available": False, "problem": f"{self.host} isn't an address the bot can use - check OLLAMA_HOST"}
        except (requests.RequestException, ValueError, AttributeError, TypeError):
            return {"available": False, "problem": f"Ollama isn't reachable at {self.host}"}
        wanted = model if ":" in model else f"{model}:latest"
        if wanted not in installed:
            return {
                "available": False,
                "problem": f"Ollama doesn't have the model '{model}' yet - run: ollama pull {model}",
            }
        return {"available": True, "problem": None}

    def _window_limits(self, model: str) -> Tuple[int, int]:
        with self._lock:
            known = self._windows.get(model)
        if known is None:
            known = self._ask_window(model)
            if known is not None:
                with self._lock:
                    self._windows[model] = known
        own_setting, trained = known or (None, None)
        # A model made with its own num_ctx (say a 64k Continue model) keeps it.
        start = max(own_setting or 0, self.num_ctx)
        return start, max(start, min(trained or start, self.max_ctx))

    def _ask_window(self, model: str) -> Optional[Tuple[Optional[int], Optional[int]]]:
        """(the model's own num_ctx setting, the most it was trained for)
        from Ollama, or None if Ollama can't say right now."""
        try:
            response = requests.post(f"{self.host}/api/show", json={"model": model}, timeout=5)
            response.raise_for_status()
            data = response.json()
            trained = next(
                (v for k, v in (data.get("model_info") or {}).items() if k.endswith(".context_length") and isinstance(v, int)),
                None,
            )
            own = _OWN_NUM_CTX.search(data.get("parameters") or "")
        except (requests.RequestException, ValueError, AttributeError, TypeError):
            return None
        return (int(own.group(1)) if own else None, trained)
