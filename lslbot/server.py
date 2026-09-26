import hmac
import logging
import os

from dotenv import load_dotenv
from flask import Flask, jsonify, request

from .config import build_router_from_env
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

app = Flask(__name__)
router = build_router_from_env()


@app.before_request
def require_shared_secret():
    if not SHARED_SECRET or request.endpoint == "health":
        return None
    supplied = request.headers.get("X-Bot-Secret", "")
    if not hmac.compare_digest(supplied.encode(), SHARED_SECRET.encode()):
        return jsonify({"error": "unauthorized"}), 401
    return None


@app.post("/chat")
def chat():
    payload = request.get_json(silent=True) or {}
    message = payload.get("message")
    if not message:
        return jsonify({"error": "'message' is required"}), 400

    history = payload.get("history") or []
    messages = [*history, {"role": "user", "content": message}]

    try:
        result = router.generate(messages)
    except RouterError as exc:
        # Provider errors can echo account details (e.g. a masked API key),
        # so they go to the server log, not back to the caller.
        logger.error("no provider could answer: %s", exc)
        return jsonify({"error": "no provider could answer right now"}), 503

    return jsonify(
        {
            "reply": result.text,
            "provider": result.provider,
            "handover": result.handover,
        }
    )


@app.get("/status")
def status():
    return jsonify(router.status())


@app.get("/health")
def health():
    return jsonify({"ok": True})


def main() -> None:
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8080")))


if __name__ == "__main__":
    main()
