import sys

import pytest

from lslbot.router import RouterError, RouterResult


def _import_server(monkeypatch, tmp_path, shared_secret=None):
    # Run from an empty directory so a developer's real .env can't leak in.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("PRIMARY_PROVIDERS", "openai")
    monkeypatch.setenv("STATE_FILE", str(tmp_path / "state.json"))
    monkeypatch.setenv("CONVERSATIONS_DIR", str(tmp_path / "conversations"))
    if shared_secret is None:
        monkeypatch.delenv("BOT_SHARED_SECRET", raising=False)
    else:
        monkeypatch.setenv("BOT_SHARED_SECRET", shared_secret)

    sys.modules.pop("lslbot.server", None)
    sys.modules.pop("lslbot.config", None)
    import lslbot.server as server

    return server


@pytest.fixture
def app_module(monkeypatch, tmp_path):
    return _import_server(monkeypatch, tmp_path)


@pytest.fixture
def secured_app_module(monkeypatch, tmp_path):
    server = _import_server(monkeypatch, tmp_path, shared_secret="s3cret")
    server.router = StubRouter(
        result=RouterResult(text="reply", provider="openai", handover=False, attempts=[])
    )
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


def test_chat_rejects_missing_secret_when_one_is_configured(secured_app_module):
    client = secured_app_module.app.test_client()
    resp = client.post("/chat", json={"message": "hi"})
    assert resp.status_code == 401


def test_chat_rejects_wrong_secret(secured_app_module):
    client = secured_app_module.app.test_client()
    resp = client.post("/chat", json={"message": "hi"}, headers={"X-Bot-Secret": "guess"})
    assert resp.status_code == 401


def test_chat_accepts_correct_secret(secured_app_module):
    client = secured_app_module.app.test_client()
    resp = client.post("/chat", json={"message": "hi"}, headers={"X-Bot-Secret": "s3cret"})
    assert resp.status_code == 200
    assert resp.get_json()["reply"] == "reply"


def test_status_requires_secret_too(secured_app_module):
    client = secured_app_module.app.test_client()
    assert client.get("/status").status_code == 401
    assert client.get("/status", headers={"X-Bot-Secret": "s3cret"}).status_code == 200


def test_health_stays_open_for_liveness_checks(secured_app_module):
    client = secured_app_module.app.test_client()
    assert client.get("/health").status_code == 200


# --- chat page and its conversation API -------------------------------------

def test_chat_page_is_served_without_the_secret(secured_app_module):
    client = secured_app_module.app.test_client()
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"<html" in resp.data.lower()
    assert "script-src 'self'" in resp.headers["Content-Security-Policy"]


def test_conversation_api_requires_the_secret(secured_app_module):
    client = secured_app_module.app.test_client()
    assert client.get("/api/conversations").status_code == 401
    assert client.get("/api/conversations", headers={"X-Bot-Secret": "s3cret"}).status_code == 200


def test_sending_a_message_uses_the_whole_conversation(app_module):
    app_module.router = StubRouter(
        result=RouterResult(text="first answer", provider="openai", handover=False, attempts=[])
    )
    client = app_module.app.test_client()
    conversation = client.post("/api/conversations", json={}).get_json()

    first = client.post(f"/api/conversations/{conversation['id']}/messages", json={"content": "hello"})
    assert first.status_code == 200
    assert app_module.router.messages_seen == [{"role": "user", "content": "hello"}]

    app_module.router = StubRouter(
        result=RouterResult(text="second answer", provider="ollama", handover=True, attempts=[])
    )
    second = client.post(f"/api/conversations/{conversation['id']}/messages", json={"content": "and then?"})
    body = second.get_json()

    assert app_module.router.messages_seen == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "first answer"},
        {"role": "user", "content": "and then?"},
    ]
    assert body["handover"] is True
    assert [m.get("provider") for m in body["conversation"]["messages"]] == [None, "openai", None, "ollama"]
    assert body["conversation"]["title"] == "hello"


def test_imported_chat_is_sent_as_context(app_module):
    app_module.router = StubRouter(result=RouterResult(text="ok", provider="ollama", handover=True, attempts=[]))
    client = app_module.app.test_client()
    conversation = client.post(
        "/api/conversations", json={"imported_text": "You: help me write a CV", "source": "Claude"}
    ).get_json()

    client.post(f"/api/conversations/{conversation['id']}/messages", json={"content": "continue"})

    context, question = app_module.router.messages_seen
    assert context["role"] == "system" and "help me write a CV" in context["content"]
    assert question == {"role": "user", "content": "continue"}


def test_failed_reply_stores_nothing_so_it_can_be_retried(app_module):
    app_module.router = StubRouter(error=RouterError("all down"))
    client = app_module.app.test_client()
    conversation = client.post("/api/conversations", json={}).get_json()

    resp = client.post(f"/api/conversations/{conversation['id']}/messages", json={"content": "hi"})

    assert resp.status_code == 503
    stored = client.get(f"/api/conversations/{conversation['id']}").get_json()
    assert stored["messages"] == []


def test_unknown_or_malformed_conversation_ids_are_404(app_module):
    client = app_module.app.test_client()
    for bad_id in ["0" * 32, "..%2F..%2Fstate", "not-an-id"]:
        assert client.get(f"/api/conversations/{bad_id}").status_code == 404
        assert client.delete(f"/api/conversations/{bad_id}").status_code == 404
        assert client.post(f"/api/conversations/{bad_id}/messages", json={"content": "x"}).status_code == 404


def test_list_and_delete_conversations(app_module):
    client = app_module.app.test_client()
    a = client.post("/api/conversations", json={}).get_json()
    b = client.post("/api/conversations", json={}).get_json()
    assert {c["id"] for c in client.get("/api/conversations").get_json()} == {a["id"], b["id"]}

    assert client.delete(f"/api/conversations/{a['id']}").status_code == 204
    assert [c["id"] for c in client.get("/api/conversations").get_json()] == [b["id"]]


# --- OpenAI-compatible API ----------------------------------------------------

def test_openai_compatible_chat_completion(app_module):
    app_module.router = StubRouter(result=RouterResult(text="hi there", provider="ollama", handover=True, attempts=[]))
    client = app_module.app.test_client()

    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o",
            "messages": [
                {"role": "developer", "content": "be brief"},
                {"role": "user", "content": [{"type": "text", "text": "hel"}, {"type": "text", "text": "lo"}]},
                {"role": "assistant", "content": None, "tool_calls": [{"id": "1"}]},
                {"role": "tool", "content": "tool output", "tool_call_id": "1"},
            ],
        },
    )

    body = resp.get_json()
    assert resp.status_code == 200
    assert body["object"] == "chat.completion"
    assert body["model"] == "lslbot/ollama"
    assert body["choices"][0]["message"] == {"role": "assistant", "content": "hi there"}
    assert app_module.router.messages_seen == [
        {"role": "system", "content": "be brief"},
        {"role": "user", "content": "hello"},
    ]


def test_openai_compatible_streaming(app_module):
    app_module.router = StubRouter(result=RouterResult(text="streamed", provider="openai", handover=False, attempts=[]))
    client = app_module.app.test_client()

    resp = client.post("/v1/chat/completions", json={"stream": True, "messages": [{"role": "user", "content": "hi"}]})

    assert resp.mimetype == "text/event-stream"
    events = [line[len("data: "):] for line in resp.get_data(as_text=True).splitlines() if line.startswith("data: ")]
    assert events[-1] == "[DONE]"
    import json as _json
    first = _json.loads(events[0])
    assert first["choices"][0]["delta"] == {"role": "assistant", "content": "streamed"}
    assert _json.loads(events[1])["choices"][0]["finish_reason"] == "stop"


def test_openai_compatible_errors(app_module):
    client = app_module.app.test_client()
    bad = client.post("/v1/chat/completions", json={"messages": []})
    assert bad.status_code == 400 and bad.get_json()["error"]["type"] == "invalid_request_error"

    app_module.router = StubRouter(error=RouterError("all down"))
    down = client.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "hi"}]})
    assert down.status_code == 503 and "all down" not in down.get_data(as_text=True)


def test_openai_clients_authenticate_with_a_bearer_key(secured_app_module):
    client = secured_app_module.app.test_client()
    assert client.get("/v1/models").status_code == 401
    assert client.get("/v1/models", headers={"Authorization": "Bearer wrong"}).status_code == 401
    ok = client.get("/v1/models", headers={"Authorization": "Bearer s3cret"})
    assert ok.status_code == 200 and ok.get_json()["data"][0]["id"] == "lslbot"
