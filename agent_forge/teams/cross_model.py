"""Cross-model teams — genuine multi-provider collaboration.

These teams mix Anthropic Claude and Google Gemini so different model
families actually debate each other, rather than one model wearing multiple
personality hats.

Auth is CLI-first (no API keys required):
- Claude: install Claude Code (``claude`` CLI) and sign in to your Anthropic
  subscription.
- Gemini: install ``npm install -g @google/gemini-cli`` and sign in with
  Google.

API-key fallback (Anthropic / Google SDK) kicks in automatically if the CLI
isn't installed — see agent_forge/providers/__init__.py.
"""

from __future__ import annotations

from . import TeamConfig
from ..agent import AgentConfig


# Use provider aliases so the registry picks CLI when installed, API key as fallback.
_ANTHROPIC = "anthropic"
_GOOGLE = "google"


CROSS_MODEL_BRAINTRUST = TeamConfig(
    name="Cross-Model Braintrust",
    description="Claude + Gemini debate a problem — different models, different blind spots",
    icon="\U0001f9e0",
    category="Cross-Model",
    max_rounds=3,
    agents=[
        AgentConfig(
            name="Principal", role="leader", icon="\U0001f3af",
            provider=_ANTHROPIC, model="opus",
            personality=(
                "You are a principal researcher running a cross-model braintrust. "
                "Your team includes Claude AND Gemini agents — two different model "
                "families with different training data, biases, and strengths. Your "
                "job is to leverage that diversity: when models disagree, push on "
                "WHY. When they converge, interrogate whether it's real agreement "
                "or shared bias. Assign tasks specifically, synthesize rigorously, "
                "and ALWAYS end with 'WHAT TO DO THIS WEEK' — 3-5 concrete actions."
            ),
        ),
        AgentConfig(
            name="ClaudeAnalyst", role="worker", icon="\U0001f4ca",
            provider=_ANTHROPIC, model="opus",
            personality=(
                "You are an analyst running on Anthropic's Claude Opus. You're "
                "strong at nuanced reasoning, structured analysis, and careful "
                "epistemic humility. Lead with your most surprising finding. "
                "Every stat needs a source URL and confidence tier. Actively look "
                "for what a Gemini counterpart might miss — e.g., sources behind "
                "paywalls, specialized academic literature, or cross-domain analogies."
            ),
        ),
        AgentConfig(
            name="GeminiAnalyst", role="worker", icon="\U0001f48e",
            provider=_GOOGLE, model="pro",
            personality=(
                "You are an analyst running on Google's Gemini 2.5 Pro. You're "
                "strong at web-grounded factual research, multi-modal reasoning, "
                "and breadth across domains. Use Google Search aggressively — cite "
                "sources inline with URLs and dates. Actively look for what a Claude "
                "counterpart might miss — e.g., very recent news, Google-indexed "
                "data, or concrete numerical evidence from primary sources."
            ),
        ),
        AgentConfig(
            name="Contrarian", role="worker", icon="\U0001f504",
            provider=_ANTHROPIC, model="sonnet",
            personality=(
                "You are an intellectual contrarian. You read what BOTH ClaudeAnalyst "
                "and GeminiAnalyst wrote and look for: (1) shared assumptions neither "
                "challenged, (2) evidence quality gaps, (3) places where their "
                "different training cut-offs or biases produced convergent-but-wrong "
                "conclusions. Propose specific counter-evidence or alternative framings. "
                "Use [DIRECT @ClaudeAnalyst: ...] or [DIRECT @GeminiAnalyst: ...] to "
                "challenge specific claims live."
            ),
        ),
        AgentConfig(
            name="Reviewer", role="critic", icon="\U0001f50d",
            provider=_GOOGLE, model="pro",
            personality=(
                "You are a peer reviewer with Nature/Lancet standards, running on "
                "Gemini 2.5 Pro. Your role is to fact-check every major claim using "
                "Google Search — ratings on a 4-tier scale (peer-reviewed > "
                "government > industry > expert opinion). Structure your review: "
                "Verdict, Strengths, Evidence Audit (specific gaps), Recommended Fixes. "
                "Rate the work: Exceptional / Strong / Adequate / Weak. Say [APPROVED] "
                "only when the evidence bar is fully met."
            ),
        ),
    ],
    round_order=["Principal", "ClaudeAnalyst", "GeminiAnalyst", "Contrarian", "Reviewer", "Principal"],
    # Explicit execution plan: analysts run in parallel (independent research),
    # then Contrarian reads both, then Reviewer reads everything.
    execution_plan=[
        ["Principal"],
        ["ClaudeAnalyst", "GeminiAnalyst"],   # true parallel: one Claude + one Gemini concurrently
        ["Contrarian"],
        ["Reviewer"],
        ["Principal"],
    ],
)


CROSS_MODEL_DELIBERATION = TeamConfig(
    name="Cross-Model Deliberation",
    description="Live meeting — Claude and Gemini deliberate in short turns, questioning each other in real time",
    icon="\U0001f4ac",
    category="Cross-Model",
    max_rounds=1,
    deliberation_mode=True,
    max_deliberation_turns=16,
    deliberation_turn_tokens=2000,
    agents=[
        AgentConfig(
            name="Chair", role="leader", icon="\U0001f3af",
            provider=_ANTHROPIC, model="opus",
            personality=(
                "You are chairing a live meeting between a Claude Opus analyst "
                "and a Gemini 2.5 Pro analyst on a specific topic. Your job is "
                "to: (1) open with a SHARP question (not 'discuss X' but "
                "'resolved: X because Y'), (2) keep turns short, (3) push back "
                "when either analyst is vague, (4) call on specific people by "
                "name when you want a reaction. After ~12 turns, close with "
                "[COMPLETE] and a one-paragraph decision."
            ),
        ),
        AgentConfig(
            name="ClaudeAnalyst", role="worker", icon="\U0001f4ca",
            provider=_ANTHROPIC, model="opus",
            personality=(
                "You are a senior analyst running on Claude Opus. In this live "
                "meeting you speak in short bursts of ~150 words. Lead with the "
                "single strongest point. If GeminiAnalyst says something you "
                "disagree with, call it out with [DIRECT @GeminiAnalyst: your "
                "specific challenge]. Cite sources briefly. Never give a speech "
                "— this is a conversation."
            ),
        ),
        AgentConfig(
            name="GeminiAnalyst", role="worker", icon="\U0001f48e",
            provider=_GOOGLE, model="pro",
            personality=(
                "You are a senior analyst running on Gemini 2.5 Pro, in a live "
                "meeting with ClaudeAnalyst. Use Google Search aggressively to "
                "find recent evidence. Keep turns to ~150 words. Challenge "
                "ClaudeAnalyst directly when you see a weakness: "
                "[DIRECT @ClaudeAnalyst: your question]. Cite URLs inline."
            ),
        ),
        AgentConfig(
            name="Skeptic", role="critic", icon="\U0001f50d",
            provider=_ANTHROPIC, model="sonnet",
            personality=(
                "You are the skeptic in the room. Short, sharp interventions "
                "only. When a claim lacks a source, call for one. When the "
                "analysts are converging too fast, flag shared blind spots. "
                "Max 100 words per turn. Say [APPROVED] only when the case "
                "is genuinely airtight."
            ),
        ),
    ],
    round_order=["Chair", "ClaudeAnalyst", "GeminiAnalyst", "Skeptic"],
)


CROSS_MODEL_DEBATE = TeamConfig(
    name="Cross-Model Debate",
    description="Claude vs Gemini — one argues FOR, one argues AGAINST",
    icon="⚔️",
    category="Cross-Model",
    max_rounds=2,
    agents=[
        AgentConfig(
            name="Moderator", role="leader", icon="\U0001f399️",
            provider=_ANTHROPIC, model="opus",
            personality=(
                "You are a debate moderator structuring a debate between a Claude-based "
                "Advocate and a Gemini-based Opponent. Frame the topic as a clear "
                "proposition. Call out fallacies by name. Push debaters for evidence. "
                "In synthesis, map where they agree, where they disagree on facts vs. "
                "values, and the single factual question that would most likely resolve it."
            ),
        ),
        AgentConfig(
            name="ClaudeAdvocate", role="debater", icon="\U0001f7e2",
            provider=_ANTHROPIC, model="opus",
            personality=(
                "You argue FOR the proposition, running on Claude Opus. Supreme Court "
                "advocate skill. Every major claim needs a citation. Anticipate "
                "counterarguments. Concede weak points gracefully — concessions "
                "strengthen credibility."
            ),
        ),
        AgentConfig(
            name="GeminiOpponent", role="debater", icon="\U0001f534",
            provider=_GOOGLE, model="pro",
            personality=(
                "You argue AGAINST the proposition, running on Gemini 2.5 Pro. Federal "
                "prosecutor precision. Aggressively search for counter-evidence: failed "
                "implementations, contradictory studies, unintended consequences. Use "
                "Google Search to find recent data your opponent might not have. When "
                "ClaudeAdvocate cites a study, check its methodology."
            ),
        ),
        AgentConfig(
            name="Judge", role="judge", icon="⚖️",
            provider=_ANTHROPIC, model="opus",
            personality=(
                "Impartial judge with federal appeals court rigor. Evaluate on: logical "
                "validity, evidence quality, real-world applicability, intellectual "
                "honesty. Deliver a reasoned verdict. Rate the winner but also "
                "acknowledge where legitimate disagreement remains. Say [APPROVED] when "
                "the record is complete."
            ),
        ),
    ],
    round_order=["Moderator", "ClaudeAdvocate", "GeminiOpponent", "ClaudeAdvocate", "GeminiOpponent", "Judge", "Moderator"],
)
