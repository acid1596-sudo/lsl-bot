from typing import Optional


def parse_retry_after(headers) -> Optional[float]:
    """Best-effort extraction of a Retry-After value (in seconds) from HTTP
    response headers. Returns None if the header is absent or not a plain
    number of seconds (HTTP also allows an HTTP-date, which we don't bother
    parsing - the caller just falls back to its own default cooldown).
    """
    if headers is None:
        return None
    value = headers.get("retry-after")
    if value is None:
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    return seconds if seconds >= 0 else None
