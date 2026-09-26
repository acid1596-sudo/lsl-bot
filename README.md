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
| `HOST`, `PORT` | Server bind address. Defaults to `127.0.0.1` (this machine only). |
| `BOT_SHARED_SECRET` | When set, `/chat` and `/status` require a matching `X-Bot-Secret` header. |
| `LOG_LEVEL` | Python log level, default `INFO`. Failover and hand-back events are logged at `WARNING`/`INFO`. |

### Exposing it to Second Life

Second Life's servers have to reach this over the internet, so you'll need
`HOST=0.0.0.0` (or a reverse proxy/tunnel in front of it). Before you do that,
**set `BOT_SHARED_SECRET`** - otherwise anyone who finds the URL can spend
your OpenAI/Anthropic usage through it. The secret travels in a request
header, so put the server behind HTTPS if you can.

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
`503` if every provider (including Ollama) failed - the details go to the
server log rather than the response - and `401` if `BOT_SHARED_SECRET` is set
and the `X-Bot-Secret` header doesn't match.

**`GET /status`** - which provider is currently active, and for each primary
provider whether it's available or how many seconds until its cooldown ends.

**`GET /health`** - liveness check.

### Calling it from an LSL script

Since this repo is named after Second Life's scripting language: LSL objects
can only reach the outside world over HTTP, via `llHTTPRequest`. A minimal
example:

```lsl
string BOT_URL    = "https://YOUR_SERVER/chat";
string BOT_SECRET = "the same value as BOT_SHARED_SECRET";

default
{
    touch_start(integer n)
    {
        llHTTPRequest(BOT_URL,
            [HTTP_METHOD, "POST",
             HTTP_MIMETYPE, "application/json",
             HTTP_CUSTOM_HEADER, "X-Bot-Secret", BOT_SECRET,
             HTTP_BODY_MAXLENGTH, 16384],
            llList2Json(JSON_OBJECT, ["message", "Hello!"]));
    }

    http_response(key id, integer status, list meta, string body)
    {
        if (status == 200)
            llSay(0, llJsonGetValue(body, ["reply"]));
        else
            llOwnerSay("bot error " + (string)status);
    }
}
```

`HTTP_BODY_MAXLENGTH` matters: LSL truncates responses at 2048 bytes by
default, which cuts a longer reply's JSON in half so `llJsonGetValue` can't
parse it (16384 is the maximum for Mono scripts). Anyone who can open the
script can read `BOT_SECRET`, so if you give the object away, make the script
no-modify for the next owner.

## Testing

```bash
pip install -r requirements-dev.txt
pytest
```

`tests/test_router.py` covers the failover/hand-back/backoff/persistence
logic with scripted fake providers and a fake clock (no real network or
sleeping involved), plus concurrency: a slow provider call must not hold up
other requests, and a burst of simultaneous 429s must start one cooldown, not
escalate it once per request. `tests/test_providers.py` checks that real
OpenAI/Anthropic SDK exceptions get translated correctly. `tests/test_server.py`
covers the HTTP routes and the shared-secret check with a stubbed router.
