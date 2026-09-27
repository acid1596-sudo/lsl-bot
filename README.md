# lsl-bot

Keeps your ChatGPT and Claude work going when their usage runs out. A local
[Ollama](https://ollama.com) model picks up **the same conversation** and
carries on, then **hands it back automatically** once ChatGPT or Claude is
available again. No manual step either way.

It runs on your PC and gives you:

- **A chat page** (`http://127.0.0.1:8080`) where you talk to ChatGPT or
  Claude. When their usage runs out, Ollama answers the next message with the
  full conversation so far. Each reply is labelled with who wrote it, and a
  status bar shows who's out of usage and when they're due back.
- **Continue a ChatGPT/Claude chat**: paste a conversation from the ChatGPT or
  Claude apps and pick the task up where it stopped. **Copy chat** does the
  reverse, so you can paste the conversation back into ChatGPT or Claude once
  their usage resets.
- **An OpenAI-compatible API** (`http://127.0.0.1:8080/v1`), so other programs
  that let you set an OpenAI API address get the same automatic handover.
- Optionally, a script for **Second Life** objects (see
  [Second Life](#second-life-optional)).

> **What it can and can't take over.** It uses the official OpenAI and
> Anthropic *developer APIs* with your API keys. ChatGPT Plus and Claude Pro
> subscriptions don't include API access, so you need keys from
> [platform.openai.com/api-keys](https://platform.openai.com/api-keys) and/or
> [console.anthropic.com/settings/keys](https://console.anthropic.com/settings/keys).
> The chatgpt.com and claude.ai websites and apps can't be taken over
> automatically: they don't let another model continue their conversations,
> and scripting them would break their terms. That's what the chat page and
> Continue/Copy are for. Also bear in mind a local model is much less capable
> than ChatGPT or Claude, so work done while it's covering will be weaker.

## Quick start on Windows

Open **PowerShell** (Start menu, type "PowerShell"), paste this block and
press Enter:

```powershell
& {
  $ErrorActionPreference = 'Stop'; $ProgressPreference = 'SilentlyContinue'
  [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
  $zip = Join-Path $env:TEMP 'lsl-bot.zip'; $unpacked = Join-Path $env:TEMP 'lsl-bot-download'; $dest = Join-Path $HOME 'lsl-bot'
  Invoke-WebRequest -UseBasicParsing -Uri 'https://github.com/acid1596-sudo/lsl-bot/archive/refs/heads/main.zip' -OutFile $zip
  if (Test-Path $unpacked) { Remove-Item $unpacked -Recurse -Force }
  Expand-Archive -Path $zip -DestinationPath $unpacked
  New-Item -ItemType Directory -Force -Path $dest | Out-Null
  Copy-Item -Path (Join-Path (Get-ChildItem $unpacked -Directory)[0].FullName '*') -Destination $dest -Recurse -Force
  & (Join-Path $dest 'start.cmd')
}
```

That downloads the bot to `%USERPROFILE%\lsl-bot` and runs `start.cmd`. On the
first run it:

- asks for your OpenAI and/or Anthropic API key (hidden while you paste,
  saved only in `.env`) and generates the bot's secret key;
- adds an **lsl-bot shortcut to your desktop**;
- asks whether to open a free Cloudflare tunnel. You only need that for Second
  Life, or to use the chat page from another device such as your phone;
- installs Python, Ollama and cloudflared with `winget` if they're missing
  (Windows may ask for permission), then downloads the Ollama model - several
  GB, one time only;
- starts the bot and opens the chat page in your browser.

After that, **double-click the lsl-bot shortcut** on your desktop. If the bot
is already running, the shortcut just opens the chat page again. Keep the bot's
window open while you use it; close it (or press Ctrl+C) to stop the bot.
Pasting the block again updates the bot and keeps your `.env`.

## Using the chat page

- **New chat** starts a conversation. ChatGPT (or Claude, if that's first in
  `PRIMARY_PROVIDERS`) answers first.
- When usage runs out, the next reply comes from Ollama. It's labelled
  **Ollama (local backup)** and marked "Ollama took over from ChatGPT". The
  status bar shows when ChatGPT is due back. As soon as it is, replies switch
  back ("Handed back to ChatGPT").
- **Continue a ChatGPT/Claude chat**: in the ChatGPT or Claude app, select the
  whole conversation, copy it and paste it into this box. The task carries on
  from there with whichever model is available.
- **Copy chat** copies the whole conversation, including what Ollama did, with
  a note asking the model to continue. Paste it into ChatGPT or Claude to hand
  the task back to them.
- **Answer with** (above the message box) is normally **Auto**: the automatic
  handover above. Choose **Ollama (on this PC) only** to pull a conversation to
  Ollama yourself, even while ChatGPT and Claude are fine. Choose ChatGPT or
  Claude to use just that one. Switch back to Auto to hand the task back.
- The status bar checks Ollama too. If it shows **Ollama unavailable**, hover
  over it, or read the note beside it, to see why (see
  [If Ollama doesn't answer](#if-ollama-doesnt-answer)).

Conversations are saved as files in `data\conversations` on your PC. The page
asks for the bot's key if it doesn't have it; that's `BOT_SHARED_SECRET` in
`.env`, and the shortcut and `start.cmd` fill it in for you.

## Using it from other apps

Anything that lets you set a custom OpenAI API address can use the bot:

- **API address / base URL:** `http://127.0.0.1:8080/v1`
- **API key:** the `BOT_SHARED_SECRET` value from `.env`
- **Model:** `lslbot` (or anything else) for the automatic handover, or
  `lslbot/ollama`, `lslbot/openai`, `lslbot/anthropic` to use just that one.

For example, with the official OpenAI Python library:

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8080/v1", api_key="<BOT_SHARED_SECRET from .env>")
reply = client.chat.completions.create(model="lslbot", messages=[{"role": "user", "content": "Hello"}])
print(reply.choices[0].message.content)
```

`reply.model` says who answered (`lslbot/openai`, `lslbot/anthropic` or
`lslbot/ollama`). Only text chat is supported: images and tool/function calls
are dropped, and a streamed reply arrives in one piece. That means coding
agents that rely on tool calls won't work through it.

## How the handover works

Requests go through a priority chain, e.g. `openai -> anthropic -> ollama`
(configurable). For each request:

1. The bot tries each configured primary provider in order.
2. If a provider's call fails because it's **out of usage** (HTTP 429: a rate
   limit or a quota/billing cap), that provider is put on a cooldown and the
   request is immediately retried on the next provider in the chain.
3. If every primary provider is cooling down or fails, the request goes to
   **Ollama** (local, no usage cap to run out of) so the task still completes.
   It's given the whole conversation, and asked for a context window big
   enough to see it (`OLLAMA_NUM_CTX`).
4. The cooldown length comes from the provider's own `Retry-After` header
   when it sends one. When it doesn't (typical for a billing/quota cap, which
   has no known reset time), the bot uses a default cooldown that **doubles
   each time the provider is still exhausted** right after its previous
   cooldown expires, up to a cap. So it waits longer for a provider that's
   been down a while, without ever needing to know the real reset time.
5. The moment a cooldown expires, the **very next** request tries that
   provider again. The first success clears its cooldown - that's the
   hand-back, no separate step required.

Cooldowns are saved to a small JSON file, so a restart doesn't forget one and
go straight back to a provider that's still out of usage. A plain connection
or server error (as opposed to a usage error) does **not** start a cooldown;
it just skips that provider for the current request. Requests run in
parallel, and a burst of simultaneous 429s counts as one exhaustion rather
than escalating the cooldown once per request.

## If Ollama doesn't answer

When nothing can answer, the chat page shows Ollama's own reason. The usual
ones:

| The page says | What to do |
|---|---|
| Ollama isn't reachable at http://127.0.0.1:11434 | Open the Ollama app from the Start menu (it runs in the system tray), then try again. |
| ... isn't an address the bot can use - check OLLAMA_HOST | Fix `OLLAMA_HOST` in `.env`, or in Windows' environment variables if you set it there for Ollama. Forms like `0.0.0.0:11434` and `http://host:11434` both work. |
| Ollama doesn't have the model 'llama3' yet | Run `ollama pull llama3` in PowerShell, or run `start.cmd` again. |
| Ollama said: ... requires more system memory ... | Set `OLLAMA_NUM_CTX=4096` in `.env` (or try a smaller model), then restart the bot. |
| Ollama took longer than 600s to answer | Your PC is running the model slowly; raise `OLLAMA_TIMEOUT` in `.env`, or use a smaller model. |

To test Ollama on its own, the same way the bot uses it, paste this into
PowerShell:

```powershell
& {
  $h = 'http://127.0.0.1:11434'; $model = 'llama3'
  try {
    $tags = Invoke-RestMethod "$h/api/tags" -TimeoutSec 5
    'Ollama is reachable. Installed models: ' + ((@($tags.models) | ForEach-Object { $_.name }) -join ', ')
  } catch { "Ollama is NOT reachable at ${h}: $($_.Exception.Message)"; return }
  $body = @{ model = $model; stream = $false; options = @{ num_ctx = 8192 }; messages = @(@{ role = 'user'; content = 'Reply with the word hello.' }) } | ConvertTo-Json -Depth 5
  $timer = [Diagnostics.Stopwatch]::StartNew()
  try {
    $reply = Invoke-RestMethod "$h/api/chat" -Method Post -ContentType 'application/json' -Body $body -TimeoutSec 900
    "Ollama answered in $([int]$timer.Elapsed.TotalSeconds)s: $($reply.message.content)"
  } catch { "Ollama failed after $([int]$timer.Elapsed.TotalSeconds)s: $($_.Exception.Message) $($_.ErrorDetails.Message)" }
}
```

## Setup on other systems

```bash
pip install -r requirements.txt
cp .env.example .env   # then fill in your API keys and a long random BOT_SHARED_SECRET
ollama pull llama3
python run_server.py
```

Then open `http://127.0.0.1:8080/#key=<your BOT_SHARED_SECRET>`.

## Configuration

All configuration is via environment variables or `.env` (see `.env.example`
for the full list with defaults):

| Variable | Purpose |
|---|---|
| `PRIMARY_PROVIDERS` | Comma-separated priority chain, e.g. `openai,anthropic`. Each must be `openai` or `anthropic`. |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | ChatGPT credentials/model. |
| `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, `ANTHROPIC_MAX_TOKENS` | Claude credentials/model. |
| `OLLAMA_HOST`, `OLLAMA_MODEL` | Local fallback server and model. Default `http://127.0.0.1:11434` and `llama3`. `OLLAMA_HOST` is Ollama's own setting too: if it's set in Windows (say `0.0.0.0:11434`, to share Ollama on your network), that wins over `.env`, and the bot reads it the way Ollama does, so `0.0.0.0` means this PC. |
| `OLLAMA_NUM_CTX` | How many tokens of the conversation Ollama can see, default 8192 (llama3's maximum). Lower it if Ollama runs out of memory. |
| `OLLAMA_TIMEOUT` | Seconds to wait for Ollama's reply, default 600. |
| `DEFAULT_COOLDOWN_SECONDS` | First cooldown when a provider is out of usage and sends no `Retry-After`. |
| `MAX_COOLDOWN_SECONDS` | Cap on the growing cooldown. |
| `BACKOFF_MULTIPLIER` | How much the cooldown grows each time a provider is still out of usage. |
| `STATE_FILE` | Where cooldowns are saved between restarts. Empty = memory only. |
| `CONVERSATIONS_DIR` | Where the chat page saves conversations. |
| `HOST`, `PORT` | Server address. Defaults to `127.0.0.1:8080` (this PC only). |
| `BOT_SHARED_SECRET` | When set, everything except the page itself and `/health` needs this key. |
| `LOG_LEVEL` | Python log level, default `INFO`. Hand-overs and hand-backs are logged. |
| `PUBLIC_TUNNEL` | Windows only: `yes` opens a Cloudflare tunnel on every start, `no` keeps the bot on this PC. Empty = ask once. |
| `DESKTOP_SHORTCUT` | Windows only: `no` stops `start.cmd` from creating the desktop shortcut. |

If you make the bot reachable from other machines (`HOST=0.0.0.0`, a reverse
proxy or the tunnel), keep `BOT_SHARED_SECRET` set. Otherwise anyone who
finds the address can spend your API usage. The key travels in a request
header, so use HTTPS for anything outside your own network (the Cloudflare
tunnel does this for you).

## HTTP API

- `GET /` - the chat page.
- `GET /api/conversations`, `POST /api/conversations` (optionally with
  `imported_text` and `source` to continue a pasted chat),
  `GET`/`DELETE /api/conversations/<id>`, and
  `POST /api/conversations/<id>/messages` with `{"content": "..."}` plus an
  optional `"provider"`: `auto` (default), `openai`, `anthropic` or `ollama`.
- `POST /v1/chat/completions`, `GET /v1/models` - OpenAI-compatible (above).
- `POST /chat` with `{"message": "...", "history": [...]}` returns
  `{"reply", "provider", "handover"}`; `handover` is `true` when Ollama
  answered. It takes the same optional `"provider"`. This is what the Second
  Life script uses.
- `GET /status` - each provider's model, whether it's available (for Ollama,
  whether it's reachable and has the model, with the problem if not) or how
  long until its cooldown ends, and which one answers next.
- `GET /health` - liveness check.

The key goes in an `X-Bot-Secret` header, or `Authorization: Bearer <key>`
for OpenAI-compatible clients. `503` means nothing could answer; its `detail`
says why in plain words. Ollama's own reason is included, but ChatGPT/Claude
error text stays in the bot's window because it can echo account details.
`401` means the key is missing or wrong.

## Second Life (optional)

[`scripts/chatbot.lsl`](scripts/chatbot.lsl) is an in-world chat script: the
object's owner says `bot <anything>` in local chat and the reply is said back.
Second Life can only reach the bot through a public address, so answer yes to
the tunnel question (or set `PUBLIC_TUNNEL=yes`). `start.cmd` then fills in the
script's `BOT_URL` and `BOT_SECRET`, saves it as `data\chatbot.lsl` and copies
it to your clipboard. The tunnel address changes each time the bot starts, so
paste the script into your object again after a restart.

The script also handles a few things that are easy to miss:

- the secret goes in an `X-Bot-Secret` header (`HTTP_CUSTOM_HEADER`);
- `HTTP_BODY_MAXLENGTH` is raised to 16384, because LSL truncates responses at
  2048 bytes by default, cutting a longer reply's JSON in half;
- long replies are split up, because `llSay` cuts a message off at 1024 bytes;
- it only listens to the owner, so other people can't spend your API usage.

Anyone who can open the script can read `BOT_SECRET`, so if you give the
object away, make the script no-modify for the next owner.

## Testing

```bash
pip install -r requirements-dev.txt
pytest
```

- `tests/test_router.py`: failover, hand-back, backoff, persistence and
  concurrency, using scripted fake providers and a fake clock.
- `tests/test_providers.py`: real OpenAI/Anthropic SDK errors are translated
  correctly, and Ollama is asked for a big enough context window.
- `tests/test_conversations.py`: conversation storage, including rejecting
  ids that could escape the conversations folder.
- `tests/test_server.py`: the HTTP routes, the key check, the chat page's API
  and the OpenAI-compatible API.
