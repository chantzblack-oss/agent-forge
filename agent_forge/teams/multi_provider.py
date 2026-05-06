"""Tri-model team configurations using phase-4 provider routing.

These teams demonstrate cost-aware model mixing across providers:
leader runs on a flagship model (Opus), workers on mid-tier (Sonnet),
critic on cheap-fast (Haiku). Phase-4 prefix routing dispatches each
agent's model string to the correct provider automatically.

For a true cross-provider mix (Claude leader + GPT worker + Gemini
critic), set the model strings to e.g. "opus", "gpt-5", "gemini-2.5-pro".
"""

from __future__ import annotations

from ..agent import AgentConfig
from . import TeamConfig


TRI_MODEL_RESEARCH_LAB = TeamConfig(
    name="Tri-Model Research Lab",
    description="Cost-aware multi-perspective research with model mixing across providers",
    icon="\U0001f52c",
    category="Work",
    max_rounds=2,
    quickstart_goals=[
        "Run a cost-aware research pass on the question of your choice",
    ],
    agents=[
        AgentConfig(
            name="Principal", role="leader", model="opus", icon="\U0001f52c",
            tagline="Synthesis on a flagship; cheaper models do the legwork",
            personality=(
                "You are a principal researcher at McKinsey senior partner caliber. You "
                "decompose complex questions, assign them to specialists, then synthesize "
                "findings into decision-driving reports. NEVER restate data your team "
                "presented. Your synthesis must ADD value. Always end with 'WHAT TO DO "
                "THIS WEEK' — 3-5 specific actions."
            ),
        ),
        AgentConfig(
            name="Analyst", role="worker", model="sonnet", icon="\U0001f4ca",
            tagline="Mid-tier model handling the data crunch",
            personality=(
                "Senior data analyst with CFA-level rigor. For every stat: confidence label "
                "+ source URL + publication date. Prefer government databases and peer-"
                "reviewed journals. Lead with your most surprising finding."
            ),
        ),
        AgentConfig(
            name="Contrarian", role="worker", model="sonnet", icon="\U0001f504",
            tagline="Mid-tier counterargument generator",
            personality=(
                "Intellectual contrarian with appellate attorney sharpness. For EVERY "
                "problem you identify, propose a specific alternative. Search for counter-"
                "evidence. Distinguish fatal flaws from manageable risks."
            ),
        ),
        AgentConfig(
            name="Reviewer", role="critic", model="haiku", icon="\U0001f50d",
            tagline="Fast, cheap evidence audit",
            stale_evidence_months=12,
            personality=(
                "Skeptical reviewer. Verdict > Strengths > Issues with Fixes > Evidence "
                "Check. Spot-check at least one key claim with your own web search. Rate: "
                "Exceptional / Strong / Adequate / Weak."
            ),
        ),
    ],
    round_order=["Principal", "Analyst", "Contrarian", "Reviewer", "Principal"],
)


CROSS_PROVIDER_RESEARCH_LAB = TeamConfig(
    name="Cross-Provider Research Lab",
    description="Claude leader, GPT worker, Gemini contrarian — native cross-model team",
    icon="\U0001f30d",
    category="Work",
    max_rounds=2,
    quickstart_goals=[
        "Run a cross-provider research pass on a single hard question",
    ],
    agents=[
        AgentConfig(
            name="Principal", role="leader", model="opus", icon="\U0001f52c",
            tagline="Claude Opus synthesizes",
            personality=(
                "You are a principal researcher synthesizing input from a team that runs "
                "on different model providers. Reconcile their perspectives explicitly. "
                "End with 'WHAT TO DO THIS WEEK' — 3-5 specific actions."
            ),
        ),
        AgentConfig(
            name="Analyst", role="worker", model="gpt-5", icon="\U0001f4ca",
            tagline="GPT-5 handles quantitative analysis",
            personality=(
                "Senior data analyst. For every stat: confidence label + source URL + "
                "publication date. Lead with your most surprising finding."
            ),
        ),
        AgentConfig(
            name="Contrarian", role="worker", model="gemini-2.5-pro", icon="\U0001f504",
            tagline="Gemini hunts the counterevidence",
            personality=(
                "Intellectual contrarian. For EVERY problem you identify, propose a "
                "specific alternative. Search for counter-evidence. Distinguish fatal "
                "flaws from manageable risks."
            ),
        ),
        AgentConfig(
            name="Reviewer", role="critic", model="haiku", icon="\U0001f50d",
            tagline="Haiku does the fast evidence audit",
            stale_evidence_months=12,
            personality=(
                "Skeptical reviewer. Verdict > Strengths > Issues with Fixes > Evidence "
                "Check. Spot-check at least one key claim with your own web search."
            ),
        ),
    ],
    round_order=["Principal", "Analyst", "Contrarian", "Reviewer", "Principal"],
)
