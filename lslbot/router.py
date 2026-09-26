import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence

from .providers.base import Message, Provider, ProviderError, UsageExhaustedError

logger = logging.getLogger("lslbot.router")


class RouterError(Exception):
    """Every primary provider is cooling down or failing, and the fallback
    provider (Ollama) could not serve the request either."""


@dataclass
class ProviderState:
    # Last backoff delay applied because of a usage error with no server-given
    # Retry-After. Only this path escalates; a concrete Retry-After is trusted
    # as-is and does not feed the escalation.
    backoff: float = 0.0
    # Epoch seconds until which this provider is skipped. 0 means available.
    unavailable_until: float = 0.0


@dataclass
class RouterResult:
    text: str
    provider: str
    handover: bool
    attempts: List[str] = field(default_factory=list)


class FailoverRouter:
    """Routes a chat request to the first available provider in
    ``primary_providers`` order, falling back to ``fallback_provider`` when
    every primary is cooling down (or fails) for this call.

    A primary provider that raises ``UsageExhaustedError`` is put on a
    cooldown - the Retry-After it reports, or an exponentially growing
    default otherwise - and skipped by every call until the cooldown expires,
    at which point it is tried again automatically. The first successful call
    clears its cooldown, handing it tasks back with no manual step.
    """

    def __init__(
        self,
        primary_providers: Sequence[Provider],
        fallback_provider: Provider,
        default_cooldown: float = 60.0,
        max_cooldown: float = 3600.0,
        backoff_multiplier: float = 2.0,
        state_path: Optional[str] = None,
        clock: Callable[[], float] = time.time,
    ):
        if not primary_providers:
            raise ValueError("at least one primary provider is required")
        if fallback_provider is None:
            raise ValueError("a fallback provider is required")

        self._primary_providers = list(primary_providers)
        self._fallback = fallback_provider
        self.default_cooldown = default_cooldown
        self.max_cooldown = max_cooldown
        self.backoff_multiplier = backoff_multiplier
        self._state_path = state_path
        self._clock = clock

        self._lock = threading.Lock()
        self._state: Dict[str, ProviderState] = {}
        self._load_state()

    def generate(self, messages: List[Message]) -> RouterResult:
        with self._lock:
            now = self._clock()
            attempts: List[str] = []

            for provider in self._primary_providers:
                state = self._state.get(provider.name, ProviderState())
                if state.unavailable_until > now:
                    attempts.append(
                        f"{provider.name}: cooling down ({state.unavailable_until - now:.0f}s left)"
                    )
                    continue

                try:
                    text = provider.generate(messages)
                except UsageExhaustedError as exc:
                    self._on_exhausted(provider.name, exc.retry_after)
                    attempts.append(f"{provider.name}: usage exhausted - {exc}")
                    continue
                except ProviderError as exc:
                    attempts.append(f"{provider.name}: error - {exc}")
                    continue

                self._on_success(provider.name)
                return RouterResult(text=text, provider=provider.name, handover=False, attempts=attempts)

            try:
                text = self._fallback.generate(messages)
            except ProviderError as exc:
                attempts.append(f"{self._fallback.name}: error - {exc}")
                raise RouterError(
                    "every primary provider is unavailable and the fallback failed: "
                    + "; ".join(attempts)
                ) from exc

            attempts.append(f"{self._fallback.name}: ok")
            return RouterResult(text=text, provider=self._fallback.name, handover=True, attempts=attempts)

    def status(self) -> dict:
        with self._lock:
            now = self._clock()
            providers = {}
            for provider in self._primary_providers:
                state = self._state.get(provider.name, ProviderState())
                available = state.unavailable_until <= now
                providers[provider.name] = {
                    "role": "primary",
                    "available": available,
                    "retry_in_seconds": None if available else round(state.unavailable_until - now, 1),
                }
            providers[self._fallback.name] = {"role": "fallback", "available": True, "retry_in_seconds": None}

            active = next(
                (p.name for p in self._primary_providers if providers[p.name]["available"]),
                self._fallback.name,
            )
            return {"active_provider": active, "providers": providers}

    def _on_exhausted(self, name: str, retry_after: Optional[float]) -> None:
        state = self._state.setdefault(name, ProviderState())
        if retry_after is not None:
            delay = max(retry_after, 0.0)
        else:
            base = state.backoff if state.backoff > 0 else self.default_cooldown
            delay = min(base * self.backoff_multiplier, self.max_cooldown) if state.backoff > 0 else base
            state.backoff = delay
        state.unavailable_until = self._clock() + delay
        logger.warning(
            "provider %r out of usage, handing its tasks to %r for %.0fs",
            name, self._fallback.name, delay,
        )
        self._save_state()

    def _on_success(self, name: str) -> None:
        state = self._state.get(name)
        if state is not None and (state.unavailable_until > 0 or state.backoff > 0):
            logger.info("provider %r usage reset, handing its tasks back", name)
        self._state[name] = ProviderState()
        self._save_state()

    def _load_state(self) -> None:
        if not self._state_path:
            return
        try:
            with open(self._state_path, "r") as f:
                raw = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return
        for name, values in raw.items():
            self._state[name] = ProviderState(
                backoff=values.get("backoff", 0.0),
                unavailable_until=values.get("unavailable_until", 0.0),
            )

    def _save_state(self) -> None:
        if not self._state_path:
            return
        directory = os.path.dirname(self._state_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        tmp_path = f"{self._state_path}.tmp"
        payload = {
            name: {"backoff": s.backoff, "unavailable_until": s.unavailable_until}
            for name, s in self._state.items()
        }
        with open(tmp_path, "w") as f:
            json.dump(payload, f)
        os.replace(tmp_path, self._state_path)
