from __future__ import annotations

import json
from datetime import date

from agent_forge.bus import Message, MessageType
from agent_forge.claims import Claim, ClaimGraph, parse_message


WORKER_FOUR_SECTION = """## Key Finding
Renewable cost declines outpace fossil fuels in 14 of 16 OECD markets.

## Evidence
- Lazard LCOE 2024 shows utility solar at $29-92/MWh. (2024-06-15) [Lazard](https://www.lazard.com/research-insights/levelized-cost-of-energy-2024)
- IEA World Energy Outlook reports 90% of new capacity in 2023 was renewable. (October 2024) [IEA](https://www.iea.org/reports/world-energy-outlook-2024)

## Conflict Check
NREL stability study suggests grid risk above 80% renewables; reconciled by phased buildout assumption. (2023-11) [NREL](https://www.nrel.gov/grid/seams.html)

## Recommendations
1. Greenlight Tier-1 storage RFP this quarter.
2. Commission interconnection queue audit.
"""


def _msg(content: str, sender: str = "Analyst", round_num: int = 2) -> Message:
    return Message(sender=sender, content=content, msg_type=MessageType.RESULT, round_num=round_num)


def test_parser_extracts_four_sections_with_typed_claims() -> None:
    claims = parse_message(_msg(WORKER_FOUR_SECTION), role="worker")

    sections = [c.section for c in claims]
    assert "Key Finding" in sections
    assert "Evidence" in sections
    assert "Conflict Check" in sections
    assert "Recommendations" in sections

    evidence = [c for c in claims if c.section == "Evidence"]
    assert len(evidence) == 2
    assert all(c.source_url and c.source_url.startswith("http") for c in evidence)
    assert all(c.source_date is not None for c in evidence)
    assert evidence[0].source_date == date(2024, 6, 15)
    assert evidence[1].source_date == date(2024, 10, 1)


def test_parser_assigns_stable_ids() -> None:
    claims = parse_message(_msg(WORKER_FOUR_SECTION, sender="Analyst", round_num=3), role="worker")
    ids = [c.id for c in claims]
    assert ids == sorted(ids)
    assert all(cid.startswith("r3.Analyst.c") for cid in ids)
    assert len(ids) == len(set(ids))


def test_unsupported_catches_missing_url_and_missing_date() -> None:
    body = """## Evidence
- Source-less claim with no link.
- Dated but no URL on April 2024.
- Linked but undated [report](https://example.com/x).
- Fully cited (2024-01-15) [link](https://example.com/y).
"""
    graph = ClaimGraph()
    graph.extend(parse_message(_msg(body), role="worker"))
    unsupported = graph.unsupported()
    assert len(unsupported) == 3
    fully_cited = [c for c in graph.evidence_claims() if c not in unsupported]
    assert len(fully_cited) == 1
    assert fully_cited[0].source_date == date(2024, 1, 15)


def test_stale_uses_threshold_and_as_of() -> None:
    body = """## Evidence
- Recent finding (2024-09-01) [a](https://example.com/a).
- Older finding (2022-03-15) [b](https://example.com/b).
- Ancient finding (2019-01-01) [c](https://example.com/c).
"""
    graph = ClaimGraph()
    graph.extend(parse_message(_msg(body), role="worker"))

    stale_24mo = graph.stale(24, as_of=date(2024, 12, 1))
    stale_urls = {c.source_url for c in stale_24mo}
    assert "https://example.com/c" in stale_urls
    assert "https://example.com/b" in stale_urls
    assert "https://example.com/a" not in stale_urls

    stale_6mo = graph.stale(6, as_of=date(2024, 12, 1))
    assert {c.source_url for c in stale_6mo} == {
        "https://example.com/b",
        "https://example.com/c",
    }
    # tighten threshold further — even 'a' (3mo old) becomes stale at 2mo
    stale_2mo = graph.stale(2, as_of=date(2024, 12, 1))
    assert "https://example.com/a" in {c.source_url for c in stale_2mo}


def test_citation_density_math() -> None:
    body = """## Evidence
- Claim with citation (2024-01-01) [src](https://example.com/1).
- Claim without citation.
- Another with citation (2024-02-01) [src](https://example.com/2).
- Another without citation.
"""
    graph = ClaimGraph()
    graph.extend(parse_message(_msg(body), role="worker"))
    assert graph.citation_density() == 0.5


def test_leader_claim_extracts_confidence() -> None:
    leader_msg = """## Synthesis
The team converged on phased rollout.

Confidence: med
Top Unknowns That Could Overturn This:
- Storage cost trajectory beyond 2027.
- FERC ruling on transmission queue reform.
[COMPLETE]
"""
    claims = parse_message(_msg(leader_msg, sender="Lead", round_num=4), role="leader")
    assert len(claims) == 1
    assert claims[0].confidence == "med"
    assert claims[0].section is None
    assert claims[0].role == "leader"


def test_to_json_round_trip_stable() -> None:
    graph = ClaimGraph()
    graph.extend(parse_message(_msg(WORKER_FOUR_SECTION), role="worker"))
    payload = graph.to_json()
    parsed = json.loads(payload)
    assert isinstance(parsed, list)
    assert all("id" in c and "section" in c for c in parsed)
    evidence = [c for c in parsed if c["section"] == "Evidence"]
    assert all(c["source_url"] is not None for c in evidence)
    assert all(c["source_date"] is not None for c in evidence)
    # ISO date strings are sortable
    assert evidence[0]["source_date"] == "2024-06-15"
