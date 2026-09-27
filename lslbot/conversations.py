import json
import os
import re
import threading
import time
import uuid
from typing import List, Optional

from .providers.base import Message

_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
DEFAULT_TITLE = "New chat"
_IMPORT_CONTEXT = (
    "This conversation was started in {source} and is being continued here. "
    "Transcript so far:\n\n{transcript}\n\n"
    "Pick up exactly where it left off and keep helping with the same task."
)


def _title_from(text: str, limit: int = 60) -> str:
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    return first_line if len(first_line) <= limit else first_line[: limit - 3].rstrip() + "..."


class ConversationStore:
    """One JSON file per conversation. Every reply is generated from the whole
    stored history, which is what lets a conversation carry on unchanged when
    the router hands it from ChatGPT/Claude to Ollama and back."""

    def __init__(self, directory: str):
        self._dir = directory
        self._lock = threading.Lock()

    def list(self) -> List[dict]:
        if not os.path.isdir(self._dir):
            return []
        summaries = []
        for name in os.listdir(self._dir):
            conversation = self.get(name[: -len(".json")]) if name.endswith(".json") else None
            if conversation:
                summaries.append(
                    {"id": conversation["id"], "title": conversation["title"], "updated": conversation["updated"]}
                )
        return sorted(summaries, key=lambda c: c["updated"], reverse=True)

    def create(self, imported_text: str = "", source: str = "", task: str = "general") -> dict:
        now = time.time()
        conversation = {
            "id": uuid.uuid4().hex,
            "title": DEFAULT_TITLE,
            "task": task,
            "created": now,
            "updated": now,
            "messages": [],
        }
        if imported_text.strip():
            source = source.strip() or "another chat"
            conversation["title"] = f"From {source}: {_title_from(imported_text, 40)}"
            conversation["messages"].append(
                {"role": "system", "content": imported_text.strip(), "imported_from": source, "at": now}
            )
        with self._lock:
            self._write(conversation)
        return conversation

    def get(self, conversation_id: str) -> Optional[dict]:
        path = self._path(conversation_id)
        if path is None:
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None

    def set_task(self, conversation_id: str, task: str) -> Optional[dict]:
        with self._lock:
            conversation = self.get(conversation_id)
            if conversation is None:
                return None
            conversation["task"] = task
            self._write(conversation)
            return conversation

    def add_exchange(
        self, conversation_id: str, user_text: str, reply_text: str, provider: str, model: Optional[str] = None
    ) -> Optional[dict]:
        with self._lock:
            conversation = self.get(conversation_id)
            if conversation is None:
                return None
            now = time.time()
            if conversation["title"] == DEFAULT_TITLE:
                conversation["title"] = _title_from(user_text) or DEFAULT_TITLE
            conversation["messages"].append({"role": "user", "content": user_text, "at": now})
            reply = {"role": "assistant", "content": reply_text, "provider": provider, "at": now}
            if model:
                reply["model"] = model
            conversation["messages"].append(reply)
            conversation["updated"] = now
            self._write(conversation)
            return conversation

    def delete(self, conversation_id: str) -> bool:
        path = self._path(conversation_id)
        if path is None:
            return False
        with self._lock:
            try:
                os.remove(path)
            except FileNotFoundError:
                return False
        return True

    @staticmethod
    def history(conversation: dict) -> List[Message]:
        history = []
        for message in conversation["messages"]:
            content = message["content"]
            if message.get("imported_from"):
                content = _IMPORT_CONTEXT.format(source=message["imported_from"], transcript=content)
            history.append({"role": message["role"], "content": content})
        return history

    def _path(self, conversation_id: str) -> Optional[str]:
        # The id comes straight from the URL, so only our own hex ids may
        # become file names - nothing like "../../somewhere".
        if not isinstance(conversation_id, str) or not _ID_PATTERN.match(conversation_id):
            return None
        return os.path.join(self._dir, f"{conversation_id}.json")

    def _write(self, conversation: dict) -> None:
        os.makedirs(self._dir, exist_ok=True)
        path = self._path(conversation["id"])
        tmp_path = f"{path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(conversation, f, ensure_ascii=False)
        os.replace(tmp_path, path)
