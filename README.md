# lsl-bot

A small HTTP backend that answers chat requests using ChatGPT (OpenAI) or
Claude (Anthropic), and **automatically fails over to a local Ollama model
when those providers run out of usage** - a rate limit or a billing/quota
cap - then **hands tasks back automatically once the provider's usage
resets**. No manual intervention needed either way.

> **Scope note:** this talks to the official OpenAI and Anthropic *developer
> APIs* (the same ones any app built on GPT/Claude uses), not the
> chatgpt.com / claude.ai consumer web apps. Those apps have their own
> "you've hit your limit, resets at ..." caps, but automating a consumer
> account through the browser to work around that would be fragile and
> against those products' terms of service, so this project doesn't do that.
> If your ChatGPT/Claude "usage" is actually a Plus/Pro web subscription
> rather than API billing, you'd point `OPENAI_API_KEY` / `ANTHROPIC_API_KEY`
> at a developer API key instead (they're billed separately from the web
> subscriptions).

## How the handover works

Requests go through a priority chain, e.g. `openai -> anthropic -> ollama`
(configurable). For each request:

1. The router tries each configured primary provider in order.
2. If a provider's call fails because it's **out of usage** (HTTP 429 - rate
   limit or quota/billing cap), that provider is put on a cooldown and the
   request is immediately retried on the next provider in the chain.
3. If every primary provider is cooling down or fails, the request goes to
   **Ollama** (local, no usage cap to run out of) so the task still
   completes.
4. The cooldown length comes from the provider's own `Retry-After` header
   when it sends one. When it doesn't (typical for a billing/quota cap,
   which has no known reset time), the router uses a default cooldown that
   **doubles each time the provider is still exhausted** right after its
   previous cooldown expires, up to a configurable cap - so it naturally
   waits longer for a provider that's been down for a while without ever
   needing to know the real reset time in advance.
5. The moment a primary provider's cooldown expires, the **very next**
   request tries it again automatically. The first success clears its
   cooldown - that's the hand-back, no separate step required.

Provider state (who's cooling down, until when) is persisted to a small JSON
file so a restart doesn't forget an in-progress cooldown and re-hammer a
provider that's still exhausted.

A plain connection/server error (as opposed to a usage error) does **not**
start a cooldown - it just skips that provider for the current request, since
there's nothing to "wait out."

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # then fill in your API keys
```

You'll also need a local [Ollama](https://ollama.com) install with a model
pulled, e.g.:

```bash
ollama pull llama3
ollama serve   # usually already running as a service after install
```

Run the server:

```bash
python run_server.py
```

## Configuration

All configuration is via environment variables (or `.env` - see
`.env.example` for the full list with defaults):

| Variable | Purpose |
|---|---|
| `PRIMARY_PROVIDERS` | Comma-separated priority chain, e.g. `openai,anthropic`. Each must be `openai` or `anthropic`. |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | ChatGPT credentials/model. |
| `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, `ANTHROPIC_MAX_TOKENS` | Claude credentials/model. |
| `OLLAMA_HOST`, `OLLAMA_MODEL` | Local fallback server/model. |
| `DEFAULT_COOLDOWN_SECONDS` | Initial cooldown when a provider is exhausted with no `Retry-After`. |
| `MAX_COOLDOWN_SECONDS` | Cap on the exponential backoff. |
| `BACKOFF_MULTIPLIER` | Growth factor applied to the cooldown each time a provider is still exhausted after its previous cooldown expired. |
| `STATE_FILE` | Where cooldown state is persisted between restarts. Empty = memory-only. |
| `HOST`, `PORT` | Server bind address. |

## API

**`POST /chat`**
```jsonc
// request
{ "message": "hello", "history": [{"role": "user", "content": "..."}] }
// response
{ "reply": "hi!", "provider": "ollama", "handover": true }
```
`provider` says who actually answered; `handover` is `true` whenever the
answer came from the Ollama fallback instead of a primary provider. Returns
`503` if every provider (including Ollama) failed.

**`GET /status`** - which provider is currently active, and for each primary
provider whether it's available or how many seconds until its cooldown ends.

**`GET /health`** - liveness check.

### Calling it from an LSL script

Since this repo is named after Second Life's scripting language: LSL objects
can only reach the outside world over HTTP, via `llHTTPRequest`. A minimal
example:

```lsl
default
{
    touch_start(integer n)
    {
        llHTTPRequest("http://YOUR_SERVER:8080/chat",
            [HTTP_METHOD, "POST", HTTP_MIMETYPE, "application/json"],
            llList2Json(JSON_OBJECT, ["message", "Hello!"]));
    }

    http_response(key id, integer status, list meta, string body)
    {
        llSay(0, llJsonGetValue(body, ["reply"]));
    }
}
```

## Testing

```bash
pip install -r requirements-dev.txt
pytest
```

`tests/test_router.py` covers the failover/hand-back/backoff/persistence
logic with scripted fake providers and a fake clock (no real network or
sleeping involved). `tests/test_providers.py` checks that real
OpenAI/Anthropic SDK exceptions get translated correctly. `tests/test_server.py`
covers the HTTP routes with a stubbed router.
