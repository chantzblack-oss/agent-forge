"""verify_providers — single tiny call per provider to validate auth + network.

Runs BEFORE any benchmark. Costs ~$0.001 total. Reports which providers are
actually usable so you don't waste a 5-question pilot finding out the network
is blocked or the key is invalid.

CLI: `python -m agent_forge.bench.verify`
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Callable

from ..providers import get_provider
from ..providers.errors import ProviderError


@dataclass
class _ProbeResult:
    label: str
    model: str
    ok: bool
    elapsed_s: float
    text: str = ""
    error: str = ""
    cost_usd: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    notes: list[str] = field(default_factory=list)


def _probe(label: str, model: str, key_env: str | None) -> _ProbeResult:
    """One micro-call per provider. Caps tokens, short timeout, harmless prompt."""
    if key_env and not os.getenv(key_env):
        return _ProbeResult(
            label=label, model=model, ok=False, elapsed_s=0.0,
            error=f"{key_env} not set in environment",
            notes=[f"export {key_env}=... before running"],
        )

    t0 = time.time()
    try:
        provider = get_provider(model)
        text, stats = provider.complete(
            model=model,
            system="Reply with the single word OK and nothing else.",
            user="ping",
            max_tokens=5,
            timeout_s=20,
        )
        return _ProbeResult(
            label=label, model=model, ok=True,
            elapsed_s=time.time() - t0,
            text=(text or "").strip()[:60],
            cost_usd=stats.cost_usd,
            input_tokens=stats.input_tokens,
            output_tokens=stats.output_tokens,
        )
    except ProviderError as exc:
        return _ProbeResult(
            label=label, model=model, ok=False,
            elapsed_s=time.time() - t0,
            error=f"ProviderError: {exc}",
            notes=_diagnose(str(exc)),
        )
    except Exception as exc:
        return _ProbeResult(
            label=label, model=model, ok=False,
            elapsed_s=time.time() - t0,
            error=f"{type(exc).__name__}: {exc}",
            notes=_diagnose(str(exc)),
        )


def _diagnose(error_text: str) -> list[str]:
    et = error_text.lower()
    notes: list[str] = []
    if "host not in allowlist" in et or "403" in et:
        notes.append("network egress blocked — sandbox proxy refused the request")
    if "auth" in et or "401" in et or "invalid_api_key" in et:
        notes.append("authentication failed — key may be invalid or rotated")
    if "rate" in et and "limit" in et:
        notes.append("rate limited — backoff or use a different tier")
    if "timeout" in et:
        notes.append("network timeout — destination unreachable or slow")
    if "module" in et and "import" in et:
        notes.append("SDK not installed — pip install openai or google-genai")
    return notes or ["uncategorized — see error string"]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="agent_forge.bench.verify")
    p.add_argument(
        "--openai-model", default="gpt-4o-mini",
        help="OpenAI model to probe (cheapest viable; default: gpt-4o-mini)",
    )
    p.add_argument(
        "--gemini-model", default="gemini-2.5-flash",
        help="Gemini model to probe (default: gemini-2.5-flash)",
    )
    p.add_argument(
        "--claude-model", default="haiku",
        help="Claude model to probe (default: haiku)",
    )
    args = p.parse_args(argv)

    probes: list[Callable[[], _ProbeResult]] = [
        lambda: _probe("Claude (CLI)", args.claude_model, key_env=None),
        lambda: _probe("OpenAI", args.openai_model, key_env="OPENAI_API_KEY"),
        lambda: _probe("Gemini", args.gemini_model, key_env="GEMINI_API_KEY"),
    ]

    print(f"=== Provider verification ({len(probes)} probes) ===\n")
    results: list[_ProbeResult] = []
    for fn in probes:
        r = fn()
        results.append(r)
        status = "OK" if r.ok else "FAIL"
        print(f"[{status}] {r.label:<14} model={r.model:<24} {r.elapsed_s:5.1f}s")
        if r.ok:
            tok = f"({r.input_tokens},{r.output_tokens})" if r.input_tokens is not None else "(unknown)"
            cost = f"${r.cost_usd:.6f}" if r.cost_usd is not None else "$?"
            print(f"       reply: {r.text!r}")
            print(f"       tokens: {tok}  cost: {cost}")
        else:
            print(f"       error: {r.error}")
            for note in r.notes:
                print(f"       hint:  {note}")
        print()

    ok_count = sum(1 for r in results if r.ok)
    print(f"=== Summary: {ok_count}/{len(results)} providers reachable ===")

    if ok_count == len(results):
        total_cost = sum((r.cost_usd or 0.0) for r in results)
        print(f"Total verification cost: ${total_cost:.6f}")
        print("All providers OK — cross-provider runs viable.")
        return 0
    if ok_count == 0:
        print("No providers reachable. Check keys + network egress.")
        return 2
    print("Partial reachability — cross-provider runs will be degraded.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
