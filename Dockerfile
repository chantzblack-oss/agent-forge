# Agent Forge — Telegram bot (always-on hosting image)
#
# This image runs the bot on the API (SDK) path: it does NOT install the
# `claude` / `gemini` CLIs, so every provider resolves to its SDK backend.
# That means you must supply API keys (see .env.telegram.example):
#   ANTHROPIC_API_KEY, GEMINI_API_KEY, OPENAI_API_KEY, TELEGRAM_BOT_TOKEN
#
# Build:  docker build -t agent-forge-bot .
# Run:    docker run --env-file .env -v agentforge_data:/root/.agent_forge agent-forge-bot

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

WORKDIR /app

# Runtime deps installed explicitly (the repo uses a flat layout with no
# build-backend, so we run from source rather than `pip install .`).
RUN pip install --upgrade pip && pip install \
    "rich>=13.0.0" \
    "edge-tts>=7.0.0" \
    "anthropic>=0.40.0" \
    "google-genai>=1.0.0" \
    "openai>=1.50.0" \
    "python-telegram-bot>=21.0"

# Application source.
COPY agent_forge ./agent_forge

# Persisted cross-session memory + model cache live here.
VOLUME ["/root/.agent_forge"]

# The bot reads its token + keys from the environment.
CMD ["python", "-m", "agent_forge.telegram_bot"]
