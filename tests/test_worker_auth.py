"""Phase 0 guardrails: authorization fails closed; diagnostics leak no
secret material."""

from __future__ import annotations

import re
import types

import pytest

from agent_forge import worker


def _update(user_id):
    u = types.SimpleNamespace()
    u.effective_user = (types.SimpleNamespace(id=user_id)
                        if user_id is not None else None)
    return u


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("FORGE_ALLOW_PUBLIC", raising=False)


def test_owner_allowed(monkeypatch):
    monkeypatch.setattr(worker, "_ALLOWED", {111})
    assert worker._ok(_update(111))


def test_stranger_denied(monkeypatch):
    monkeypatch.setattr(worker, "_ALLOWED", {111})
    assert not worker._ok(_update(222))


def test_no_user_denied(monkeypatch):
    monkeypatch.setattr(worker, "_ALLOWED", {111})
    assert not worker._ok(_update(None))


def test_empty_allowlist_fails_closed(monkeypatch):
    monkeypatch.setattr(worker, "_ALLOWED", set())
    assert not worker._ok(_update(222))


def test_explicit_public_override(monkeypatch):
    monkeypatch.setattr(worker, "_ALLOWED", set())
    monkeypatch.setenv("FORGE_ALLOW_PUBLIC", "1")
    assert worker._ok(_update(222))


def test_startup_refuses_empty_allowlist(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setattr(worker, "_ALLOWED", set())
    with pytest.raises(SystemExit, match="TELEGRAM_ALLOWED_USERS"):
        worker.main()


def test_diag_source_has_no_key_prefix():
    """cmd_diag must never interpolate key material — only presence and
    length. Guard the source itself so a regression can't slip in."""
    import inspect
    src = inspect.getsource(worker.cmd_diag)
    assert not re.search(r"key\[\s*:", src), \
        "cmd_diag slices the API key into its output"
