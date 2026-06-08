"""Compile Agent Forge research artifacts into Wonderlab episode specs."""

from __future__ import annotations

import json
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from typing import Callable

from .fixtures import money_dossier
from .manual_packets import apply_manual_source_packets
from .schema import (
    BuildMode,
    EpisodeScene,
    EpisodeSpec,
    EvalReport,
    InteractionSpec,
    InteractionVariable,
    ResearchDossier,
    StageResult,
    Source,
    WonderlabRun,
)
from .source_verifier import (
    FetchedPage,
    summarize_source_verification,
    verify_sources as verify_episode_sources,
)
from .simulations import (
    bank_run_resilience,
    barter_success_rate,
    inflation_pressure,
)


def build_money_episode(
    mode: BuildMode = "deep",
    verify_sources: bool = False,
    source_fetcher: Callable[[Source], FetchedPage] | None = None,
) -> WonderlabRun:
    """Build the first deterministic Wonderlab vertical slice."""
    dossier = money_dossier()
    source_stage_summary = "Skipped network verification; sources remain seeded."
    if verify_sources:
        verified_sources = verify_episode_sources(
            dossier.source_graph,
            fetcher=source_fetcher,
        )
        verified_sources = apply_manual_source_packets(verified_sources)
        dossier = replace(dossier, source_graph=verified_sources)
        source_stage_summary = summarize_source_verification(verified_sources)

    episode = compile_dossier_to_episode(dossier, mode=mode)
    eval_report = evaluate_episode(dossier, episode)
    return WonderlabRun(
        run_id=_run_id("money"),
        topic=dossier.topic,
        mode=mode,
        stages=[
            StageResult(
                stage="topic-intake",
                agent_role="Narrative Director",
                summary="Converted the topic into a central mystery and episode promise.",
                artifact_ids=["central_mystery"],
            ),
            StageResult(
                stage="research-dossier",
                agent_role="Research Swarm",
                summary="Loaded a seeded Money dossier with claims, sources, concepts, and controversies.",
                artifact_ids=[claim.id for claim in dossier.claim_ledger],
            ),
            StageResult(
                stage="source-verification",
                agent_role="Citation Auditor",
                summary=source_stage_summary,
                artifact_ids=[source.id for source in dossier.source_graph],
            ),
            StageResult(
                stage="scene-compiler",
                agent_role="Interaction Designer",
                summary="Compiled dossier claims into documentary scenes and simulation blueprints.",
                artifact_ids=[scene.id for scene in episode.scenes],
            ),
            StageResult(
                stage="eval-gauntlet",
                agent_role="Citation Auditor",
                summary="Checked claim-source-scene linkage and flagged source verification as the next gate.",
                artifact_ids=["eval_report"],
            ),
        ],
        dossier=dossier,
        episode=episode,
        eval_report=eval_report,
    )


def compile_dossier_to_episode(
    dossier: ResearchDossier,
    mode: BuildMode = "deep",
) -> EpisodeSpec:
    """Turn a research dossier into a renderer-ready episode."""
    source_by_claim = {
        claim.id: claim.sources
        for claim in dossier.claim_ledger
    }

    def refs(claim_ids: list[str]) -> list[str]:
        out: list[str] = []
        for claim_id in claim_ids:
            for source_id in source_by_claim.get(claim_id, []):
                if source_id not in out:
                    out.append(source_id)
        return out

    barter_snapshot = barter_success_rate(0.22, 0.35, 18)
    bank_snapshot = bank_run_resilience(0.12, 0.08, 0.6)
    inflation_snapshot = inflation_pressure(0.08, 0.02, 0.03, 0.04)

    scenes = [
        EpisodeScene(
            id="scene-intro",
            title="The Shared Fiction",
            scene_type="cinematic-intro",
            learning_goal="Make money feel strange before explaining it.",
            hook="A number on a screen can move a ship, hire a surgeon, or start a war.",
            narration=[
                dossier.central_mystery,
                "The episode follows money as a trust machine: symbol, ledger, institution, and protocol.",
            ],
            visual_direction=(
                "Full-bleed macro shots of coins, receipts, bank ledgers, payment terminals, "
                "and database rows cutting into a glowing account balance."
            ),
            claims_used=["claim-money-social-technology"],
            source_refs=refs(["claim-money-social-technology"]),
            estimated_reading_time_seconds=55,
        ),
        EpisodeScene(
            id="scene-barter-game",
            title="The Barter Trap",
            scene_type="interactive-simulation",
            learning_goal="Show why direct exchange breaks when wants do not align.",
            hook="You have fish. You need shoes. The shoemaker wants grain.",
            narration=[
                "Barter is a useful puzzle, but it is not the whole origin story.",
                "The real lesson is coordination: money makes indirect exchange easier.",
            ],
            visual_direction="A network of traders where successful matches glow and failed wants fade.",
            claims_used=["claim-barter-origin-disputed"],
            source_refs=refs(["claim-barter-origin-disputed"]),
            estimated_reading_time_seconds=90,
            interaction=InteractionSpec(
                type="barter-mini-game",
                title="Find a trade path",
                variables=[
                    InteractionVariable(
                        id="wants_overlap",
                        label="Wants overlap",
                        min=0,
                        max=1,
                        default=0.22,
                        explanation="How often two traders want what the other has.",
                    ),
                    InteractionVariable(
                        id="trust",
                        label="Trust",
                        min=0,
                        max=1,
                        default=0.35,
                        explanation="How willing traders are to accept delayed or indirect value.",
                    ),
                    InteractionVariable(
                        id="market_size",
                        label="Market size",
                        min=2,
                        max=100,
                        default=18,
                        explanation="How many possible counterparties exist.",
                    ),
                ],
                outputs=asdict(barter_snapshot),
                learning_reveal=(
                    "Money does not merely replace barter; it expands who can trade with whom."
                ),
                renderer_hint="Use a force-directed exchange graph with pathfinding feedback.",
            ),
        ),
        EpisodeScene(
            id="scene-debt-ledgers",
            title="Before Coins, There Were Ledgers",
            scene_type="scroll-story",
            learning_goal="Introduce credit, debt, and accounting as monetary foundations.",
            hook="A debt written down can move value before a coin ever changes hands.",
            narration=[
                "Money is also memory: who owes what, to whom, and under whose authority.",
                "This is why the barter-first story becomes more interesting when debt enters the room.",
            ],
            visual_direction="Clay-tablet inspired entries transforming into modern database rows.",
            claims_used=["claim-barter-origin-disputed", "claim-states-shape-currency"],
            source_refs=refs(["claim-barter-origin-disputed", "claim-states-shape-currency"]),
            estimated_reading_time_seconds=110,
        ),
        EpisodeScene(
            id="scene-states-armies",
            title="Taxes, Armies, and Standard Coins",
            scene_type="timeline",
            learning_goal="Show how authority can standardize monetary systems.",
            hook="A state can make money matter by demanding it back as taxes.",
            narration=[
                "Markets matter, but so do laws, taxes, wages, armies, and courts.",
                "Money becomes more powerful when institutions make it the official language of obligation.",
            ],
            visual_direction="A horizontal timeline connecting minting, taxation, payroll, and legal tender.",
            claims_used=["claim-states-shape-currency"],
            source_refs=refs(["claim-states-shape-currency"]),
            estimated_reading_time_seconds=85,
        ),
        EpisodeScene(
            id="scene-banking-trust",
            title="The Money Banks Create",
            scene_type="systems-diagram",
            learning_goal="Make deposit creation legible without pretending banks are magic.",
            hook="A loan can create a deposit before anyone prints new cash.",
            narration=[
                "Modern money is partly created through bank balance sheets.",
                "That makes trust, regulation, and liquidity part of the monetary machine.",
            ],
            visual_direction="Split balance-sheet animation: loan asset appears as deposit liability.",
            claims_used=["claim-bank-deposit-creation"],
            source_refs=refs(["claim-bank-deposit-creation"]),
            estimated_reading_time_seconds=100,
        ),
        EpisodeScene(
            id="scene-bank-run",
            title="How Trust Breaks Fast",
            scene_type="interactive-simulation",
            learning_goal="Let users feel the speed of a liquidity crisis.",
            hook="The danger is not only how much money leaves. It is how fast.",
            narration=[
                "A bank run compresses trust failure into hours or days.",
                "Liquid reserves buy time; panic spends it.",
            ],
            visual_direction="A reserve tank draining into withdrawal streams while long-term assets stay locked.",
            claims_used=["claim-bank-runs-speed-trust", "claim-bank-deposit-creation"],
            source_refs=refs(["claim-bank-runs-speed-trust", "claim-bank-deposit-creation"]),
            estimated_reading_time_seconds=95,
            interaction=InteractionSpec(
                type="bank-run-model",
                title="Reserve runway",
                variables=[
                    InteractionVariable(
                        id="reserve_ratio",
                        label="Reserve ratio",
                        min=0.01,
                        max=0.5,
                        default=0.12,
                        explanation="Liquid reserves as a share of deposits.",
                    ),
                    InteractionVariable(
                        id="daily_withdrawal_rate",
                        label="Daily withdrawals",
                        min=0.01,
                        max=0.4,
                        default=0.08,
                        explanation="Share of deposits customers try to withdraw each day.",
                    ),
                    InteractionVariable(
                        id="confidence_shock",
                        label="Confidence shock",
                        min=0,
                        max=1,
                        default=0.6,
                        explanation="Panic multiplier on normal withdrawals.",
                    ),
                ],
                outputs=asdict(bank_snapshot),
                learning_reveal="Liquidity is time. Trust decides how quickly time disappears.",
                renderer_hint="Use a balance-sheet panel beside an animated reserve gauge.",
            ),
        ),
        EpisodeScene(
            id="scene-inflation-lab",
            title="Inflation Is a System",
            scene_type="interactive-simulation",
            learning_goal="Replace one-cause inflation stories with a multi-variable mental model.",
            hook="Move one slider and prices twitch. Move four and the system starts talking.",
            narration=[
                "This lab is not a forecast; it is a map of pressures.",
                "Money, goods, velocity, shocks, and expectations push on prices together.",
            ],
            visual_direction="A control room with four sliders feeding a pressure gauge and price index trail.",
            claims_used=["claim-inflation-system"],
            source_refs=refs(["claim-inflation-system"]),
            estimated_reading_time_seconds=100,
            interaction=InteractionSpec(
                type="inflation-pressure-model",
                title="Price pressure board",
                variables=[
                    InteractionVariable(
                        id="money_growth",
                        label="Money growth",
                        min=-0.05,
                        max=0.25,
                        default=0.08,
                        explanation="How quickly the money supply expands.",
                    ),
                    InteractionVariable(
                        id="goods_growth",
                        label="Goods growth",
                        min=-0.05,
                        max=0.15,
                        default=0.02,
                        explanation="How quickly goods and services supply expands.",
                    ),
                    InteractionVariable(
                        id="velocity_change",
                        label="Velocity",
                        min=-0.1,
                        max=0.2,
                        default=0.03,
                        explanation="How quickly money changes hands.",
                    ),
                    InteractionVariable(
                        id="expectations_shock",
                        label="Expectations",
                        min=-0.1,
                        max=0.2,
                        default=0.04,
                        explanation="How strongly people expect prices to rise.",
                    ),
                ],
                outputs=asdict(inflation_snapshot),
                learning_reveal=(
                    "Inflation debates are often fights over which pressure deserves the most weight."
                ),
                renderer_hint="Use linked sliders, a gauge, and a small uncertainty band.",
            ),
        ),
        EpisodeScene(
            id="scene-debate",
            title="Why Smart People Disagree",
            scene_type="debate",
            learning_goal="Make disagreement legible instead of smoothing it away.",
            hook="The history of money is partly a fight over which story gets to be called obvious.",
            narration=[
                "Wonderlab does not hide interpretive conflict.",
                "This room separates factual disputes, framing disputes, and emphasis disputes.",
            ],
            visual_direction=(
                "Three debate lanes for source scout, research critic, and synthesis director, "
                "with the resolved episode choice highlighted at the bottom."
            ),
            claims_used=[
                "claim-barter-origin-disputed",
                "claim-states-shape-currency",
                "claim-inflation-system",
            ],
            source_refs=refs([
                "claim-barter-origin-disputed",
                "claim-states-shape-currency",
                "claim-inflation-system",
            ]),
            estimated_reading_time_seconds=105,
        ),
        EpisodeScene(
            id="scene-crypto-debate",
            title="Protocol Trust",
            scene_type="debate",
            learning_goal="Frame crypto as a trust tradeoff, not trustlessness.",
            hook="What if the institution is replaced by code, but the code still needs people?",
            narration=[
                "Crypto changes who or what users trust.",
                "The debate is whether that substitution solves more problems than it creates.",
            ],
            visual_direction="Two-column debate chamber: institutional trust versus protocol trust.",
            claims_used=["claim-crypto-protocol-trust"],
            source_refs=refs(["claim-crypto-protocol-trust"]),
            estimated_reading_time_seconds=95,
        ),
        EpisodeScene(
            id="scene-source-lens",
            title="Show Me the Evidence",
            scene_type="source-gallery",
            learning_goal="Expose claims, confidence, and sources without derailing the story.",
            hook="Every glowing claim has wiring behind the wall.",
            narration=[
                "The source lens lets users inspect what the episode asserts, what supports it, and what remains disputed.",
            ],
            visual_direction="Claim cards connected to source cards and controversy markers.",
            claims_used=[claim.id for claim in dossier.claim_ledger],
            source_refs=[source.id for source in dossier.source_graph],
            estimated_reading_time_seconds=120,
        ),
        EpisodeScene(
            id="scene-synthesis",
            title="What Money Really Buys",
            scene_type="synthesis-challenge",
            learning_goal="Ask the user to synthesize money as trust, memory, power, and protocol.",
            hook="Design a new money. What do people have to believe for it to work?",
            narration=[
                dossier.one_sentence_thesis,
                "The final challenge asks users to choose which trust failures their money system can survive.",
            ],
            visual_direction="A final design board where the user's choices light up risks and tradeoffs.",
            claims_used=[
                "claim-money-social-technology",
                "claim-bank-runs-speed-trust",
                "claim-inflation-system",
                "claim-crypto-protocol-trust",
            ],
            source_refs=refs([
                "claim-money-social-technology",
                "claim-bank-runs-speed-trust",
                "claim-inflation-system",
                "claim-crypto-protocol-trust",
            ]),
            estimated_reading_time_seconds=120,
        ),
    ]

    return EpisodeSpec(
        id="episode-money-shared-fiction",
        title="Money: The Shared Fiction That Runs the World",
        subtitle="A playable documentary about trust, ledgers, banks, inflation, and protocol money.",
        topic=dossier.topic,
        central_mystery=dossier.central_mystery,
        mode=mode,
        scenes=scenes,
        claim_ledger=dossier.claim_ledger,
        source_graph=dossier.source_graph,
        disagreements=dossier.disagreements,
    )


def evaluate_episode(dossier: ResearchDossier, episode: EpisodeSpec) -> EvalReport:
    """Run deterministic linkage checks before a live evaluator exists."""
    required_fixes: list[str] = []
    notes: list[str] = []

    claim_ids = {claim.id for claim in dossier.claim_ledger}
    source_ids = {source.id for source in dossier.source_graph}
    scene_ids = {scene.id for scene in episode.scenes}

    for claim in dossier.claim_ledger:
        missing_sources = [source for source in claim.sources if source not in source_ids]
        if missing_sources:
            required_fixes.append(
                f"{claim.id} references missing sources: {', '.join(missing_sources)}"
            )
        missing_scenes = [scene for scene in claim.used_in_scenes if scene not in scene_ids]
        if missing_scenes:
            required_fixes.append(
                f"{claim.id} references missing scenes: {', '.join(missing_scenes)}"
            )

    for scene in episode.scenes:
        missing_claims = [claim for claim in scene.claims_used if claim not in claim_ids]
        if missing_claims:
            required_fixes.append(
                f"{scene.id} references missing claims: {', '.join(missing_claims)}"
            )
        missing_sources = [source for source in scene.source_refs if source not in source_ids]
        if missing_sources:
            required_fixes.append(
                f"{scene.id} references missing sources: {', '.join(missing_sources)}"
            )

    statuses = {source.verification_status for source in dossier.source_graph}
    seeded_sources = [
        source.id for source in dossier.source_graph
        if source.verification_status == "seeded-not-fetched"
    ]
    human_review_sources = [
        source.id for source in dossier.source_graph
        if source.verification_status in {
            "needs-human-review",
            "access-blocked",
            "manual-packet",
        }
    ]
    failed_sources = [
        source.id for source in dossier.source_graph
        if source.verification_status in {
            "fetch-error",
            "not-found",
            "reachable-title-mismatch",
        }
    ]

    if seeded_sources:
        required_fixes.append(
            "Seed sources must be fetched, quoted, and verified before public publication."
        )
        notes.append("This is expected for the offline vertical slice.")
    if human_review_sources:
        required_fixes.append(
            "Sources requiring human review: " + ", ".join(human_review_sources)
        )
    if failed_sources:
        required_fixes.append(
            "Source verification failed for: " + ", ".join(failed_sources)
        )

    claims_with_sources = sum(1 for claim in dossier.claim_ledger if claim.sources)
    claims_with_scenes = sum(1 for claim in dossier.claim_ledger if claim.used_in_scenes)
    interactive_scenes = sum(1 for scene in episode.scenes if scene.interaction is not None)
    verified_statuses = {"verified", "verified-pdf", "verified-manual"}
    verified_sources = sum(
        1 for source in dossier.source_graph
        if source.verification_status in verified_statuses
    )
    verification_coverage = round(
        (verified_sources / max(1, len(dossier.source_graph))) * 100
    )

    citation_coverage = round((claims_with_sources / max(1, len(dossier.claim_ledger))) * 100)
    claim_scene_coverage = round((claims_with_scenes / max(1, len(dossier.claim_ledger))) * 100)
    interaction_value = min(100, 55 + (interactive_scenes * 12))
    source_quality = max(30, min(96, 48 + round(verification_coverage * 0.45)))
    if "not-found" in statuses or "reachable-title-mismatch" in statuses:
        hallucination_risk = 72
    elif "fetch-error" in statuses:
        hallucination_risk = 52
    elif required_fixes:
        hallucination_risk = 35
    else:
        hallucination_risk = 12

    if failed_sources:
        publish_decision = "revise"
    elif required_fixes:
        publish_decision = "human-review"
    else:
        publish_decision = "publish"

    return EvalReport(
        factual_accuracy=min(92, 68 + round(verification_coverage * 0.18)),
        citation_coverage=citation_coverage,
        claim_scene_coverage=claim_scene_coverage,
        source_quality=source_quality,
        conceptual_depth=84,
        narrative_arc=88,
        interaction_value=interaction_value,
        accessibility=76,
        performance_risk=28,
        hallucination_risk=hallucination_risk,
        publish_decision=publish_decision,
        required_fixes=required_fixes,
        notes=notes,
    )


def write_wonderlab_run(run: WonderlabRun, path: str | Path) -> Path:
    """Write a complete Wonderlab run artifact as pretty JSON."""
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(asdict(run), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return out_path


def _run_id(slug: str) -> str:
    return f"wonderlab_{slug}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
