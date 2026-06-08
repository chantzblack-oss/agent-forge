"""Seed dossiers used before live model orchestration is connected."""

from __future__ import annotations

from .schema import (
    Claim,
    ClaimEvidence,
    Concept,
    Disagreement,
    ModelPosition,
    ResearchDossier,
    Source,
    TimelineEvent,
)


def money_dossier() -> ResearchDossier:
    """Return the flagship Wonderlab seed dossier.

    Sources are intentionally marked ``seeded-not-fetched``. The live Agent
    Forge phase should replace or verify them before public publication.
    """
    sources = [
        Source(
            id="src-imf-what-is-money",
            title="Money: At the Center of Transactions",
            source_type="institutional",
            publisher="International Monetary Fund",
            year="2012",
            url="https://www.imf.org/en/Publications/fandd/issues/Series/Back-to-Basics/Money",
            notes="Seed reference for money functions and basic monetary concepts.",
        ),
        Source(
            id="src-boe-money-creation",
            title="Money creation in the modern economy",
            source_type="institutional",
            publisher="Bank of England Quarterly Bulletin",
            year="2014",
            url="https://www.bankofengland.co.uk/quarterly-bulletin/2014/q1/money-creation-in-the-modern-economy",
            notes="Seed reference for bank deposit creation.",
        ),
        Source(
            id="src-fed-money-supply",
            title="Federal Reserve money supply FAQ",
            source_type="institutional",
            publisher="Federal Reserve",
            year="",
            url="https://www.federalreserve.gov/faqs/money_12845.htm",
            notes="Seed reference for money supply concepts.",
        ),
        Source(
            id="src-graeber-debt",
            title="Debt: The First 5,000 Years",
            source_type="book",
            publisher="Melville House",
            year="2011",
            notes="Seed reference for the debt/credit critique of simple barter-origin stories.",
        ),
        Source(
            id="src-bitcoin-whitepaper",
            title="Bitcoin: A Peer-to-Peer Electronic Cash System",
            source_type="primary",
            publisher="Satoshi Nakamoto",
            year="2008",
            url="https://bitcoin.org/bitcoin.pdf",
            notes="Seed primary source for protocol-trust framing.",
        ),
    ]

    claims = [
        Claim(
            id="claim-money-social-technology",
            text=(
                "Money is a social technology for storing value, moving value "
                "through time, and coordinating trust among strangers."
            ),
            claim_type="definition",
            confidence="high",
            sources=["src-imf-what-is-money"],
            evidence=[
                ClaimEvidence(
                    source_id="src-imf-what-is-money",
                    summary="IMF Back to Basics explains money through store-of-value, unit-of-account, and medium-of-exchange functions.",
                    quote="money can be anything that can serve as a",
                    locator="IMF F&D Back to Basics, opening definition",
                )
            ],
            supporting_evidence=[
                "Institutional explanations commonly define money through store-of-value, medium-of-exchange, and unit-of-account functions.",
            ],
            used_in_scenes=["scene-intro", "scene-source-lens", "scene-synthesis"],
        ),
        Claim(
            id="claim-barter-origin-disputed",
            text=(
                "The simple story that money naturally emerged from barter is "
                "useful as a teaching device but disputed as a universal history."
            ),
            claim_type="controversial",
            confidence="medium",
            sources=["src-imf-what-is-money", "src-graeber-debt"],
            evidence=[
                ClaimEvidence(
                    source_id="src-imf-what-is-money",
                    summary="IMF presents barter as a teaching model for why money helps indirect exchange.",
                    locator="IMF F&D Back to Basics, barter section",
                ),
                ClaimEvidence(
                    source_id="src-graeber-debt",
                    summary="Manual packet lane: Graeber is used for the debt/credit critique of simple barter-origin stories.",
                    verification_status="manual-packet",
                ),
            ],
            supporting_evidence=[
                "Textbook explanations often begin with barter, while anthropological critiques emphasize debt, credit, and obligation.",
            ],
            counterpoints=[
                "Barter can still appear in specific settings, especially where money is scarce or institutions break down.",
            ],
            used_in_scenes=["scene-barter-game", "scene-debt-ledgers", "scene-debate"],
        ),
        Claim(
            id="claim-states-shape-currency",
            text=(
                "States, taxation, military logistics, and legal authority have "
                "often helped standardize and enforce monetary systems."
            ),
            claim_type="historical",
            confidence="medium",
            sources=["src-graeber-debt"],
            evidence=[
                ClaimEvidence(
                    source_id="src-graeber-debt",
                    summary="Manual packet lane: this interpretive claim needs page-level book evidence before public release.",
                    verification_status="manual-packet",
                )
            ],
            supporting_evidence=[
                "The episode treats state power as one major driver, not the only origin story.",
            ],
            counterpoints=[
                "Private credit, commodity money, and local exchange networks can also generate monetary practices.",
            ],
            used_in_scenes=["scene-debt-ledgers", "scene-states-armies", "scene-debate"],
        ),
        Claim(
            id="claim-bank-deposit-creation",
            text=(
                "In modern banking systems, commercial banks create deposits "
                "when they issue loans; lending is not simply relending existing cash."
            ),
            claim_type="economic",
            confidence="high",
            sources=["src-boe-money-creation"],
            evidence=[
                ClaimEvidence(
                    source_id="src-boe-money-creation",
                    summary="Bank of England explains that commercial-bank lending creates deposits in modern money systems.",
                    quote="commercial banks create money, in the form of bank deposits",
                    locator="Bank of England Quarterly Bulletin 2014 Q1",
                )
            ],
            supporting_evidence=[
                "Central bank educational material explicitly describes bank lending as creating deposits.",
            ],
            used_in_scenes=["scene-banking-trust", "scene-bank-run"],
        ),
        Claim(
            id="claim-bank-runs-speed-trust",
            text=(
                "A bank run is a trust and liquidity crisis: withdrawals can "
                "outpace liquid reserves even when a bank owns longer-term assets."
            ),
            claim_type="economic",
            confidence="high",
            sources=["src-boe-money-creation"],
            evidence=[
                ClaimEvidence(
                    source_id="src-boe-money-creation",
                    summary="Bank of England material distinguishes bank deposits, central-bank money, and liquidity constraints.",
                    locator="Bank of England Quarterly Bulletin 2014 Q1",
                )
            ],
            supporting_evidence=[
                "The simulation separates liquid reserves from longer-term assets so the timing problem becomes visible.",
            ],
            used_in_scenes=["scene-bank-run", "scene-synthesis"],
        ),
        Claim(
            id="claim-inflation-system",
            text=(
                "Inflation is better taught as a system involving money supply, "
                "goods supply, spending velocity, shocks, and expectations."
            ),
            claim_type="economic",
            confidence="medium",
            sources=["src-fed-money-supply"],
            evidence=[
                ClaimEvidence(
                    source_id="src-fed-money-supply",
                    summary="Federal Reserve material defines money supply concepts used as one input in the educational inflation model.",
                    locator="Federal Reserve money supply FAQ",
                )
            ],
            supporting_evidence=[
                "The episode uses a simplified slider model to show interacting pressures rather than one-cause explanations.",
            ],
            counterpoints=[
                "Different schools of economics weight monetary, supply-side, and expectation channels differently.",
            ],
            used_in_scenes=["scene-inflation-lab", "scene-debate", "scene-synthesis"],
        ),
        Claim(
            id="claim-crypto-protocol-trust",
            text=(
                "Crypto reframes the money question from institutional trust to "
                "protocol trust, but it does not eliminate trust altogether."
            ),
            claim_type="interpretive",
            confidence="medium",
            sources=["src-bitcoin-whitepaper"],
            evidence=[
                ClaimEvidence(
                    source_id="src-bitcoin-whitepaper",
                    summary="The Bitcoin whitepaper frames the system as peer-to-peer electronic cash, supporting the protocol-trust scene.",
                    quote="peer-to-peer version of electronic cash",
                    locator="Bitcoin whitepaper abstract",
                )
            ],
            supporting_evidence=[
                "The white paper proposes a peer-to-peer payment system, while users still rely on software, governance, exchanges, wallets, and social consensus.",
            ],
            counterpoints=[
                "Crypto advocates and skeptics disagree over whether protocol trust is a stronger or weaker foundation than institutional trust.",
            ],
            used_in_scenes=["scene-crypto-debate", "scene-synthesis"],
        ),
    ]

    disagreements = [
        Disagreement(
            claim_id="claim-barter-origin-disputed",
            disagreement_type="framing",
            model_positions=[
                ModelPosition(
                    model="GeminiScout",
                    position="Use barter as the opening intuition because users recognize the coordination problem.",
                    evidence=["src-imf-what-is-money"],
                ),
                ModelPosition(
                    model="ClaudeCritic",
                    position="Do not imply barter is the established historical origin; show debt and obligation early.",
                    evidence=["src-graeber-debt"],
                ),
                ModelPosition(
                    model="ChatGPTDirector",
                    position="Turn the disagreement into a playable myth-vs-reality sequence.",
                    evidence=["claim-barter-origin-disputed"],
                ),
            ],
            resolution="shown-as-controversy",
            summary="The episode starts with barter as a puzzle, then immediately complicates it.",
        ),
        Disagreement(
            claim_id="claim-inflation-system",
            disagreement_type="emphasis",
            model_positions=[
                ModelPosition(
                    model="GeminiScout",
                    position="Foreground central-bank and money-supply explanations.",
                    evidence=["src-fed-money-supply"],
                ),
                ModelPosition(
                    model="ClaudeCritic",
                    position="Prevent the slider from implying a single universal inflation formula.",
                    evidence=["claim-inflation-system"],
                ),
                ModelPosition(
                    model="ChatGPTDirector",
                    position="Use the lab as a mental model, not a prediction engine.",
                    evidence=["claim-inflation-system"],
                ),
            ],
            resolution="downgraded",
            summary="The scene labels the simulation as educational and keeps uncertainty visible.",
        ),
    ]

    return ResearchDossier(
        topic="Money",
        central_mystery=(
            "Why do paper, metal, and database entries command real labor, "
            "power, and belief?"
        ),
        one_sentence_thesis=(
            "Money works because societies continually convert trust into shared accounting systems."
        ),
        key_questions=[
            "What problem does money solve better than barter?",
            "Why do debt, states, and banks matter as much as coins?",
            "When does monetary trust break?",
            "What changes when money becomes software?",
        ],
        timeline=[
            TimelineEvent(
                id="time-barter-puzzle",
                label="The barter puzzle",
                period="Teaching model",
                description="A simple market shows why direct trade can fail.",
                claim_ids=["claim-barter-origin-disputed"],
            ),
            TimelineEvent(
                id="time-ledgers",
                label="Debt and ledgers",
                period="Ancient to modern",
                description="Accounts, obligations, and credit make exchange possible without immediate barter.",
                claim_ids=["claim-barter-origin-disputed", "claim-states-shape-currency"],
            ),
            TimelineEvent(
                id="time-modern-banking",
                label="Modern bank money",
                period="Modern era",
                description="Banks expand money-like deposits through lending and trust.",
                claim_ids=["claim-bank-deposit-creation", "claim-bank-runs-speed-trust"],
            ),
            TimelineEvent(
                id="time-digital-money",
                label="Protocol money",
                period="2008 onward",
                description="Crypto shifts the trust question toward code, networks, and governance.",
                claim_ids=["claim-crypto-protocol-trust"],
            ),
        ],
        core_concepts=[
            Concept(
                id="concept-unit-account",
                label="Unit of account",
                explanation="A shared measuring stick for prices, debts, and economic memory.",
                claim_ids=["claim-money-social-technology"],
            ),
            Concept(
                id="concept-liquidity",
                label="Liquidity",
                explanation="How quickly an asset can become spendable without a painful discount.",
                claim_ids=["claim-bank-runs-speed-trust"],
            ),
            Concept(
                id="concept-expectations",
                label="Expectations",
                explanation="Beliefs about future prices can change behavior now.",
                claim_ids=["claim-inflation-system"],
            ),
        ],
        misconceptions=[
            "Money is just valuable because the material is valuable.",
            "Banks only lend out cash that savers already deposited.",
            "Inflation has one simple cause in every context.",
            "Crypto removes trust from money.",
        ],
        controversies=[
            "Barter-first origin story versus credit/debt-first accounts.",
            "How much state power versus private exchange explains money's rise.",
            "Whether protocol trust can outperform institutional trust.",
        ],
        claim_ledger=claims,
        source_graph=sources,
        disagreements=disagreements,
        visual_opportunities=[
            "A dark museum-like wall of price tags becoming a ledger.",
            "A market map where failed barter links light up red.",
            "A bank balance sheet that drains as confidence falls.",
            "An inflation control board with linked sliders and visible tradeoffs.",
        ],
        interaction_opportunities=[
            "Barter mini-game",
            "Bank-run reserve runway model",
            "Inflation pressure slider lab",
            "Trust-type debate chamber",
        ],
        recommended_episode_structure=[
            "Cinematic mystery",
            "Barter puzzle",
            "Debt and ledgers",
            "States and armies",
            "Banking and trust",
            "Bank-run simulator",
            "Inflation lab",
            "Crypto debate",
            "Source lens",
            "Final synthesis challenge",
        ],
    )
