# Running Agent Forge from your phone (always-on)

Agent Forge ships a **Telegram bot** (`agent_forge/telegram_bot.py`) — that's
the mobile interface. You message your bot, it runs the multi-agent teams, and
replies in the chat. To use it from your phone *whenever you want*, the bot
needs to run on a machine that's always on. This folder has everything for that.

## How it works on a server

On your laptop, Agent Forge can use the logged-in `claude` / `gemini` CLIs (no
API keys). **On a server there's no logged-in CLI**, so the bot automatically
falls back to the **API (SDK) path** and uses API keys instead. That's why the
hosting setup asks for keys for every model family you want to use.

| Key | Needed for |
|-----|-----------|
| `TELEGRAM_BOT_TOKEN` | the bot itself (from [@BotFather](https://t.me/BotFather)) |
| `ANTHROPIC_API_KEY` | Claude — **required** (no CLI on a server) |
| `GEMINI_API_KEY` | every Cross-Model team (Claude + Gemini) |
| `OPENAI_API_KEY` | Tri-Model / Triple-Model Braintrust (adds GPT) |
| `TELEGRAM_ALLOWED_USERS` | optional but recommended — lock the bot to your user ID |

> ⚠️ **Lock it down.** Without `TELEGRAM_ALLOWED_USERS`, anyone who finds your
> bot can spend your API credits. Message [@userinfobot](https://t.me/userinfobot)
> to get your numeric Telegram ID, then set it.

## Step 0 — create the bot

1. In Telegram, message **@BotFather** → `/newbot` → follow the prompts.
2. Copy the token it gives you (looks like `123456789:AA...`). That's your
   `TELEGRAM_BOT_TOKEN`.

## Option A — Docker Compose (easiest on any VPS)

```bash
cp .env.telegram.example .env     # then fill in your keys
docker compose up -d --build
docker compose logs -f            # watch it connect; Ctrl-C to stop watching
```

Auto-restarts on crash and on reboot. Update with `git pull && docker compose up -d --build`.
Stop with `docker compose down`.

## Option B — Fly.io (managed, no server to maintain)

See the header of [`fly.toml`](./fly.toml) for the exact commands. Summary:

```bash
fly launch --no-deploy
fly secrets set TELEGRAM_BOT_TOKEN=... ANTHROPIC_API_KEY=... GEMINI_API_KEY=... OPENAI_API_KEY=... TELEGRAM_ALLOWED_USERS=...
fly volumes create agentforge_data --size 1
fly deploy -c deploy/fly.toml --dockerfile Dockerfile
```

Keep **exactly one** machine running — Telegram long-polling allows only one
poller per bot token.

## Option C — systemd on a VPS / Raspberry Pi (no Docker)

See [`agent-forge-bot.service`](./agent-forge-bot.service) for the full
walkthrough. Summary:

```bash
sudo git clone <your-fork> /opt/agent-forge && cd /opt/agent-forge
python3 -m venv .venv
.venv/bin/pip install rich edge-tts anthropic google-genai openai python-telegram-bot
cp .env.telegram.example .env     # fill in keys
sudo cp deploy/agent-forge-bot.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now agent-forge-bot
journalctl -u agent-forge-bot -f
```

## Using it from your phone

Once the bot is running, open the chat with your bot in Telegram:

- `/start` — welcome + instructions
- `/teams` — list all 24 teams
- `/team` — switch team (default: **Triple-Model Braintrust**)
- `/ask <question>` — run the current team on a question
- just send a plain message — same as `/ask`
- `/status` — is a session running?
- `/cancel` — abort a running session

## Notes & gotchas

- **One poller per token.** Don't run the bot in two places at once (e.g. Fly
  *and* your laptop) — Telegram will throw `Conflict` errors.
- **Costs.** Tri-Model teams call Claude + Gemini + GPT across multiple rounds;
  a single `/ask` can be several model calls. Watch your API spend, and use
  `TELEGRAM_ALLOWED_USERS` to keep strangers out.
- **Persistence.** Cross-session memory and the resolved-model cache live in
  `/root/.agent_forge` (the mounted volume), so they survive restarts.
