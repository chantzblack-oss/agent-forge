"""Persistent cross-session memory — your polymath library.

Each finished deliberation gets distilled into a small ``MemoryEntry`` and
written to disk under ``~/.agent_forge/memory/``. When you start a new chat
session, the orchestrator embeds your first question and retrieves the 2-3
most relevant prior sessions, injecting them as context so the team builds
on your history instead of starting fresh.

Backends (auto-selected, best-first):

1. **ChromaDB** — semantic search via embeddings, best recall. Requires
   ``pip install chromadb``. Embeddings default to the local
   ``all-MiniLM-L6-v2`` model bundled with sentence-transformers.

2. **JSON-line log** (fallback) — no extra deps; does keyword-match
   retrieval over the stored synthesis text. Worse recall but never breaks.

Silent if neither works — memory is optional, not load-bearing.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class MemoryEntry:
    """A compressed record of one deliberation for future retrieval."""
    session_id: str
    timestamp: str                   # ISO-8601
    team_name: str
    user_question: str
    synthesis_tldr: str              # one-sentence answer from Learning Recap
    synthesis_full: str              # Scholar's closing synthesis
    key_concepts: list[dict[str, str]] = field(default_factory=list)
    # [{"term": "...", "definition": "..."}]

    def searchable_document(self) -> str:
        """Compact text representation used for embedding + retrieval."""
        parts = [
            f"Question: {self.user_question}",
            f"TL;DR: {self.synthesis_tldr}",
            f"Team: {self.team_name}",
        ]
        if self.key_concepts:
            concept_lines = [
                f"  {c.get('term', '')}: {c.get('definition', '')}"
                for c in self.key_concepts
            ]
            parts.append("Key concepts:\n" + "\n".join(concept_lines))
        parts.append(f"Synthesis:\n{self.synthesis_full[:2000]}")
        return "\n\n".join(parts)


# ── tiny keyword scorer for the JSON fallback ───────────

_WORD_RE = re.compile(r"[a-zA-Z]{3,}")

def _tokenize(text: str) -> set[str]:
    return {w.lower() for w in _WORD_RE.findall(text)}

_STOPWORDS = {
    "the", "and", "for", "are", "you", "with", "that", "this", "have",
    "from", "not", "but", "was", "they", "what", "which", "were", "been",
    "can", "does", "really", "just", "how", "why", "when", "then", "than",
    "some", "more", "most", "less", "few", "any", "all", "about", "into",
    "them", "their", "would", "should", "could", "has", "had", "his", "her",
    "its", "our", "your", "will", "one", "two", "three", "four",
}

def _overlap_score(query: str, doc: str) -> int:
    q = _tokenize(query) - _STOPWORDS
    d = _tokenize(doc) - _STOPWORDS
    return len(q & d)


# ── SessionMemory ───────────────────────────────────────

class SessionMemory:
    """File-backed memory with optional Chroma vector search.

    Usage:
        mem = SessionMemory()
        mem.remember(entry)
        hits = mem.recall("what did we learn about resilience?", n=3)
    """

    def __init__(self, storage_dir: Path | None = None) -> None:
        if storage_dir is None:
            storage_dir = Path.home() / ".agent_forge" / "memory"
        storage_dir.mkdir(parents=True, exist_ok=True)
        self.storage_dir = storage_dir
        self._chroma = None
        self._json_path = storage_dir / "sessions.jsonl"
        self.backend = "json"
        self._try_init_chroma()

    def _try_init_chroma(self) -> None:
        try:
            import chromadb
            from chromadb.config import Settings
        except ImportError:
            return
        try:
            client = chromadb.PersistentClient(
                path=str(self.storage_dir / "chroma"),
                settings=Settings(anonymized_telemetry=False, allow_reset=False),
            )
            self._chroma = client.get_or_create_collection(
                name="polymath_sessions",
                metadata={"hnsw:space": "cosine"},
            )
            self.backend = "chromadb"
        except Exception:
            self._chroma = None
            self.backend = "json"

    # ── write ──

    def remember(self, entry: MemoryEntry) -> None:
        """Persist a session. Always writes to JSON log; also to Chroma if available."""
        self._append_json(entry)
        if self._chroma is not None:
            try:
                self._chroma.add(
                    documents=[entry.searchable_document()],
                    metadatas=[self._metadata_for(entry)],
                    ids=[entry.session_id],
                )
            except Exception:
                # Chroma failure doesn't poison the session
                pass

    def _append_json(self, entry: MemoryEntry) -> None:
        try:
            with open(self._json_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(entry)) + "\n")
        except Exception:
            pass

    @staticmethod
    def _metadata_for(entry: MemoryEntry) -> dict[str, Any]:
        # Chroma metadata must be scalar types
        return {
            "session_id": entry.session_id,
            "timestamp": entry.timestamp,
            "team_name": entry.team_name,
            "user_question": entry.user_question[:400],
            "synthesis_tldr": entry.synthesis_tldr[:400],
        }

    # ── read ──

    def recall(self, query: str, n_results: int = 3) -> list[dict[str, Any]]:
        """Return the n most relevant prior sessions for this query."""
        if self._chroma is not None:
            try:
                results = self._chroma.query(
                    query_texts=[query], n_results=n_results,
                )
                docs = (results.get("documents") or [[]])[0]
                mds = (results.get("metadatas") or [[]])[0]
                return [{"document": docs[i], "metadata": mds[i]} for i in range(len(docs))]
            except Exception:
                pass
        # Fallback: keyword overlap on the JSON log
        return self._json_recall(query, n_results)

    def _json_recall(self, query: str, n: int) -> list[dict[str, Any]]:
        if not self._json_path.exists():
            return []
        rows: list[tuple[int, dict[str, Any]]] = []
        try:
            with open(self._json_path, encoding="utf-8") as f:
                for line in f:
                    try:
                        data = json.loads(line)
                    except Exception:
                        continue
                    score = _overlap_score(query, data.get("synthesis_full", "") + " " + data.get("user_question", ""))
                    if score > 0:
                        rows.append((score, data))
        except Exception:
            return []
        rows.sort(key=lambda x: x[0], reverse=True)
        return [
            {
                "document": r[1].get("synthesis_full", ""),
                "metadata": {
                    "session_id": r[1].get("session_id", ""),
                    "timestamp": r[1].get("timestamp", ""),
                    "team_name": r[1].get("team_name", ""),
                    "user_question": r[1].get("user_question", ""),
                    "synthesis_tldr": r[1].get("synthesis_tldr", ""),
                },
            }
            for r in rows[:n]
        ]

    def all_entries(self) -> list[dict[str, Any]]:
        """Return every stored session (JSON log) — used for /memory list."""
        if not self._json_path.exists():
            return []
        out: list[dict[str, Any]] = []
        try:
            with open(self._json_path, encoding="utf-8") as f:
                for line in f:
                    try:
                        out.append(json.loads(line))
                    except Exception:
                        continue
        except Exception:
            pass
        return out

    # ── helpers ──

    @staticmethod
    def new_session_id() -> str:
        return f"sess_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

    @staticmethod
    def format_for_context(hits: list[dict[str, Any]]) -> str:
        """Turn recall results into a context block to inject into a new session."""
        if not hits:
            return ""
        parts = [
            "══ RELEVANT PRIOR SESSIONS ══",
            "(You can reference these. Do not re-derive conclusions; build on them.)",
        ]
        for i, hit in enumerate(hits, 1):
            md = hit.get("metadata") or {}
            parts.append(
                f"\n[#{i} — {md.get('timestamp', 'unknown date')[:10]}]"
                f"\nQ: {md.get('user_question', '')}"
                f"\nTL;DR: {md.get('synthesis_tldr', '')}"
                f"\n(Fuller synthesis excerpt:)\n{hit.get('document', '')[:900]}"
            )
        return "\n".join(parts)
