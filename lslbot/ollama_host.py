import ipaddress
import os
from urllib.parse import urlsplit

DEFAULT_URL = "http://127.0.0.1:11434"


def _means_this_machine(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_unspecified
    except ValueError:
        return False


def ollama_url(raw: str) -> str:
    """OLLAMA_HOST is Ollama's own setting, so people write it any way Ollama
    accepts - "0.0.0.0:11434", "localhost", "http://host:port". Read it the
    way Ollama does, then turn it into an address a client can connect to.
    A value that isn't an address at all comes back as written, so the error
    the bot shows names it."""
    value = (raw or "").strip().strip("\"'").strip()
    if not value:
        return DEFAULT_URL

    scheme, found, rest = value.partition("://")
    if found:
        # Ollama matches these exactly, so "HTTP://" keeps port 11434 there too.
        default_port = {"http": 80, "https": 443}.get(scheme, 11434)
        scheme = scheme.lower() or "http"
    else:
        scheme, rest, default_port = "http", value, 11434

    hostport, _, path = rest.partition("/")
    try:
        ipaddress.IPv6Address(hostport)
        hostport = f"[{hostport}]"  # a bare IPv6 address, like "::"
    except ValueError:
        pass
    try:
        parts = urlsplit(f"//{hostport}")
        host = parts.hostname or "127.0.0.1"
    except ValueError:
        return f"{scheme}://{rest}".rstrip("/")
    try:
        port = parts.port or default_port
    except ValueError:  # not a number, or out of range: Ollama uses the default
        port = default_port

    # To a server, 0.0.0.0 and :: mean "listen everywhere"; to a client they
    # mean this machine. Plain-http localhost is swapped too, because Windows
    # may try IPv6 first and stall while Ollama listens on IPv4.
    if _means_this_machine(host) or (host == "localhost" and scheme == "http"):
        host = "127.0.0.1"
    if ":" in host:
        host = f"[{host}]"

    path = path.strip("/")
    return f"{scheme}://{host}:{port}" + (f"/{path}" if path else "")


def configured_url() -> str:
    """Where the bot looks for Ollama. OLLAMA_HOST set in the system (for
    Ollama itself) wins over .env, because .env never overrides the
    environment."""
    return ollama_url(os.environ.get("OLLAMA_HOST", ""))


if __name__ == "__main__":
    # start.ps1 runs this so it sets up the same Ollama the bot will use.
    from dotenv import load_dotenv

    load_dotenv(".env", override=False)
    print(configured_url())
