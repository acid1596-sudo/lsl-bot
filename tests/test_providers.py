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
        status_code = 200

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


def test_ollama_asks_for_a_context_window_big_enough_for_the_history(monkeypatch):
    sent = {}

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"message": {"content": "ok"}}

    def fake_post(url, json=None, timeout=None):
        sent.update(json)
        return FakeResponse()

    monkeypatch.setattr("lslbot.providers.ollama_provider.requests.post", fake_post)
    OllamaProvider(num_ctx=16384).generate([{"role": "user", "content": "hi"}])
    assert sent["options"] == {"num_ctx": 16384}


class _Resp:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")


def test_ollama_passes_on_its_own_error_message(monkeypatch):
    monkeypatch.setattr(
        "lslbot.providers.ollama_provider.requests.post",
        lambda *a, **kw: _Resp(500, {"error": "model requires more system memory (5.6 GiB) than is available"}),
    )
    with pytest.raises(ProviderError) as exc_info:
        OllamaProvider().generate([])
    assert str(exc_info.value) == "Ollama said: model requires more system memory (5.6 GiB) than is available"


def test_ollama_timeout_says_how_to_fix_it(monkeypatch):
    def slow(*a, **kw):
        raise requests.ReadTimeout("read timed out")

    monkeypatch.setattr("lslbot.providers.ollama_provider.requests.post", slow)
    with pytest.raises(ProviderError) as exc_info:
        OllamaProvider(timeout=42).generate([])
    assert "took longer than 42s" in str(exc_info.value) and "OLLAMA_TIMEOUT" in str(exc_info.value)


def test_ollama_unreachable_names_the_address(monkeypatch):
    def refused(*a, **kw):
        raise requests.ConnectionError("refused")

    monkeypatch.setattr("lslbot.providers.ollama_provider.requests.post", refused)
    with pytest.raises(ProviderError) as exc_info:
        OllamaProvider(host="http://127.0.0.1:11434").generate([])
    assert str(exc_info.value) == "Ollama isn't reachable at http://127.0.0.1:11434"


def test_ollama_health(monkeypatch):
    target = "lslbot.providers.ollama_provider.requests.get"

    monkeypatch.setattr(target, lambda *a, **kw: _Resp(200, {"models": [{"name": "llama3:latest"}]}))
    assert OllamaProvider(model="llama3").health() == {"available": True, "problem": None}

    monkeypatch.setattr(target, lambda *a, **kw: _Resp(200, {"models": [{"name": "mistral:latest"}]}))
    missing = OllamaProvider(model="llama3").health()
    assert missing["available"] is False and "ollama pull llama3" in missing["problem"]

    def refused(*a, **kw):
        raise requests.ConnectionError("refused")

    monkeypatch.setattr(target, refused)
    down = OllamaProvider().health()
    assert down["available"] is False and "isn't reachable" in down["problem"]


def test_ollama_defaults_to_the_ipv4_loopback():
    # On Windows "localhost" can try IPv6 first and stall before falling back.
    assert OllamaProvider().host == "http://127.0.0.1:11434"


def test_ollama_host_written_for_the_ollama_server_still_reaches_it(monkeypatch):
    # OLLAMA_HOST=0.0.0.0:11434 tells Ollama to listen on every network; the
    # bot used to send that straight to requests, which can't connect to it.
    posted = []

    def fake_post(url, json=None, timeout=None):
        posted.append(url)
        return _Resp(200, {"message": {"content": "ok"}})

    monkeypatch.setattr("lslbot.providers.ollama_provider.requests.post", fake_post)
    assert OllamaProvider(host="0.0.0.0:11434").generate([]) == "ok"
    assert posted == ["http://127.0.0.1:11434/api/chat"]


def test_ollama_host_that_is_not_an_address_says_so():
    provider = OllamaProvider(host="tcp://myserver:11434")

    with pytest.raises(ProviderError) as exc_info:
        provider.generate([])
    assert str(exc_info.value) == "tcp://myserver:11434 isn't an address the bot can use - check OLLAMA_HOST"
    assert provider.health() == {
        "available": False,
        "problem": "tcp://myserver:11434 isn't an address the bot can use - check OLLAMA_HOST",
    }


def test_ollama_health_survives_a_reply_that_is_not_ollamas(monkeypatch):
    monkeypatch.setattr(
        "lslbot.providers.ollama_provider.requests.get", lambda *a, **kw: _Resp(200, {"models": 5})
    )
    assert OllamaProvider().health()["available"] is False
