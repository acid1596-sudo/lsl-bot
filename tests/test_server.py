import sys

import pytest

from lslbot.router import RouterError, RouterResult


@pytest.fixture
def app_module(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("PRIMARY_PROVIDERS", "openai")
    monkeypatch.setenv("STATE_FILE", str(tmp_path / "state.json"))

    sys.modules.pop("lslbot.server", None)
    sys.modules.pop("lslbot.config", None)
    import lslbot.server as server

    return server


class StubRouter:
    def __init__(self, result=None, error=None):
        self._result = result
        self._error = error
        self.messages_seen = None

    def generate(self, messages):
        self.messages_seen = messages
        if self._error:
            raise self._error
        return self._result

    def status(self):
        return {"active_provider": "ollama", "providers": {}}


def test_chat_endpoint_returns_router_result(app_module):
    app_module.router = StubRouter(
        result=RouterResult(text="stub reply", provider="ollama", handover=True, attempts=["x"])
    )
    client = app_module.app.test_client()

    resp = client.post("/chat", json={"message": "hello"})

    assert resp.status_code == 200
    assert resp.get_json() == {"reply": "stub reply", "provider": "ollama", "handover": True}
    assert app_module.router.messages_seen == [{"role": "user", "content": "hello"}]


def test_chat_endpoint_includes_history(app_module):
    app_module.router = StubRouter(
        result=RouterResult(text="reply", provider="openai", handover=False, attempts=[])
    )
    client = app_module.app.test_client()

    history = [{"role": "user", "content": "earlier"}, {"role": "assistant", "content": "ok"}]
    client.post("/chat", json={"message": "hello", "history": history})

    assert app_module.router.messages_seen == history + [{"role": "user", "content": "hello"}]


def test_chat_endpoint_requires_message(app_module):
    client = app_module.app.test_client()
    resp = client.post("/chat", json={})
    assert resp.status_code == 400


def test_chat_endpoint_returns_503_on_router_error(app_module):
    app_module.router = StubRouter(error=RouterError("everything is down"))
    client = app_module.app.test_client()

    resp = client.post("/chat", json={"message": "hi"})

    assert resp.status_code == 503
    assert "error" in resp.get_json()


def test_status_endpoint(app_module):
    app_module.router = StubRouter()
    client = app_module.app.test_client()

    resp = client.get("/status")

    assert resp.status_code == 200
    assert resp.get_json()["active_provider"] == "ollama"


def test_health_endpoint(app_module):
    client = app_module.app.test_client()
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True}
