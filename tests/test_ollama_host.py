import os
import subprocess
import sys
from pathlib import Path

import pytest

from lslbot.config import build_router_from_env
from lslbot.ollama_host import DEFAULT_URL, ollama_url

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize(
    "raw, expected",
    [
        # What Ollama's own docs tell people to set to share it on a network.
        ("0.0.0.0:11434", "http://127.0.0.1:11434"),
        ("0.0.0.0", "http://127.0.0.1:11434"),
        (":11434", "http://127.0.0.1:11434"),
        ("[::]:11434", "http://127.0.0.1:11434"),
        ("::", "http://127.0.0.1:11434"),
        ("http://0.0.0.0:11434", "http://127.0.0.1:11434"),
        ("", DEFAULT_URL),
        ("   ", DEFAULT_URL),
        ('"0.0.0.0:11434"', "http://127.0.0.1:11434"),
        ("' 0.0.0.0:11434 '", "http://127.0.0.1:11434"),
        ("localhost", "http://127.0.0.1:11434"),
        ("http://localhost:11434", "http://127.0.0.1:11434"),
        ("http://127.0.0.1:11434/", "http://127.0.0.1:11434"),
        ("::1", "http://[::1]:11434"),
        ("[::1]:11500", "http://[::1]:11500"),
        ("myserver:11500", "http://myserver:11500"),
        ("192.168.1.50", "http://192.168.1.50:11434"),
        # With a scheme and no port, Ollama uses the scheme's own port.
        ("http://ollama.example.com", "http://ollama.example.com:80"),
        ("https://ollama.example.com", "https://ollama.example.com:443"),
        ("https://localhost", "https://localhost:443"),
        ("https://ollama.example.com/ollama/", "https://ollama.example.com:443/ollama"),
        ("myserver:not-a-port", "http://myserver:11434"),
        ("myserver:99999", "http://myserver:11434"),
    ],
)
def test_reads_ollama_host_the_way_ollama_does(raw, expected):
    assert ollama_url(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [("[", "http://["), ("[::1", "http://[::1"), ("tcp://myserver:11434", "tcp://myserver:11434")],
)
def test_a_value_that_is_not_an_address_is_kept_so_the_error_names_it(raw, expected):
    assert ollama_url(raw) == expected


@pytest.mark.parametrize("raw", ["0.0.0.0:11434", "https://ollama.example.com", "[::1]", "[", "tcp://x:1"])
def test_reading_an_address_twice_changes_nothing(raw):
    assert ollama_url(ollama_url(raw)) == ollama_url(raw)


def test_ollama_host_set_for_ollama_itself_reaches_the_bot_as_a_usable_address(monkeypatch):
    monkeypatch.setenv("PRIMARY_PROVIDERS", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("STATE_FILE", "")
    monkeypatch.setenv("OLLAMA_HOST", "0.0.0.0:11434")

    router = build_router_from_env()

    assert router._fallback.host == "http://127.0.0.1:11434"


def _run_module(cwd, ollama_host=None):
    env = {k: v for k, v in os.environ.items() if k != "OLLAMA_HOST"}
    env["PYTHONPATH"] = str(REPO_ROOT)
    if ollama_host is not None:
        env["OLLAMA_HOST"] = ollama_host
    done = subprocess.run(
        [sys.executable, "-m", "lslbot.ollama_host"],
        cwd=cwd, env=env, capture_output=True, text=True, timeout=60, check=True,
    )
    return done.stdout.strip()


def test_start_ps1_gets_the_same_address_the_bot_uses(tmp_path):
    (tmp_path / ".env").write_text("OLLAMA_HOST=http://localhost:11434\n")
    assert _run_module(tmp_path) == "http://127.0.0.1:11434"

    (tmp_path / ".env").write_text("OLLAMA_HOST=http://192.168.1.50:11434\n")
    assert _run_module(tmp_path) == "http://192.168.1.50:11434"
    # Set in Windows for Ollama itself, it wins over .env - as it does for the bot.
    assert _run_module(tmp_path, ollama_host="0.0.0.0:11434") == "http://127.0.0.1:11434"

    (tmp_path / ".env").unlink()
    assert _run_module(tmp_path) == DEFAULT_URL
