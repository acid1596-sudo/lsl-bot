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
from .tasks import GENERAL, TASKS, TaskSettings, automatic_model, get_task, is_model_name

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
task_settings = TaskSettings(os.environ.get("TASKS_FILE", "./data/tasks.json").strip() or None)

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


_LABELS = {"openai": "ChatGPT", "anthropic": "Claude", "ollama": "Ollama"}


class _BadChoice(ValueError):
    pass


def _chosen_provider(value):
    """None means "auto": the usual failover chain."""
    if value in (None, "", "auto"):
        return None
    if value not in router.provider_names():
        raise _BadChoice(f"unknown provider {value!r}; use auto or one of {router.provider_names()}")
    return value


def _requested_task(value):
    """A task named in a request; leaving it out means General."""
    if value in (None, ""):
        return GENERAL
    task = get_task(value)
    if task is None:
        raise _BadChoice(f"unknown task {value!r}; use one of {[t.id for t in TASKS]}")
    return task


def _stored_task(conversation):
    # Conversations from before tasks existed are General.
    return get_task(conversation.get("task")) or GENERAL


def _ollama_model(task) -> str:
    """The model picked for the task on the chat page, else its automatic
    one. Only code tasks need the list of installed models to decide."""
    chosen = task_settings.chosen_model(task.id)
    if chosen:
        return chosen
    installed = router.fallback.installed_models() if task.wants_code_model else None
    return automatic_model(task, router.fallback.model, installed)


def _models_for(task) -> dict:
    return {router.fallback.name: _ollama_model(task)}


def _json_object() -> dict:
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


def _with_instructions(task, messages):
    # Sent to whichever provider answers, so the task keeps its rules when it
    # moves between ChatGPT, Claude and Ollama.
    if not task.instructions:
        return messages
    return [{"role": "system", "content": task.instructions}] + messages


def _explain(exc: RouterError, only) -> str:
    # Only Ollama's own message is passed on: it's local, whereas cloud errors
    # can echo account details (e.g. a masked API key) and stay in the log.
    label = _LABELS.get(exc.provider, exc.provider)
    if exc.reason == "usage":
        return f"{label} is out of usage right now. Set 'Answer with' to Auto or another choice."
    if exc.reason == "error":
        return f"{label} couldn't answer; the reason is in the bot's window."
    if only:
        return f"Ollama couldn't answer. {exc.fallback_error}"
    return f"ChatGPT/Claude couldn't be used, and Ollama couldn't answer either. {exc.fallback_error}"


def _generate(messages, only=None, task=GENERAL):
    """Returns (result, None) or (None, user-facing explanation)."""
    try:
        return router.generate(_with_instructions(task, messages), only=only, models=_models_for(task)), None
    except RouterError as exc:
        logger.error("no provider could answer: %s", exc)
        return None, _explain(exc, only)


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/health")
def health():
    return jsonify({"ok": True})


@app.get("/status")
def status():
    # ?task= checks Ollama for the model that task would use.
    task = get_task(request.args.get("task")) or GENERAL
    return jsonify(router.status(models=_models_for(task)))


def _task_view(task, installed):
    chosen = task_settings.chosen_model(task.id)
    automatic = automatic_model(task, router.fallback.model, installed)
    return {
        "id": task.id,
        "label": task.label,
        "description": task.description,
        "chosen_model": chosen,
        "automatic_model": automatic,
        "model": chosen or automatic,
    }


@app.get("/api/tasks")
def list_tasks():
    installed = router.fallback.installed_models()
    return jsonify(
        {
            "tasks": [_task_view(task, installed) for task in TASKS],
            # None when Ollama can't be asked, so the page can say so.
            "installed_models": None if installed is None else sorted(m["name"] for m in installed),
        }
    )


@app.put("/api/tasks/<task_id>")
def choose_task_model(task_id):
    task = get_task(task_id)
    if task is None:
        return jsonify({"error": "task not found"}), 404
    payload = _json_object()
    if "model" not in payload:
        return jsonify({"error": "'model' is required; an empty one means automatic"}), 400
    model = payload["model"] or ""
    if model and not is_model_name(model):
        return jsonify({"error": "'model' must be an Ollama model name, such as qwen3-coder:30b"}), 400
    task_settings.choose_model(task.id, model)
    return jsonify(_task_view(task, router.fallback.installed_models()))


@app.post("/chat")
def chat():
    payload = request.get_json(silent=True) or {}
    message = payload.get("message")
    if not isinstance(message, str) or not message:
        return jsonify({"error": "'message' is required"}), 400
    try:
        only = _chosen_provider(payload.get("provider"))
        task = _requested_task(payload.get("task"))
    except _BadChoice as exc:
        return jsonify({"error": str(exc)}), 400

    result, problem = _generate(
        _plain_messages(payload.get("history")) + [{"role": "user", "content": message}], only, task
    )
    if result is None:
        return jsonify({"error": NO_PROVIDER_ERROR, "detail": problem}), 503
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
    try:
        task = _requested_task(payload.get("task"))
    except _BadChoice as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(store.create(imported_text, source[:40], task.id)), 201


@app.get("/api/conversations/<conversation_id>")
def get_conversation(conversation_id):
    conversation = store.get(conversation_id)
    if conversation is None:
        return jsonify({"error": "conversation not found"}), 404
    return jsonify(conversation)


@app.patch("/api/conversations/<conversation_id>")
def update_conversation(conversation_id):
    payload = _json_object()
    if "task" not in payload:
        return jsonify({"error": "'task' is required"}), 400
    try:
        task = _requested_task(payload["task"])
    except _BadChoice as exc:
        return jsonify({"error": str(exc)}), 400
    conversation = store.set_task(conversation_id, task.id)
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
    try:
        only = _chosen_provider(payload.get("provider"))
    except _BadChoice as exc:
        return jsonify({"error": str(exc)}), 400

    result, problem = _generate(
        store.history(conversation) + [{"role": "user", "content": content}], only, _stored_task(conversation)
    )
    if result is None:
        return jsonify({"error": NO_PROVIDER_ERROR, "detail": problem}), 503
    updated = store.add_exchange(conversation_id, content, result.text, result.provider, result.model)
    if updated is None:
        return jsonify({"error": "conversation not found"}), 404
    return jsonify({"conversation": updated, "handover": result.handover})


def _openai_error(message: str, status_code: int, error_type: str):
    return jsonify({"error": {"message": message, "type": error_type}}), status_code


@app.get("/v1/models")
def openai_models():
    # "lslbot" is the usual failover; "lslbot/<name>" uses only that provider,
    # and "@<task>" on either (say "lslbot@mesh") works as that task.
    ids = (
        ["lslbot"]
        + [f"lslbot/{name}" for name in router.provider_names()]
        + [f"lslbot@{task.id}" for task in TASKS if task is not GENERAL]
    )
    return jsonify({"object": "list", "data": [{"id": i, "object": "model", "owned_by": "lslbot"} for i in ids]})


def _route_for_model(model):
    """(provider or None for the failover, task) from a model name; any
    name the bot doesn't know gets the failover and the General task."""
    if not isinstance(model, str):
        return None, GENERAL
    name, _, task_id = model.partition("@")
    name = name[len("lslbot/"):] if name.startswith("lslbot/") else name
    return (name if name in router.provider_names() else None), get_task(task_id) or GENERAL


@app.post("/v1/chat/completions")
def openai_chat_completions():
    payload = request.get_json(silent=True) or {}
    messages = _plain_messages(payload.get("messages"))
    if not messages:
        return _openai_error("'messages' must contain at least one text message", 400, "invalid_request_error")

    result, problem = _generate(messages, *_route_for_model(payload.get("model")))
    if result is None:
        return _openai_error(problem, 503, "server_error")

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
