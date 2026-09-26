import typing

import anthropic
import openai
import pytest
import requests

from lslbot.providers.anthropic_provider import AnthropicProvider
from lslbot.providers.base import ProviderError, UsageExhaustedError
from lslbot.providers.ollama_provider import OllamaProvider
from lslbot.providers.openai_provider import OpenAIProvider
from tests.conftest import FakeHTTPResponse


# --- OpenAI --------------------------------------------------------------

def test_openai_rate_limit_becomes_usage_exhausted_with_retry_after(monkeypatch):
    provider = OpenAIProvider(api_key="test-key")
    err = openai.RateLimitError(
        "you exceeded your quota",
        response=FakeHTTPResponse(status_code=429, headers={"retry-after": "42"}),
        body=None,
    )

    def raise_it(**kwargs):
        raise err

    monkeypatch.setattr(provider._client.chat.completions, "create", raise_it)

    with pytest.raises(UsageExhaustedError) as exc_info:
        provider.generate([{"role": "user", "content": "hi"}])
    assert exc_info.value.retry_after == pytest.approx(42.0)


def test_openai_rate_limit_without_header_has_no_retry_after(monkeypatch):
    provider = OpenAIProvider(api_key="test-key")
    err = openai.RateLimitError(
        "you exceeded your quota", response=FakeHTTPResponse(status_code=429), body=None
    )
    monkeypatch.setattr(provider._client.chat.completions, "create", lambda **kw: (_ for _ in ()).throw(err))

    with pytest.raises(UsageExhaustedError) as exc_info:
        provider.generate([])
    assert exc_info.value.retry_after is None


def test_openai_other_status_error_is_a_plain_provider_error(monkeypatch):
    provider = OpenAIProvider(api_key="test-key")
    err = openai.InternalServerError(
        "server exploded", response=FakeHTTPResponse(status_code=500), body=None
    )
    monkeypatch.setattr(provider._client.chat.completions, "create", lambda **kw: (_ for _ in ()).throw(err))

    with pytest.raises(ProviderError) as exc_info:
        provider.generate([])
    assert not isinstance(exc_info.value, UsageExhaustedError)
    assert "500" in str(exc_info.value)


def test_openai_returns_reply_text(monkeypatch):
    provider = OpenAIProvider(api_key="test-key")

    class Choice:
        class message:
            content = "hello!"

    class Response:
        choices = [Choice()]

    monkeypatch.setattr(provider._client.chat.completions, "create", lambda **kw: Response())
    assert provider.generate([{"role": "user", "content": "hi"}]) == "hello!"


def test_openai_missing_api_key_raises_immediately():
    with pytest.raises(ProviderError):
        OpenAIProvider(api_key="")


# --- Anthropic -------------------------------------------------------------

def test_anthropic_rate_limit_becomes_usage_exhausted_with_retry_after(monkeypatch):
    provider = AnthropicProvider(api_key="test-key")
    err = anthropic.RateLimitError(
        "rate limited",
        response=FakeHTTPResponse(status_code=429, headers={"retry-after": "17"}),
        body=None,
    )
    monkeypatch.setattr(provider._client.messages, "create", lambda **kw: (_ for _ in ()).throw(err))

    with pytest.raises(UsageExhaustedError) as exc_info:
        provider.generate([{"role": "user", "content": "hi"}])
    assert exc_info.value.retry_after == pytest.approx(17.0)


def test_anthropic_overloaded_is_a_plain_provider_error(monkeypatch):
    provider = AnthropicProvider(api_key="test-key")
    err = anthropic.OverloadedError(
        "overloaded", response=FakeHTTPResponse(status_code=529), body=None
    )
    monkeypatch.setattr(provider._client.messages, "create", lambda **kw: (_ for _ in ()).throw(err))

    with pytest.raises(ProviderError) as exc_info:
        provider.generate([])
    assert not isinstance(exc_info.value, UsageExhaustedError)


def test_anthropic_returns_first_text_block(monkeypatch):
    provider = AnthropicProvider(api_key="test-key")

    class Block:
        type = "text"
        text = "hi from claude"

    class Response:
        content = [Block()]

    monkeypatch.setattr(provider._client.messages, "create", lambda **kw: Response())
    assert provider.generate([{"role": "user", "content": "hi"}]) == "hi from claude"


def test_anthropic_splits_system_messages_out_of_the_turn_list(monkeypatch):
    provider = AnthropicProvider(api_key="test-key")
    captured = {}

    class Block:
        type = "text"
        text = "ok"

    class Response:
        content = [Block()]

    def fake_create(**kwargs):
        captured.update(kwargs)
        return Response()

    monkeypatch.setattr(provider._client.messages, "create", fake_create)
    provider.generate(
        [
            {"role": "system", "content": "be nice"},
            {"role": "user", "content": "hi"},
        ]
    )
    assert captured["system"] == "be nice"
    assert captured["messages"] == [{"role": "user", "content": "hi"}]


def test_anthropic_omits_system_field_when_there_is_no_system_prompt(monkeypatch):
    provider = AnthropicProvider(api_key="test-key")
    captured = {}

    class Block:
        type = "text"
        text = "ok"

    class Response:
        content = [Block()]

    def fake_create(**kwargs):
        captured.update(kwargs)
        return Response()

    monkeypatch.setattr(provider._client.messages, "create", fake_create)
    provider.generate([{"role": "user", "content": "hi"}])
    assert "system" not in captured


def test_anthropic_joins_every_text_block_and_skips_others(monkeypatch):
    provider = AnthropicProvider(api_key="test-key")

    class Thinking:
        type = "thinking"

    class Text:
        type = "text"

        def __init__(self, text):
            self.text = text

    class Response:
        content = [Thinking(), Text("Hello, "), Text("world")]

    monkeypatch.setattr(provider._client.messages, "create", lambda **kw: Response())
    assert provider.generate([{"role": "user", "content": "hi"}]) == "Hello, world"


def test_anthropic_default_model_is_one_the_sdk_still_knows():
    known_models = typing.get_args(typing.get_args(anthropic.types.Model)[0])
    assert AnthropicProvider(api_key="test-key").model in known_models


# --- Ollama ------------------------------------------------------------

def test_ollama_returns_reply_text(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"message": {"content": "local model reply"}}

    monkeypatch.setattr(
        "lslbot.providers.ollama_provider.requests.post", lambda *a, **kw: FakeResponse()
    )
    provider = OllamaProvider()
    assert provider.generate([{"role": "user", "content": "hi"}]) == "local model reply"


def test_ollama_non_json_reply_is_a_provider_error(monkeypatch):
    not_ollama = requests.Response()
    not_ollama.status_code = 200
    not_ollama._content = b"<html>this is not an Ollama server</html>"

    monkeypatch.setattr(
        "lslbot.providers.ollama_provider.requests.post", lambda *a, **kw: not_ollama
    )
    provider = OllamaProvider()

    with pytest.raises(ProviderError):
        provider.generate([])


def test_ollama_connection_failure_is_a_provider_error(monkeypatch):
    def raise_it(*a, **kw):
        raise requests.ConnectionError("no route to host")

    monkeypatch.setattr("lslbot.providers.ollama_provider.requests.post", raise_it)
    provider = OllamaProvider()

    with pytest.raises(ProviderError):
        provider.generate([])
