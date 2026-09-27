class FakeHTTPResponse:
    """Minimal stand-in for the httpx response object the OpenAI/Anthropic SDKs
    attach to their status errors - just enough for our provider wrappers to
    read a status code and a Retry-After header off of it."""

    def __init__(self, status_code=429, headers=None):
        self.status_code = status_code
        self.headers = headers or {}
        self.request = None
