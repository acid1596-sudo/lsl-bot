import os
from typing import List

from .ollama_host import configured_url
from .providers import AnthropicProvider, OllamaProvider, OpenAIProvider, Provider
from .router import FailoverRouter

_PRIMARY_PROVIDER_FACTORIES = {
    "openai": lambda: OpenAIProvider(
        api_key=os.environ.get("OPENAI_API_KEY", ""),
        model=os.environ.get("OPENAI_MODEL") or OpenAIProvider.DEFAULT_MODEL,
    ),
    "anthropic": lambda: AnthropicProvider(
        api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
        model=os.environ.get("ANTHROPIC_MODEL") or AnthropicProvider.DEFAULT_MODEL,
        max_tokens=int(os.environ.get("ANTHROPIC_MAX_TOKENS") or 1024),
    ),
}


def build_router_from_env() -> FailoverRouter:
    """Build a FailoverRouter from environment variables (see .env.example)."""
    names = [n.strip() for n in os.environ.get("PRIMARY_PROVIDERS", "openai,anthropic").split(",") if n.strip()]
    if not names:
        raise ValueError("PRIMARY_PROVIDERS must list at least one provider")

    primaries: List[Provider] = []
    for name in names:
        factory = _PRIMARY_PROVIDER_FACTORIES.get(name)
        if factory is None:
            raise ValueError(
                f"unknown provider {name!r} in PRIMARY_PROVIDERS (expected one of "
                f"{sorted(_PRIMARY_PROVIDER_FACTORIES)})"
            )
        primaries.append(factory())

    fallback = OllamaProvider(
        host=configured_url(),
        model=os.environ.get("OLLAMA_MODEL") or "llama3",
        num_ctx=int(os.environ.get("OLLAMA_NUM_CTX") or 8192),
        timeout=float(os.environ.get("OLLAMA_TIMEOUT") or 600),
    )

    state_file = os.environ.get("STATE_FILE", "./data/provider_state.json").strip()

    return FailoverRouter(
        primary_providers=primaries,
        fallback_provider=fallback,
        default_cooldown=float(os.environ.get("DEFAULT_COOLDOWN_SECONDS", "60")),
        max_cooldown=float(os.environ.get("MAX_COOLDOWN_SECONDS", "3600")),
        backoff_multiplier=float(os.environ.get("BACKOFF_MULTIPLIER", "2.0")),
        state_path=state_file or None,
    )
