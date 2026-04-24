"""Evidence ledger — every claim made in a session, with grade, source, and verification.

Each session produces a structured log of claims: who asserted what, what
evidence backed it, what grade the asserting agent or Scholar assigned,
whether the Citationist verified the source URL, and whether Skeptic or the
Verifier challenged it. The ledger is:

- Displayed as a panel at session end (optional via ``/ledger`` chat command)
- Exported as CSV/JSON for compound personal-research use
- Stored in ``~/.agent_forge/ledgers/``

Over many sessions, you build a queryable database of what the team has
claimed across topics — your personal evidence library. Useful for:

- "Show me every Grade-A claim the team has ever made about sleep"
- "What conditions did Skeptic raise across my last 20 sessions?"
- "Which citations did I verify vs. which were flagged?"
"""

from __future__ import annotations

import csv
import json
import re
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


# Matches any mention of Grade A/B/C/D as a tier label.
_GRADE_RE = re.compile(r"\bGrade\s*([A-D])\b", re.IGNORECASE)

# Matches markdown citations [Label](url)
_URL_RE = re.compile(r"\[([^\]]+?)\]\((https?://[^)\s]+)\)")


@dataclass
class ClaimRecord:
    """One row in the ledger — a claim made by an agent during a session."""
    session_id: str
    timestamp: str                   # ISO-8601
    team_name: str
    user_question: str
    agent: str                       # who made the claim
    role: str                        # leader / worker / critic / etc.
    claim: str                       # the claim text (truncated)
    grade: str = ""                  # "A" / "B" / "C" / "D" / "" if unstated
    sources: list[str] = field(default_factory=list)   # URLs cited
    verified_urls: list[str] = field(default_factory=list)  # URLs Citationist verified
    hallucinated_urls: list[str] = field(default_factory=list)  # URLs Citationist flagged
    conditions: list[str] = field(default_factory=list)  # conditions attached
    challenged_by: str = ""          # "Skeptic" / "Verifier" / ""


class ClaimLedger:
    """Session-scoped ledger of claims, with persistent global log across sessions."""

    def __init__(self, storage_dir: Path | None = None) -> None:
        if storage_dir is None:
            storage_dir = Path.home() / ".agent_forge" / "ledgers"
        storage_dir.mkdir(parents=True, exist_ok=True)
        self.storage_dir = storage_dir
        self._global_log = storage_dir / "all_claims.jsonl"
        self._lock = threading.Lock()
        self.records: list[ClaimRecord] = []

    # ── extraction ──

    def extract_from_transcript(
        self,
        transcript_entries: list[dict[str, Any]],
        session_id: str,
        team_name: str,
        user_question: str,
        timestamp: str | None = None,
        verified_citations: list | None = None,
    ) -> None:
        """Pull claim records out of a deliberation transcript.

        Uses a heuristic extraction: sentences tagged with '(Grade X: ...)'
        become claim records; grade is parsed. URLs cited in the same
        sentence become the source list. Verified URLs are intersected
        with the Citationist results if provided.
        """
        ts = timestamp or datetime.now().isoformat(timespec="seconds")

        # Build URL → status lookup from Citationist results
        verified_set: set[str] = set()
        hallucinated_set: set[str] = set()
        for vc in (verified_citations or []):
            url = getattr(vc, "url", "")
            status = getattr(vc, "status", "")
            if url and status == "verified":
                verified_set.add(url)
            elif url and status in ("wrong_article", "not_found"):
                hallucinated_set.add(url)

        for entry in transcript_entries:
            content = str(entry.get("content", ""))
            if not content:
                continue
            agent = entry.get("agent", "?")
            role = entry.get("role", "?")

            # Find every sentence/line tagged with a Grade
            for line in content.split("\n"):
                line = line.strip()
                if not line:
                    continue
                grade_match = _GRADE_RE.search(line)
                if not grade_match:
                    continue
                grade = grade_match.group(1).upper()

                urls = [m.group(2) for m in _URL_RE.finditer(line)]
                claim_text = line[:500]

                record = ClaimRecord(
                    session_id=session_id,
                    timestamp=ts,
                    team_name=team_name,
                    user_question=user_question[:500],
                    agent=agent,
                    role=role,
                    claim=claim_text,
                    grade=grade,
                    sources=urls,
                    verified_urls=[u for u in urls if u in verified_set],
                    hallucinated_urls=[u for u in urls if u in hallucinated_set],
                )
                with self._lock:
                    self.records.append(record)

    # ── persistence ──

    def persist(self) -> None:
        """Append this session's records to the global JSONL log."""
        with self._lock:
            if not self.records:
                return
            try:
                with open(self._global_log, "a", encoding="utf-8") as f:
                    for r in self.records:
                        f.write(json.dumps(asdict(r)) + "\n")
            except Exception:
                pass

    def export_session_csv(self, session_id: str) -> Path | None:
        """Write just this session's records as a CSV, return the path."""
        if not self.records:
            return None
        path = self.storage_dir / f"{session_id}.csv"
        try:
            with open(path, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        "agent", "role", "grade", "claim",
                        "sources", "verified_urls", "hallucinated_urls",
                        "user_question", "timestamp",
                    ],
                )
                writer.writeheader()
                for r in self.records:
                    writer.writerow({
                        "agent": r.agent,
                        "role": r.role,
                        "grade": r.grade,
                        "claim": r.claim[:300],
                        "sources": "; ".join(r.sources),
                        "verified_urls": "; ".join(r.verified_urls),
                        "hallucinated_urls": "; ".join(r.hallucinated_urls),
                        "user_question": r.user_question[:200],
                        "timestamp": r.timestamp,
                    })
            return path
        except Exception:
            return None

    # ── querying ──

    def all_global_records(self) -> list[ClaimRecord]:
        """Load every claim ever recorded (across all sessions)."""
        with self._lock:
            if not self._global_log.exists():
                return []
            out: list[ClaimRecord] = []
            try:
                with open(self._global_log, encoding="utf-8") as f:
                    for line in f:
                        try:
                            data = json.loads(line)
                            out.append(ClaimRecord(**data))
                        except Exception:
                            continue
            except Exception:
                pass
            return out

    @staticmethod
    def new_session_id() -> str:
        return f"ledger_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
