from __future__ import annotations

from typing import Any

import pytest

from agent_forge.providers import (
    LLMProvider,
    ProviderCallStats,
    ProviderError,
    get_provider,
    register_provider,
    reset_providers,
)


class MockProvider(LLMProvider):
    def __init__(self, label: str = "mock", reply: str = "mock-reply") -> None:
        self.label = label
        self.reply = reply
        self.calls: list[tuple[str, str, str]] = []

    def complete(
        self, *, model: str, system: str, user: str, **kwargs: Any
    ) -> tuple[str, ProviderCallStats]:
        self.calls.append((model, system, user))
        return self.reply, ProviderCallStats(
            provider=self.label,
            model=model,
            input_tokens=10,
            output_tokens=20,
            cost_usd=0.001,
        )


@pytest.fixture(autouse=True)
def _isolated_registry():
    reset_providers()
    yield
    reset_providers()


def test_default_registry_routes_claude_models() -> None:
    # ClaudeProvider construction doesn't need API keys (uses CLI). Verify routing only.
    provider = get_provider("opus")
    assert provider.__class__.__name__ == "ClaudeProvider"
    assert get_provider("sonnet").__class__.__name__ == "ClaudeProvider"
    assert get_provider("haiku").__class__.__name__ == "ClaudeProvider"


def test_unknown_model_raises_provider_error() -> None:
    with pytest.raises(ProviderError):
        get_provider("totally-fake-model-7b")


def test_register_provider_routes_by_prefix() -> None:
    fake = MockProvider("fake", "hi")
    register_provider("custom-7b", lambda: fake)
    out, stats = get_provider("custom-7b").complete(
        model="custom-7b", system="sys", user="usr"
    )
    assert out == "hi"
    assert stats.provider == "fake"
    assert stats.cost_usd == 0.001


def test_longest_prefix_wins() -> None:
    short = MockProvider("short", "short-reply")
    long = MockProvider("long", "long-reply")
    register_provider("gpt-4", lambda: short)
    register_provider("gpt-4o-mini", lambda: long)
    text, stats = get_provider("gpt-4o-mini-2024-07-18").complete(
        model="gpt-4o-mini-2024-07-18", system="s", user="u"
    )
    assert text == "long-reply"
    assert stats.provider == "long"


def test_provider_instance_is_cached_per_prefix() -> None:
    register_provider("xx-", lambda: MockProvider("x"))
    a = get_provider("xx-1")
    b = get_provider("xx-2")
    assert a is b
