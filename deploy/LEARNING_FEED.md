# Your learning feed — narrated videos to your phone

This runs Agent Forge as an always-on **Telegram bot** that makes **narrated
lesson/explainer videos** and sends them to your phone. Telegram plays MP4
inline, so it feels like a feed.

Why a host (not a cloud session): narration (edge-tts), live web discovery,
"constant" restocking, and push delivery all need open network + uptime —
which an ephemeral cloud container doesn't have. On a host, videos come out
**narrated**; in the sandbox they were silent.

## What it does

From your phone, in the bot chat:

- **`teach me <anything>`** → a narrated lesson video + a cheat-sheet doc
- **`/surprise`** → a fresh, wild explainer (discovered from the live web)
- **`/feed`** / **`/play <n>`** → your growing library
- **Auto-feed** (optional): every `RESTOCK_EVERY` seconds it discovers a new
  topic, makes a narrated video, and pushes it to you unprompted

## Setup (all from a phone browser + Telegram)

1. **Make the bot:** message **@BotFather** → `/newbot` → copy the token.
   Message **@userinfobot** → copy your numeric id.
2. **Keys:** an **Anthropic API key** (console.anthropic.com). Gemini/OpenAI
   optional.
3. **Deploy** (pick one):

### Docker (any VPS)
```bash
cp deploy/.env.worker.example .env      # fill in token, your id, key
docker build -f deploy/Dockerfile.worker -t forge-worker .
docker run -d --restart unless-stopped --env-file .env \
  -v forge_explorations:/app/explorations forge-worker
```

### Render (from a phone browser)
New → **Background Worker** → connect this repo → set:
- Dockerfile path: `deploy/Dockerfile.worker`
- add the env vars from `.env.worker.example` as secrets
- add a disk mounted at `/app/explorations`

Then open your bot in Telegram and send **`teach me how to build a REST API`**.

## Cost & safety

- Each video is several model calls (research + script) + rendering. Set
  **`TELEGRAM_ALLOWED_USERS`** so only you can spend your credits.
- **`RESTOCK_EVERY=0`** by default (no surprise spend). Turn it up (e.g.
  `21600` = 6h) once you're comfortable with the per-video cost.
- A good narration voice is free (edge-tts). If you later want a premium
  voice, that's the one paid add-on worth considering.

## Notes

- The Playwright base image ships Chromium + libs; ffmpeg is the pip-bundled
  `imageio-ffmpeg` binary — no system installs.
- Everything the worker makes lands in `/app/explorations` (mount a volume to
  keep the library across restarts).
- One bot token = one running instance (Telegram allows a single poller).
