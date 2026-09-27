import hmac
import json
import logging
import os
import time
import uuid

from dotenv import load_dotenv
from flask import Flask, Response, jsonify, request, send_from_directory

from .config import build_router_from_env
from .conversations import ConversationStore
from .router import RouterError

# Load .env before anything reads the environment, so every setting (LOG_LEVEL
# included) can live there. Real environment variables still win.
load_dotenv(".env", override=False)

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
logger = logging.getLogger("lslbot.server")

SHARED_SECRET = os.environ.get("BOT_SHARED_SECRET", "")
if not SHARED_SECRET:
    logger.warning(
        "BOT_SHARED_SECRET is not set: anyone who can reach this server can spend your API usage"
    )

NO_PROVIDER_ERROR = "no provider could answer right now"
PUBLIC_ENDPOINTS = {"health", "index", "static"}

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024
router = build_router_from_env()
store = ConversationStore(os.environ.get("CONVERSATIONS_DIR", "./data/conversations"))

_ROLES = {"system": "system", "developer": "system", "user": "user", "assistant": "assistant"}


def _supplied_secret() -> str:
    # X-Bot-Secret for the chat page and LSL; "Authorization: Bearer" because
    # that is where OpenAI-compatible clients put the API key.
    header = request.headers.get("X-Bot-Secret")
    if header:
        return header
    auth = request.headers.get("Authorization", "")
    return auth[len("Bearer "):] if auth.startswith("Bearer ") else ""


@app.before_request
def require_shared_secret():
    if not SHARED_SECRET or request.endpoint in PUBLIC_ENDPOINTS:
        return None
    if not hmac.compare_digest(_supplied_secret().encode(), SHARED_SECRET.encode()):
        return jsonify({"error": "unauthorized"}), 401
    return None


@app.after_request
def add_security_headers(response):
    # The chat page shows model output, which is untrusted text; this stops
    # the browser from running anything that was not served by this app.
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def _plain_messages(raw_messages) -> list:
    """Keep only text chat turns the providers understand: content given as
    a list of parts is flattened to its text, "developer" counts as system,
    and tool/function turns are dropped."""
    messages = []
    for message in raw_messages if isinstance(raw_messages, list) else []:
        if not isinstance(message, dict):
            continue
        role = _ROLES.get(message.get("role"))
        content = message.get("content")
        if isinstance(content, list):
            content = "".join(
                part.get("text", "") for part in content if isinstance(part, dict) and part.get("type") == "text"
            )
        if role and isinstance(content, str) and content:
            messages.append({"role": role, "content": content})
    return messages


def _generate(messages):
    try:
        return router.generate(messages)
    except RouterError as exc:
        # Provider errors can echo account details (e.g. a masked API key),
        # so they go to the server log, not back to the caller.
        logger.error("no provider could answer: %s", exc)
        return None


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/health")
def health():
    return jsonify({"ok": True})


@app.get("/status")
def status():
    return jsonify(router.status())


@app.post("/chat")
def chat():
    payload = request.get_json(silent=True) or {}
    message = payload.get("message")
    if not isinstance(message, str) or not message:
        return jsonify({"error": "'message' is required"}), 400

    result = _generate(_plain_messages(payload.get("history")) + [{"role": "user", "content": message}])
    if result is None:
        return jsonify({"error": NO_PROVIDER_ERROR}), 503
    return jsonify({"reply": result.text, "provider": result.provider, "handover": result.handover})


@app.get("/api/conversations")
def list_conversations():
    return jsonify(store.list())


@app.post("/api/conversations")
def create_conversation():
    payload = request.get_json(silent=True) or {}
    imported_text = payload.get("imported_text") or ""
    source = payload.get("source") or ""
    if not isinstance(imported_text, str) or not isinstance(source, str):
        return jsonify({"error": "'imported_text' and 'source' must be strings"}), 400
    return jsonify(store.create(imported_text, source[:40])), 201


@app.get("/api/conversations/<conversation_id>")
def get_conversation(conversation_id):
    conversation = store.get(conversation_id)
    if conversation is None:
        return jsonify({"error": "conversation not found"}), 404
    return jsonify(conversation)


@app.delete("/api/conversations/<conversation_id>")
def delete_conversation(conversation_id):
    if not store.delete(conversation_id):
        return jsonify({"error": "conversation not found"}), 404
    return "", 204


@app.post("/api/conversations/<conversation_id>/messages")
def send_message(conversation_id):
    conversation = store.get(conversation_id)
    if conversation is None:
        return jsonify({"error": "conversation not found"}), 404
    payload = request.get_json(silent=True) or {}
    content = payload.get("content")
    if not isinstance(content, str) or not content.strip():
        return jsonify({"error": "'content' is required"}), 400

    result = _generate(store.history(conversation) + [{"role": "user", "content": content}])
    if result is None:
        return jsonify({"error": NO_PROVIDER_ERROR}), 503
    updated = store.add_exchange(conversation_id, content, result.text, result.provider)
    if updated is None:
        return jsonify({"error": "conversation not found"}), 404
    return jsonify({"conversation": updated, "handover": result.handover})


def _openai_error(message: str, status_code: int, error_type: str):
    return jsonify({"error": {"message": message, "type": error_type}}), status_code


@app.get("/v1/models")
def openai_models():
    return jsonify({"object": "list", "data": [{"id": "lslbot", "object": "model", "owned_by": "lslbot"}]})


@app.post("/v1/chat/completions")
def openai_chat_completions():
    payload = request.get_json(silent=True) or {}
    messages = _plain_messages(payload.get("messages"))
    if not messages:
        return _openai_error("'messages' must contain at least one text message", 400, "invalid_request_error")

    result = _generate(messages)
    if result is None:
        return _openai_error(NO_PROVIDER_ERROR, 503, "server_error")

    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())
    model = f"lslbot/{result.provider}"

    if payload.get("stream"):
        # The reply is already complete, so it streams as a single chunk:
        # enough for clients that insist on stream=true.
        def events():
            base = {"id": completion_id, "object": "chat.completion.chunk", "created": created, "model": model}
            yield "data: " + json.dumps(
                {**base, "choices": [{"index": 0, "delta": {"role": "assistant", "content": result.text}, "finish_reason": None}]}
            ) + "\n\n"
            yield "data: " + json.dumps({**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}) + "\n\n"
            yield "data: [DONE]\n\n"

        return Response(events(), mimetype="text/event-stream")

    return jsonify(
        {
            "id": completion_id,
            "object": "chat.completion",
            "created": created,
            "model": model,
            "choices": [
                {"index": 0, "message": {"role": "assistant", "content": result.text}, "finish_reason": "stop"}
            ],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }
    )


def main() -> None:
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8080")))


if __name__ == "__main__":
    main()
