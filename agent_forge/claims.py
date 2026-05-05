"""ClaimGraph — structured representation of agent-emitted claims.

Each agent message in the four-section schema (Key Finding / Evidence /
Conflict Check / Recommendations) is parsed into typed Claim objects and
stored in a graph. Quality gates and the future benchmark harness consume
this graph; raw transcript text is no longer the source of truth for
synthesis or scoring.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Iterable, Literal

from .bus import Message

Section = Literal["Key Finding", "Evidence", "Conflict Check", "Recommendations"]
Confidence = Literal["low", "med", "high"]

_SECTIONS: tuple[Section, ...] = (
    "Key Finding",
    "Evidence",
    "Conflict Check",
    "Recommendations",
)

_SECTION_HEADER_RE = re.compile(
    r"^\s*#{1,6}\s*(?:\d+[\)\.\:]?\s*)?(?P<title>[^\n#]+?)\s*:?\s*$",
    re.MULTILINE,
)
_MD_LINK_RE = re.compile(r"\[(?P<text>[^\]]+)\]\((?P<url>https?://[^\s)]+)\)")
_BARE_URL_RE = re.compile(r"(?<!\()https?://[^\s)\]]+")
_CONFIDENCE_RE = re.compile(
    r"Confidence\s*[:\-]\s*(?P<value>low|med(?:ium)?|high)\b",
    re.IGNORECASE,
)

_MONTHS = {
    m.lower(): i
    for i, m in enumerate(
        ["January", "February", "March", "April", "May", "June",
         "July", "August", "September", "October", "November", "December"],
        start=1,
    )
}
_MONTHS_ABBR = {m.lower()[:3]: i for m, i in _MONTHS.items()}


def _normalize_section(title: str) -> Section | None:
    """Map a header title to one of the canonical four sections, else None."""
    cleaned = re.sub(r"[^a-z ]", " ", title.lower()).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    for canonical in _SECTIONS:
        if cleaned == canonical.lower():
            return canonical
    return None


def _parse_date(text: str) -> date | None:
    """Extract the first parseable publication date from a snippet.

    Supports YYYY-MM-DD, YYYY-MM, YYYY/MM, 'Month YYYY', and 'Mon YYYY'.
    Returns None if no date is found — caller should treat as missing.
    """
    if m := re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", text):
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    if m := re.search(r"\b(\d{4})[-/](\d{1,2})\b", text):
        try:
            return date(int(m.group(1)), int(m.group(2)), 1)
        except ValueError:
            pass
    if m := re.search(r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})\b", text, re.IGNORECASE):
        return date(int(m.group(2)), _MONTHS[m.group(1).lower()], 1)
    if m := re.search(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s+(\d{4})\b", text, re.IGNORECASE):
        return date(int(m.group(2)), _MONTHS_ABBR[m.group(1).lower()[:3]], 1)
    return None


def _parse_confidence(text: str) -> Confidence | None:
    if m := _CONFIDENCE_RE.search(text):
        v = m.group("value").lower()
        if v.startswith("med"):
            return "med"
        return v  # type: ignore[return-value]
    return None


def _months_between(earlier: date, later: date) -> int:
    return (later.year - earlier.year) * 12 + (later.month - earlier.month)


@dataclass
class Claim:
    id: str
    text: str
    agent: str
    role: str
    round: int
    section: Section | None
    source_url: str | None
    source_date: date | None
    confidence: Confidence | None
    raw_excerpt: str

    def to_dict(self) -> dict:
        d = asdict(self)
        d["source_date"] = self.source_date.isoformat() if self.source_date else None
        return d


class ClaimGraph:
    """In-memory store of typed claims emitted across a session."""

    def __init__(self) -> None:
        self._claims: list[Claim] = []

    def add(self, claim: Claim) -> None:
        self._claims.append(claim)

    def extend(self, claims: Iterable[Claim]) -> None:
        self._claims.extend(claims)

    def all(self) -> list[Claim]:
        return list(self._claims)

    def by_agent(self, name: str) -> list[Claim]:
        return [c for c in self._claims if c.agent == name]

    def by_round(self, n: int) -> list[Claim]:
        return [c for c in self._claims if c.round == n]

    def by_section(self, section: Section) -> list[Claim]:
        return [c for c in self._claims if c.section == section]

    def evidence_claims(self) -> list[Claim]:
        return self.by_section("Evidence")

    def conflict_claims(self) -> list[Claim]:
        return self.by_section("Conflict Check")

    def leader_claims(self) -> list[Claim]:
        return [c for c in self._claims if c.role == "leader"]

    def stale(self, threshold_months: int, *, as_of: date | None = None) -> list[Claim]:
        now = as_of or date.today()
        out: list[Claim] = []
        for c in self.evidence_claims():
            if c.source_date is None:
                continue  # missing date is unsupported(), not stale()
            if _months_between(c.source_date, now) > threshold_months:
                out.append(c)
        return out

    def unsupported(self) -> list[Claim]:
        return [
            c for c in self.evidence_claims()
            if c.source_url is None or c.source_date is None
        ]

    def citation_density(self, round: int | None = None) -> float:
        evidence = self.evidence_claims()
        if round is not None:
            evidence = [c for c in evidence if c.round == round]
        if not evidence:
            return 1.0  # vacuous: no Evidence claims means no failures
        supported = sum(
            1 for c in evidence if c.source_url is not None and c.source_date is not None
        )
        return supported / len(evidence)

    def to_json(self) -> str:
        return json.dumps([c.to_dict() for c in self._claims], indent=2)


# ── parser ─────────────────────────────────────────────────────────────


def _split_sections(text: str) -> list[tuple[Section | None, str]]:
    """Walk markdown headers and group body text under canonical sections.

    Lines before the first canonical header land under section=None. Once a
    canonical header is seen, body lines accumulate until the next header.
    Non-canonical headers reset the active section to None.
    """
    sections: list[tuple[Section | None, list[str]]] = [(None, [])]
    for line in text.splitlines():
        m = _SECTION_HEADER_RE.match(line)
        if m and line.lstrip().startswith("#"):
            normalized = _normalize_section(m.group("title"))
            sections.append((normalized, []))
            continue
        sections[-1][1].append(line)
    return [(sec, "\n".join(body).strip()) for sec, body in sections if "\n".join(body).strip()]


def _split_claim_units(body: str) -> list[str]:
    """Break a section body into atomic claim units.

    Treats numbered/bulleted list items as one claim each; otherwise splits
    on blank lines. Falls back to one claim for the whole body.
    """
    body = body.strip()
    if not body:
        return []
    bullets = re.findall(
        r"(?m)^(?:[-*]\s+|\d+[\.\)]\s+).*?(?=^(?:[-*]\s+|\d+[\.\)]\s+)|\Z)",
        body + "\n\n",
        flags=re.DOTALL,
    )
    if bullets:
        return [b.strip() for b in bullets if b.strip()]
    paras = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    return paras or [body]


def parse_message(msg: Message, role: str) -> list[Claim]:
    """Extract Claim objects from a single agent message.

    Workers/debaters: parse the four-section schema. Each unit in each
    section becomes a Claim. Evidence units have URL+date extraction.

    Leaders: extract a single synthesizing claim with confidence parsed
    from the body. Section is None.

    Critics/judges/synthesizers: emit one claim per atomic unit, no section.
    """
    claims: list[Claim] = []
    counter = 0
    agent = msg.sender
    round_num = msg.round_num

    def next_id() -> str:
        nonlocal counter
        counter += 1
        return f"r{round_num}.{agent}.c{counter}"

    if role in ("worker", "debater"):
        for section, body in _split_sections(msg.content):
            if section is None:
                continue
            for unit in _split_claim_units(body):
                url_match = _MD_LINK_RE.search(unit) or _BARE_URL_RE.search(unit)
                if isinstance(url_match, re.Match):
                    url = url_match.group("url") if "url" in (url_match.groupdict() or {}) else url_match.group(0)
                else:
                    url = None
                source_date = _parse_date(unit) if section == "Evidence" else None
                claims.append(Claim(
                    id=next_id(),
                    text=unit,
                    agent=agent,
                    role=role,
                    round=round_num,
                    section=section,
                    source_url=url,
                    source_date=source_date,
                    confidence=None,
                    raw_excerpt=unit,
                ))
        return claims

    if role == "leader":
        confidence = _parse_confidence(msg.content)
        claims.append(Claim(
            id=next_id(),
            text=msg.content.strip(),
            agent=agent,
            role=role,
            round=round_num,
            section=None,
            source_url=None,
            source_date=None,
            confidence=confidence,
            raw_excerpt=msg.content.strip()[:500],
        ))
        return claims

    # critic, judge, synthesizer — flat extraction, no section
    for unit in _split_claim_units(msg.content):
        url_match = _MD_LINK_RE.search(unit) or _BARE_URL_RE.search(unit)
        url = (url_match.group("url") if isinstance(url_match, re.Match) and "url" in (url_match.groupdict() or {}) else (url_match.group(0) if url_match else None))
        claims.append(Claim(
            id=next_id(),
            text=unit,
            agent=agent,
            role=role,
            round=round_num,
            section=None,
            source_url=url,
            source_date=_parse_date(unit),
            confidence=None,
            raw_excerpt=unit,
        ))
    return claims
