import os

from lslbot.conversations import DEFAULT_TITLE, ConversationStore


def test_create_get_list_and_delete(tmp_path):
    store = ConversationStore(str(tmp_path / "conversations"))
    assert store.list() == []

    conversation = store.create()
    assert conversation["title"] == DEFAULT_TITLE
    assert store.get(conversation["id"]) == conversation
    assert [c["id"] for c in store.list()] == [conversation["id"]]

    assert store.delete(conversation["id"]) is True
    assert store.get(conversation["id"]) is None
    assert store.delete(conversation["id"]) is False


def test_add_exchange_keeps_history_and_titles_from_first_message(tmp_path):
    store = ConversationStore(str(tmp_path))
    conversation = store.create()

    store.add_exchange(conversation["id"], "Plan my week\nwith details", "Sure!", "openai")
    updated = store.add_exchange(conversation["id"], "Now Friday only", "Friday: ...", "ollama")

    assert updated["title"] == "Plan my week"
    assert [(m["role"], m.get("provider")) for m in updated["messages"]] == [
        ("user", None),
        ("assistant", "openai"),
        ("user", None),
        ("assistant", "ollama"),
    ]
    assert store.history(updated) == [
        {"role": "user", "content": "Plan my week\nwith details"},
        {"role": "assistant", "content": "Sure!"},
        {"role": "user", "content": "Now Friday only"},
        {"role": "assistant", "content": "Friday: ..."},
    ]


def test_imported_transcript_becomes_context_for_the_next_reply(tmp_path):
    store = ConversationStore(str(tmp_path))
    conversation = store.create("You: fix my essay\nChatGPT: here is a draft...", "ChatGPT")

    assert conversation["title"].startswith("From ChatGPT: You: fix my essay")
    [stored] = conversation["messages"]
    assert stored["imported_from"] == "ChatGPT"
    assert stored["content"] == "You: fix my essay\nChatGPT: here is a draft..."

    [context] = store.history(conversation)
    assert context["role"] == "system"
    assert "started in ChatGPT" in context["content"]
    assert "here is a draft..." in context["content"]


def test_ids_that_are_not_ours_never_become_paths(tmp_path):
    store = ConversationStore(str(tmp_path / "conversations"))
    outside = tmp_path / "secret.json"
    outside.write_text('{"id": "x"}')

    for bad_id in ["../secret", "..%2Fsecret", "/etc/passwd", "", "ABCDEF" * 6, "g" * 32]:
        assert store.get(bad_id) is None
        assert store.delete(bad_id) is False
        assert store.add_exchange(bad_id, "hi", "hello", "openai") is None
    assert outside.exists()


def test_writes_leave_no_temp_files(tmp_path):
    store = ConversationStore(str(tmp_path))
    conversation = store.create()
    store.add_exchange(conversation["id"], "hi", "hello", "anthropic")
    assert sorted(os.listdir(tmp_path)) == [f"{conversation['id']}.json"]


def test_a_conversation_keeps_its_task_and_the_model_behind_each_reply(tmp_path):
    store = ConversationStore(str(tmp_path))
    conversation = store.create(task="mesh")
    assert conversation["task"] == "mesh"
    assert store.create()["task"] == "general"

    assert store.set_task(conversation["id"], "lsl")["task"] == "lsl"
    assert store.get(conversation["id"])["task"] == "lsl"
    assert store.set_task("0" * 32, "lsl") is None

    updated = store.add_exchange(conversation["id"], "a door script", "Here it is", "ollama", "qwen3-coder:30b")
    assert updated["messages"][-1]["model"] == "qwen3-coder:30b"
    no_model = store.add_exchange(conversation["id"], "thanks", "You're welcome", "openai")
    assert "model" not in no_model["messages"][-1]
