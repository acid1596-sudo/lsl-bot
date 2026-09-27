from abc import ABC, abstractmethod
from typing import Dict, List, Optional

Message = Dict[str, str]
"""A single chat turn, e.g. {"role": "user", "content": "hello"}."""


class ProviderError(Exception):
    """A provider call failed. Not necessarily related to usage/quota -
    e.g. a network error or an invalid request."""


class UsageExhaustedError(ProviderError):
    """The provider rejected the call specifically because the account is out of
    usage: a rate limit or a billing/quota cap. The router treats this
    differently from a generic ProviderError by putting the provider on a
    cooldown and routing subsequent tasks to the fallback provider until it
    expires.
    """

    def __init__(self, message: str, retry_after: Optional[float] = None):
        super().__init__(message)
        self.retry_after = retry_after
        """Seconds until the provider says it will accept requests again, when
        it told us via a Retry-After header. None means unknown - the caller
        should fall back to its own default/backoff cooldown."""


class Provider(ABC):
    """A backend that can turn a chat history into a reply.

    Implementations should raise UsageExhaustedError when the underlying
    service reports a rate limit or quota/billing cap, and ProviderError for
    any other failure (network error, bad request, etc). Any other exception
    is treated by the router as an unexpected bug, not a routing signal.
    """

    name: str

    @abstractmethod
    def generate(self, messages: List[Message]) -> str:
        """Return the assistant's reply text for the given message history."""
        raise NotImplementedError

    def health(self) -> dict:
        """Whether this provider looks usable right now, for the status bar.
        Cloud providers report usage problems through errors instead."""
        return {"available": True, "problem": None}
