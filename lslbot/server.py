import logging
import os

from flask import Flask, jsonify, request

from .config import build_router_from_env
from .router import RouterError

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))

app = Flask(__name__)
router = build_router_from_env()


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
        return jsonify({"error": str(exc)}), 503

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
    app.run(host=os.environ.get("HOST", "0.0.0.0"), port=int(os.environ.get("PORT", "8080")))


if __name__ == "__main__":
    main()
