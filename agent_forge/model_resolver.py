"""Dynamic model resolver — always pick the latest model each provider offers.

Each of the three providers exposes a ``models.list()`` call that returns
the models your API key can access. This module queries those lists, filters
to the family you asked for (``opus`` / ``pro`` / ``gpt`` etc.), ranks by
version + recency, and returns the newest.

The resolved model IDs are cached in ``~/.agent_forge/model_cache.json``
with a 24-hour TTL so we don't hammer the APIs every session, but you
automatically pick up new releases within a day of them going live.

If an API call fails (no key, network issue), we fall back to sensible
hardcoded defaults — the system keeps working, you just won't auto-track
the absolute latest until the API is reachable again.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


# ── cache plumbing ────────────────────────────────────────

_CACHE_DIR = Path.home() / ".agent_forge"
_CACHE_FILE = _CACHE_DIR / "model_cache.json"
_CACHE_TTL_SECONDS = 24 * 60 * 60   # 24 hours


def _load_cache() -> dict:
    if not _CACHE_FILE.exists():
        return {}
    try:
        return json.loads(_CACHE_FILE.read_text())
    except Exception:
        return {}


def _save_cache(cache: dict) -> None:
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _CACHE_FILE.write_text(json.dumps(cache, indent=2))
    except Exception:
        pass


def _cache_key(provider: str, family: str) -> str:
    return f"{provider}:{family}"


def _cached_or_fetch(
    provider: str,
    family: str,
    fetcher: Callable[[], str | None],
    fallback: str,
) -> str:
    """Check cache first; if stale or missing, fetch; always return something."""
    cache = _load_cache()
    key = _cache_key(provider, family)
    entry = cache.get(key)
    now = time.time()
    if entry and (now - entry.get("ts", 0)) < _CACHE_TTL_SECONDS:
        return entry.get("model") or fallback

    try:
        resolved = fetcher()
    except Exception:
        resolved = None

    model = resolved or fallback
    cache[key] = {"model": model, "ts": now, "via": "api" if resolved else "fallback"}
    _save_cache(cache)
    return model


# ── version ranking helpers ───────────────────────────────

_VERSION_RE = re.compile(r"(\d+)(?:[.\-_](\d+))?(?:[.\-_](\d+))?")
_DATE_RE = re.compile(r"(20\d{6,8})")


def _version_tuple(model_id: str) -> tuple[int, ...]:
    """Extract a comparable version signature from a model id.

    Prefers embedded date suffixes (YYYYMMDD), falls back to version numbers.
    Missing positions zero out so older short-form ids don't accidentally win.
    """
    m = _DATE_RE.search(model_id)
    if m:
        d = m.group(1)
        # Pad to YYYYMMDD
        d = (d + "00000000")[:8]
        return (int(d),)
    parts = _VERSION_RE.findall(model_id)
    nums: list[int] = []
    for p in parts:
        for x in p:
            nums.append(int(x) if x else 0)
    # Pad to length 4 so shorter IDs aren't treated as ties
    while len(nums) < 4:
        nums.append(0)
    return tuple(nums)


# ── Anthropic resolver ────────────────────────────────────

_ANTHROPIC_FAMILIES = {
    "opus":   "claude-opus",
    "sonnet": "claude-sonnet",
    "haiku":  "claude-haiku",
}

_ANTHROPIC_FALLBACKS = {
    "opus":   "claude-opus-4-7",
    "sonnet": "claude-sonnet-4-6",
    "haiku":  "claude-haiku-4-5",
}


def resolve_anthropic(family: str) -> str:
    prefix = _ANTHROPIC_FAMILIES.get(family)
    fallback = _ANTHROPIC_FALLBACKS.get(family, "")
    if not prefix or not fallback:
        return family  # pass through unrecognized families

    def _fetch() -> str | None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return None
        try:
            from anthropic import Anthropic
        except ImportError:
            return None
        client = Anthropic()
        models = client.models.list()
        matching = [m.id for m in models.data if m.id.startswith(prefix)]
        if not matching:
            return None
        matching.sort(key=_version_tuple, reverse=True)
        return matching[0]

    return _cached_or_fetch("anthropic", family, _fetch, fallback)


# ── OpenAI resolver ───────────────────────────────────────

_OPENAI_FAMILIES = {
    "gpt":      "gpt-",
    "gpt-5":    "gpt-5",
    "gpt-4":    "gpt-4",
    "gpt-4o":   "gpt-4o",
    "o1":       "o1",
    "o3":       "o3",
    "o4":       "o4",
}

_OPENAI_FALLBACKS = {
    "gpt":      "gpt-5.4",
    "gpt-5":    "gpt-5.4",
    "gpt-4":    "gpt-4o",
    "gpt-4o":   "gpt-4o",
    "o1":       "o1",
    "o3":       "o3-mini",
    "o4":       "o4-mini",
}


def resolve_openai(family: str) -> str:
    prefix = _OPENAI_FAMILIES.get(family)
    fallback = _OPENAI_FALLBACKS.get(family, "")
    if not prefix or not fallback:
        return family

    def _fetch() -> str | None:
        if not os.environ.get("OPENAI_API_KEY"):
            return None
        try:
            from openai import OpenAI
        except ImportError:
            return None
        client = OpenAI()
        # Retrieve lists actual chat-capable models; filter to family.
        # Exclude embedding / tts / image / audio models that share the prefix.
        EXCLUDE = ("-embed", "-tts", "-image", "-audio", "-realtime",
                   "transcribe", "whisper", "-search-preview")
        models = client.models.list()
        matching = [
            m.id for m in models.data
            if m.id.startswith(prefix)
            and not any(ex in m.id for ex in EXCLUDE)
        ]
        # For the generic "gpt" family, rank by explicit version (higher "gpt-N" wins)
        if family == "gpt":
            # Prefer the highest major number + highest version within that major
            def _score(mid: str) -> tuple[int, ...]:
                # Extract "gpt-X.Y" portion
                m = re.match(r"gpt-(\d+)(?:\.(\d+))?", mid)
                if m:
                    maj = int(m.group(1))
                    minor = int(m.group(2) or 0)
                else:
                    maj, minor = 0, 0
                return (maj, minor) + _version_tuple(mid)
            matching.sort(key=_score, reverse=True)
        else:
            matching.sort(key=_version_tuple, reverse=True)
        return matching[0] if matching else None

    return _cached_or_fetch("openai", family, _fetch, fallback)


# ── Google resolver ───────────────────────────────────────

_GOOGLE_FAMILIES = {
    "pro":         "gemini-",     # rank by version to find latest pro
    "flash":       "gemini-",
    "flash-lite":  "gemini-",
}

_GOOGLE_FALLBACKS = {
    "pro":         "gemini-3.1-pro",
    "flash":       "gemini-2.5-flash",
    "flash-lite":  "gemini-2.5-flash-lite",
}

_GOOGLE_SUFFIX = {
    "pro":         "-pro",
    "flash":       "-flash",
    "flash-lite":  "-flash-lite",
}


def resolve_google(family: str) -> str:
    prefix = _GOOGLE_FAMILIES.get(family)
    fallback = _GOOGLE_FALLBACKS.get(family, "")
    suffix = _GOOGLE_SUFFIX.get(family, "")
    if not prefix or not fallback:
        return family

    def _fetch() -> str | None:
        if not os.environ.get("GEMINI_API_KEY") and not os.environ.get("GOOGLE_API_KEY"):
            return None
        try:
            from google import genai
        except ImportError:
            return None
        client = genai.Client()
        models = list(client.models.list())
        matching: list[str] = []
        for m in models:
            name = getattr(m, "name", "")
            # Strip leading "models/" namespace if present
            if name.startswith("models/"):
                name = name[len("models/"):]
            if (name.startswith(prefix) and suffix in name
                    and "flash-lite" in name if family == "flash-lite"
                    else name.startswith(prefix) and name.endswith(suffix)):
                matching.append(name)
        if not matching:
            return None
        matching.sort(key=_version_tuple, reverse=True)
        return matching[0]

    return _cached_or_fetch("google", family, _fetch, fallback)


# ── summary for /models command ───────────────────────────

@dataclass
class ResolvedModel:
    provider: str
    family: str
    resolved: str
    source: str   # "api" | "fallback"


def all_resolutions() -> list[ResolvedModel]:
    """Return the current resolved model for every known family, for display."""
    results: list[ResolvedModel] = []
    cache = _load_cache()

    def _record(provider: str, family: str, resolver: Callable[[str], str]) -> None:
        resolved = resolver(family)
        entry = cache.get(_cache_key(provider, family)) or {}
        results.append(ResolvedModel(
            provider=provider, family=family, resolved=resolved,
            source=entry.get("via", "fallback"),
        ))

    for f in ["opus", "sonnet", "haiku"]:
        _record("anthropic", f, resolve_anthropic)
    for f in ["pro", "flash"]:
        _record("google", f, resolve_google)
    for f in ["gpt", "o3"]:
        _record("openai", f, resolve_openai)
    return results


def clear_cache() -> None:
    """Wipe the model cache; next call re-queries the APIs."""
    if _CACHE_FILE.exists():
        try:
            _CACHE_FILE.unlink()
        except Exception:
            pass
