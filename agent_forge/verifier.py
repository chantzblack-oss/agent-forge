"""Citationist + Verifier — post-deliberation audit agents.

Two capabilities:

1. **Citationist**: takes markdown citations of the form ``[label](url)`` from
   agent output, actually fetches each URL (via Claude CLI with WebFetch),
   extracts a supporting quote, and flags citations where the page content
   doesn't back the claim. Catches hallucinated or misattributed sources.

2. **Verifier**: runs a final audit pass over the full deliberation transcript
   and surfaces contradictions agents didn't resolve, unsupported claims, and
   over-extrapolations (e.g. clinical findings applied to healthy adults).

Both are best-effort: if the ``claude`` CLI isn't on PATH or WebFetch isn't
allowed, they degrade silently rather than blocking the user's flow.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Iterable


_CLAUDE_PATH: str | None = shutil.which("claude")

# Matches markdown links: [label](url)  — standard and the form our agents emit
_CITATION_RE = re.compile(r"\[([^\]]+?)\]\((https?://[^)\s]+)\)")


# ── data types ────────────────────────────────────────────

@dataclass
class VerifiedCitation:
    label: str
    url: str
    claim_context: str          # 200 chars of text surrounding the citation
    verified: bool = False      # True only if fetched page content backs the claim
    finding: str = ""           # one-sentence summary of what the page actually says
    extracted_quote: str = ""   # verbatim supporting quote, if any
    error: str | None = None    # populated if fetch or parse failed
    # Severity of a failed verification — distinguishes real reliability problems
    # from "can't check, might be fine" cases so the UI can treat them differently.
    # Values: "verified" | "paywalled" | "wrong_article" | "not_found" | "error"
    status: str = "verified"


@dataclass
class DeliberationAudit:
    contradictions: list[str] = field(default_factory=list)
    unsupported_claims: list[str] = field(default_factory=list)
    over_extrapolations: list[str] = field(default_factory=list)
    coverage_gaps: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (
            self.contradictions
            or self.unsupported_claims
            or self.over_extrapolations
            or self.coverage_gaps
        )


# ── citation extraction ──────────────────────────────────

def extract_citations(text: str, context_chars: int = 200) -> list[tuple[str, str, str]]:
    """Return every ``[label](url)`` in ``text`` with surrounding context.

    Context is the ``context_chars`` characters preceding the citation — used
    so the verifier knows what claim the citation was backing.
    """
    results: list[tuple[str, str, str]] = []
    for m in _CITATION_RE.finditer(text):
        label = m.group(1).strip()
        url = m.group(2).strip()
        start = max(0, m.start() - context_chars)
        context = text[start:m.end()].replace("\n", " ").strip()
        # Skip obvious non-citations: anchor links, agent dashboards, etc.
        if url.startswith("#"):
            continue
        results.append((label, url, context))
    return results


def extract_citations_from_transcript(
    transcript: Iterable[dict], max_total: int = 8,
) -> list[tuple[str, str, str, str]]:
    """Pull citations from every agent turn, tagged with agent name.

    Returns (agent_name, label, url, context). Capped at ``max_total`` to
    keep the verifier fast and cheap.
    """
    tagged: list[tuple[str, str, str, str]] = []
    seen_urls: set[str] = set()
    for entry in transcript:
        agent = entry.get("agent", "?")
        content = entry.get("content", "")
        for label, url, ctx in extract_citations(content):
            if url in seen_urls:
                continue
            seen_urls.add(url)
            tagged.append((agent, label, url, ctx))
            if len(tagged) >= max_total:
                return tagged
    return tagged


# ── Citationist: verify one URL ──────────────────────────

def _clean_env() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    return env


def _extract_json(raw: str) -> dict | None:
    """Find and parse a JSON object from a Claude response."""
    if not raw:
        return None
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def verify_citation(label: str, url: str, context: str) -> VerifiedCitation:
    """Fetch the URL and check whether its content supports the citation context."""
    cit = VerifiedCitation(
        label=label, url=url, claim_context=context[-400:],
    )
    if not _CLAUDE_PATH:
        cit.error = "claude CLI not found on PATH"
        return cit

    prompt = (
        "You are auditing a citation made during a multi-agent research deliberation.\n\n"
        f"URL: {url}\n\n"
        f"THE CITATION WAS USED TO SUPPORT THIS CLAIM (see end of context):\n"
        f"{context[-600:]}\n\n"
        "Use WebFetch to actually read the URL, then output ONLY this JSON "
        "(no other text, no markdown fences):\n"
        "{\n"
        '  "status": "verified" | "paywalled" | "wrong_article" | "not_found",\n'
        '  "finding": "one-sentence summary of what the page actually says or why it is unreadable",\n'
        '  "quote": "verbatim supporting quote (max 220 chars) or empty string"\n'
        "}\n\n"
        "STATUS DEFINITIONS (be strict — wrong_article and not_found are the worst):\n"
        "- verified     : page content substantively supports the claim. "
        "Tangentially related ≠ verified.\n"
        "- paywalled    : URL resolves but content is behind paywall/login (403, "
        "'sign in', journal-subscriber-only). The citation MAY be legitimate — "
        "we just can't check. Less severe than wrong_article.\n"
        "- wrong_article: URL resolves but the page is about something else "
        "entirely (common LLM failure mode — plausible-looking URL, wrong content).\n"
        "- not_found    : URL returns 404 or DNS error. The URL was hallucinated.\n\n"
        "The quote field must be a REAL verbatim string taken from the page, or "
        "empty string if you couldn't read it."
    )

    try:
        result = subprocess.run(
            [_CLAUDE_PATH, "-p",
             "--model", "haiku",
             "--effort", "low",
             "--allowedTools", "WebFetch",
             "--no-session-persistence"],
            input=prompt,
            capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            env=_clean_env(),
            timeout=90,
        )
    except subprocess.TimeoutExpired:
        cit.error = "verification timed out"
        return cit
    except Exception as exc:
        cit.error = f"{type(exc).__name__}: {str(exc)[:120]}"
        return cit

    data = _extract_json(result.stdout)
    if not data:
        cit.error = "verifier returned no parseable JSON"
        cit.status = "error"
        return cit

    status = str(data.get("status", "")).lower()
    if status not in ("verified", "paywalled", "wrong_article", "not_found"):
        # Back-compat: older verifier responses used boolean "verified"
        status = "verified" if data.get("verified") else "wrong_article"
    cit.status = status
    cit.verified = (status == "verified")
    cit.finding = str(data.get("finding", ""))[:400]
    cit.extracted_quote = str(data.get("quote", ""))[:320]
    return cit


def verify_citations_parallel(
    tagged_citations: list[tuple[str, str, str, str]],
    max_workers: int = 4,
) -> list[tuple[str, VerifiedCitation]]:
    """Run ``verify_citation`` concurrently over a batch.

    Returns [(agent_name, VerifiedCitation), ...] in the same order as input.
    """
    if not tagged_citations:
        return []

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [
            (agent, pool.submit(verify_citation, label, url, ctx))
            for (agent, label, url, ctx) in tagged_citations
        ]
        return [(agent, fut.result()) for agent, fut in futures]


# ── Verifier: end-of-deliberation audit ──────────────────

def audit_deliberation(
    transcript_entries: list[dict],
    user_question: str,
) -> DeliberationAudit:
    """Run a final-pass audit of the deliberation.

    Scholar's synthesis is included in the audit target — the auditor gets to
    check whether the synthesis smuggled in unsupported claims or papered
    over real contradictions.
    """
    audit = DeliberationAudit()
    if not _CLAUDE_PATH or not transcript_entries:
        return audit

    transcript = "\n\n".join(
        f"[{e.get('agent', '?')} ({e.get('role', '?')})]: "
        f"{str(e.get('content', ''))[:2400]}"
        for e in transcript_entries
    )[:16000]

    prompt = (
        "You are the Verifier — a final auditor for a multi-agent deliberation.\n"
        "Your job is to surface what the inline Skeptic may have missed, including "
        "important dimensions of the user's question the team never addressed.\n\n"
        f"USER'S ORIGINAL QUESTION:\n{user_question}\n\n"
        f"FULL TRANSCRIPT:\n{transcript}\n\n"
        "Output ONLY this JSON (no markdown, no commentary):\n"
        "{\n"
        '  "contradictions": [\n'
        '    "Specific unresolved disagreements — quote both sides"\n'
        "  ],\n"
        '  "unsupported_claims": [\n'
        '    "Specific assertions any agent made without evidence — quote the claim"\n'
        "  ],\n"
        '  "over_extrapolations": [\n'
        '    "Places where findings from one population (e.g., clinical) were '
        'applied to another (e.g., healthy adults) without justification — be specific"\n'
        "  ],\n"
        '  "coverage_gaps": [\n'
        '    "Important dimensions of the USER\'S QUESTION the team never addressed. '
        'For example: if the question is about daily-life mental health and the team '
        'covers exercise + sleep but skips social connection (one of the strongest '
        'predictors in the literature), flag it here. Max 15 words each."\n'
        "  ]\n"
        "}\n\n"
        "RULES:\n"
        "- Be SPECIFIC — quote or paraphrase the exact text you're flagging.\n"
        "- Max 3 items per category.\n"
        "- Empty arrays only if there genuinely aren't issues.\n"
        "- Do NOT repeat issues Skeptic already resolved inline.\n"
        "- For coverage_gaps: think about what an expert in this field would be "
        "surprised the team DIDN'T discuss, not just what they'd add as nice-to-have."
    )

    try:
        result = subprocess.run(
            [_CLAUDE_PATH, "-p",
             "--model", "haiku",
             "--effort", "medium",
             "--no-session-persistence"],
            input=prompt,
            capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            env=_clean_env(),
            timeout=90,
        )
    except Exception:
        return audit

    data = _extract_json(result.stdout)
    if not data:
        return audit

    audit.contradictions = [str(x) for x in data.get("contradictions", [])][:3]
    audit.unsupported_claims = [str(x) for x in data.get("unsupported_claims", [])][:3]
    audit.over_extrapolations = [str(x) for x in data.get("over_extrapolations", [])][:3]
    audit.coverage_gaps = [str(x) for x in data.get("coverage_gaps", [])][:3]
    return audit


# ── Synthesis brief: structured claim ledger before Scholar closes ──

def generate_synthesis_brief(
    transcript_entries: list[dict],
    user_question: str,
) -> str:
    """Distill the deliberation into a structured brief for the leader's synthesis.

    Surfaces every graded claim, every condition raised, every challenge and
    its resolution status. Handed to the leader as structured context right
    before they close, so the synthesis integrates from a concrete ledger
    instead of free-form recall — preventing silent promotion of Grade C
    claims to Grade A parity, flattened conditions, and smuggled claims.

    Returns a markdown-formatted brief (empty string on failure). The caller
    injects this into the leader's synthesis prompt.
    """
    if not _CLAUDE_PATH or not transcript_entries:
        return ""

    transcript = "\n\n".join(
        f"[{e.get('agent', '?')} ({e.get('role', '?')})]: "
        f"{str(e.get('content', ''))[:2200]}"
        for e in transcript_entries
    )[:15000]

    prompt = (
        "You are preparing a structured brief for a leader about to synthesize "
        "a multi-agent deliberation. Your output is a markdown ledger with "
        "four sections. The leader will INTEGRATE from this ledger — so be "
        "faithful, comprehensive, and structured.\n\n"
        f"USER'S QUESTION:\n{user_question}\n\n"
        f"DELIBERATION:\n{transcript}\n\n"
        "Output EXACTLY this markdown (no intro, no outro, no commentary):\n\n"
        "## GRADED CLAIMS\n"
        "- **[Claim text]** — Grade A/B/C/D — raised by [Agent] — evidence: [brief].\n"
        "- ...\n\n"
        "## CONDITIONS & CAVEATS\n"
        "- **[Condition]** — applies to [which claim] — raised by [Agent].\n"
        "- ...\n\n"
        "## UNRESOLVED DISAGREEMENTS\n"
        "- **[Issue]** — [Agent A] says X, [Agent B] says Y, status: unresolved.\n"
        "- ...\n\n"
        "## SKEPTIC'S STANDING CHALLENGES\n"
        "- **[Challenge]** — targets [claim/agent] — status: addressed/unaddressed.\n"
        "- ...\n\n"
        "RULES:\n"
        "- Extract from the ACTUAL text — don't invent claims or grades.\n"
        "- If a claim has no grade, mark 'Grade: unstated'.\n"
        "- Max 6 items per section; fewer is fine.\n"
        "- Preserve conditions exactly as phrased. Don't flatten 'only for X' to 'works'.\n"
        "- Empty section = '(none)'."
    )

    try:
        result = subprocess.run(
            [_CLAUDE_PATH, "-p",
             "--model", "haiku",
             "--effort", "medium",
             "--no-session-persistence"],
            input=prompt,
            capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            env=_clean_env(),
            timeout=60,
        )
    except Exception:
        return ""
    if result.returncode != 0:
        return ""
    return (result.stdout or "").strip()


# ── Mid-deliberation coverage pulse ────────────────────

def mid_deliberation_pulse(
    transcript_so_far: list[dict],
    user_question: str,
) -> list[str]:
    """At the deliberation midpoint, check what critical dimension the team is NOT on track to discuss.

    Returns up to 3 missing-dimension hints. Caller injects them as system
    messages so the remaining turns can redirect. Closes the gap that the
    end-of-deliberation Audit can only flag retrospectively.
    """
    if not _CLAUDE_PATH or not transcript_so_far:
        return []

    transcript = "\n\n".join(
        f"[{e.get('agent', '?')}]: {str(e.get('content', ''))[:1500]}"
        for e in transcript_so_far
    )[:10000]

    prompt = (
        "You are a mid-deliberation coverage auditor. The team is halfway "
        "through; you're checking what critical dimension of the user's "
        "question they're NOT on track to address.\n\n"
        f"USER'S QUESTION:\n{user_question}\n\n"
        f"DELIBERATION SO FAR:\n{transcript}\n\n"
        "Identify up to 3 dimensions an expert would be SURPRISED the team "
        "hasn't discussed — not nice-to-haves, but load-bearing aspects. "
        "Output ONLY this JSON:\n"
        "{\n"
        '  "missing_dimensions": [\n'
        '    "Specific dimension — one-sentence description of what the '
        'team should add before closing"\n'
        "  ]\n"
        "}\n\n"
        "RULES:\n"
        "- Be SPECIFIC. 'Discuss more nuance' is not a dimension.\n"
        "- For resilience: social connection, cognitive reappraisal, "
        "individual stratification are examples of load-bearing dimensions.\n"
        "- For philosophical questions: historical positions, key "
        "counter-arguments, practical implications are examples.\n"
        "- Empty list [] if the team is covering the territory well."
    )

    try:
        result = subprocess.run(
            [_CLAUDE_PATH, "-p",
             "--model", "haiku",
             "--effort", "low",
             "--no-session-persistence"],
            input=prompt,
            capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            env=_clean_env(),
            timeout=40,
        )
    except Exception:
        return []
    if result.returncode != 0:
        return []
    data = _extract_json(result.stdout)
    if not data:
        return []
    return [str(x) for x in data.get("missing_dimensions", [])][:3]
