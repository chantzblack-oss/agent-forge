"""Explorer — a personal exploration engine. Arrive with nothing, leave with
a rabbit hole; come back and it remembers everything you've explored.

What makes this more than "ask an AI a question":

- **Memory.** Every exploration is logged to ``explorations/journal.json``,
  which is committed to git on purpose — cloud session containers are
  ephemeral, so git IS the persistence layer. Every menu is generated
  against that history: no repeats, deliberate adjacency.
- **Modes.**
    - ``menu(n)``   — n one-line exploration pitches, tuned by the journal.
    - ``dive(t)``   — a self-verifying deep dive on topic ``t`` (see below).
    - ``surprise()``— menu(1) → dive, sight unseen.
    - ``threads()`` — for the last dive, the open follow-up threads it left.
- **Self-verification.** A dive is not one generation. It drafts, then a
  skeptic pass attacks the draft's factual claims and framing, then a final
  pass rewrites with corrections and an honest "where the pop version
  oversells it" section. One strong model that argues with itself beats a
  committee that agrees with itself.

Single-model by design (Claude via the authenticated CLI or API key — zero
extra keys needed in a cloud session). If Gemini is configured, the skeptic
seat automatically switches to a different model family for genuinely
independent pushback — that's the only place cross-model buys anything here.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

from .providers import get_provider, ProviderError

REPO_ROOT = Path(__file__).resolve().parent.parent
EXPLORATIONS_DIR = REPO_ROOT / "explorations"
JOURNAL_PATH = EXPLORATIONS_DIR / "journal.json"

# Family aliases — resolve to the newest release. Overridable because the
# CLI path has heavy per-call latency; EXPLORER_FAST=1 (or forge.py --fast)
# swaps the writer to sonnet for a ~3x faster dive at some depth cost.
WRITER_MODEL = os.environ.get("EXPLORER_WRITER_MODEL") or (
    "sonnet" if os.environ.get("EXPLORER_FAST") else "opus"
)
SKEPTIC_MODEL = os.environ.get("EXPLORER_SKEPTIC_MODEL", "sonnet")


# ── journal (memory) ─────────────────────────────────────

def load_journal() -> list[dict]:
    if not JOURNAL_PATH.exists():
        return []
    try:
        return json.loads(JOURNAL_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []


def _append_journal(entry: dict) -> None:
    entries = load_journal()
    entries.append(entry)
    EXPLORATIONS_DIR.mkdir(exist_ok=True)
    JOURNAL_PATH.write_text(
        json.dumps(entries, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _journal_digest(limit: int = 40) -> str:
    """Compact history for prompt context — newest last."""
    entries = load_journal()[-limit:]
    if not entries:
        return "(nothing explored yet — this is the very first session)"
    lines = []
    for e in entries:
        tags = ", ".join(e.get("tags", []))
        lines.append(f"- {e.get('date', '?')}: {e.get('topic', '?')} [{tags}]")
    return "\n".join(lines)


# ── providers ────────────────────────────────────────────

def _claude():
    return get_provider("anthropic")


def _skeptic_provider():
    """Prefer a different model family for the skeptic seat, if configured."""
    if (
        os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or shutil.which("gemini")
    ):
        try:
            return get_provider("google"), "flash", "Gemini"
        except ProviderError:
            pass
    return _claude(), SKEPTIC_MODEL, "Claude"


# ── menu ─────────────────────────────────────────────────

_MENU_SYSTEM = (
    "You are the curator of a personal exploration engine for one curious "
    "person. You generate rabbit holes: specific, surprising, one-line "
    "exploration pitches in the spirit of Veritasium / Kurzgesagt deep "
    "dives — concrete mysteries and mechanisms, never generic topics "
    "('the ocean' is bad; 'why the deepest fish have no swim bladders and "
    "what the pressure does to their bodies instead' is good).\n\n"
    "TOPIC DIET — pick from these four appetites only; wonky-mechanism "
    "topics (fee plumbing, insurance design, market microstructure) are OUT "
    "unless they carry a genuinely dramatic story:\n"
    "  1. Mind-bending science — physics, space, the brain, time, reality; "
    "'wait, WHAT?' material.\n"
    "  2. Dark/dramatic true stories — heists, disasters, cons, mysteries, "
    "people who did insane things; narrative and stakes.\n"
    "  3. Big human questions — consciousness, death, meaning, why we're "
    "like this; philosophy with teeth.\n"
    "  4. How power really works — the hidden machinery behind money, tech, "
    "history; who really decides things.\n\n"
    "Rules:\n"
    "- OBSCURITY TEST (most important): if a mainstream podcast or a viral "
    "explainer has probably covered it, it's too familiar — reach for the "
    "thing one layer deeper or one field over. Prefer topics where the "
    "interesting part is NOT a debunk of a famous claim but a mechanism, "
    "story, or connection the person has likely never encountered at all.\n"
    "- NEVER repeat or closely paraphrase anything in the already-explored "
    "list you are given.\n"
    "- Make 1-2 options adjacent to the most recent explorations (a thread "
    "worth pulling), and the rest deliberately far from everything in the "
    "history (new territory).\n"
    "- Vary the register: a mystery, a how-it-actually-works, a big idea, a "
    "controversy, a wildcard.\n"
    "- Output ONLY a numbered list, one line per option: a bold 2-5 word "
    "title, an em dash, then a one-sentence hook. No preamble, no outro."
)


def menu(n: int = 6, topic: str | None = None) -> str:
    """Generate n exploration options, personalized against the journal."""
    focus = f"\nConstraint: every option must relate to: {topic}." if topic else ""
    user = (
        f"Already explored (do not repeat):\n{_journal_digest()}\n{focus}\n\n"
        f"Generate exactly {n} options."
    )
    return _claude().complete(
        system=_MENU_SYSTEM, user=user, model=WRITER_MODEL, max_tokens=1400
    ).strip()


# ── dive (draft → skeptic → final) ───────────────────────

_SCOUT_SYSTEM = (
    "You are a research scout for a science/history storyteller. Given a "
    "topic, use web search to hunt for the material that would surprise "
    "even a well-read person: the counterintuitive mechanism, the primary-"
    "source detail everyone omits, the researcher feud, the recent finding "
    "(last 2-3 years) that changed the picture, the killer concrete number, "
    "the vivid scene or character the story can hang on. Explicitly SKIP "
    "what every explainer already says — note it in one line as 'the "
    "familiar version' and spend your effort beyond it.\n\n"
    "Output a terse briefing:\n"
    "FAMILIAR VERSION: one sentence.\n"
    "SURPRISES: 5-8 bullets, each a specific finding with its source and "
    "why it's not commonly known.\n"
    "CHARACTERS & SCENES: 1-3 bullets of vivid, real narrative material.\n"
    "BEST ANGLE: two sentences — the freshest through-line for an essay.\n"
    "No prose beyond this briefing."
)

_DRAFT_SYSTEM = (
    "You write deep-dive explorations for one sharp, curious generalist — "
    "Veritasium/Kurzgesagt register in prose: vivid, concrete, mechanism-"
    "first, zero filler. You are given a scout's briefing of surprising "
    "material; the briefing is your spine — build the essay around the "
    "SURPRISES and BEST ANGLE, not around the familiar version (compress "
    "any necessary background to a few sentences).\n\n"
    "Craft requirements:\n"
    "- Open on a concrete scene, character, or paradox — never a "
    "definition.\n"
    "- Surprise density: something the reader almost certainly didn't know "
    "in every section; if a paragraph teaches nothing new, cut it.\n"
    "- Entertain like a great narrator: momentum, stakes, an occasional "
    "dry aside — but never at the cost of precision.\n"
    "- Generative, not just reportive: end the body with one section "
    "connecting this to something from a different field — an original "
    "'nobody frames it this way' synthesis, clearly flagged as your "
    "framing rather than established fact.\n"
    "- 900-1400 words. State facts plainly; you will be fact-checked by "
    "an adversary, so do not embellish."
)

_SKEPTIC_SYSTEM = (
    "You are a ruthless fact-checker and framing critic. You are given a "
    "draft essay. Your job is to attack it: list its shakiest factual "
    "claims (numbers, dates, attributions, 'studies show'), any pop-"
    "science oversimplifications, and any place the framing oversells "
    "certainty. For each: quote the claim, say why it's suspect, and state "
    "what the more defensible version is (or 'unknown/contested'). Be "
    "specific and merciless. Output a numbered list only."
)

_FINAL_SYSTEM = (
    "You are revising your own draft after an adversarial fact-check. "
    "Produce the final essay in clean markdown:\n"
    "- Fix or hedge every claim the critique flagged; drop what can't be "
    "defended.\n"
    "- Keep the vivid register and surprise density — corrections must not "
    "flatten the prose into hedge-soup; where a claim gets hedged, keep it "
    "interesting by saying precisely WHAT is uncertain and why.\n"
    "- Keep the cross-field synthesis section (clearly flagged as your "
    "framing), tightened by the critique rather than deleted.\n"
    "- End with two short sections: '## Where the pop version oversells "
    "it' (2-4 honest bullets from the critique) and '## Open threads' "
    "(exactly 3 numbered follow-up explorations this opens).\n"
    "- Start with a single H1 title line.\n"
    "Output only the essay markdown."
)


def dive(topic: str, on_progress=None) -> dict:
    """Run a self-verifying deep dive. Returns {title, path, threads, skeptic}."""
    say = on_progress or (lambda _msg: None)
    claude = _claude()

    say("scouting for the non-obvious…")
    briefing = claude.complete(
        system=_SCOUT_SYSTEM,
        user=f"Scout this topic: {topic}",
        model=SKEPTIC_MODEL,   # fast model; the searching does the work
        max_tokens=2000,
    )

    say("drafting…")
    draft = claude.complete(
        system=_DRAFT_SYSTEM,
        user=f"Deep dive topic: {topic}\n\nScout briefing:\n\n{briefing}",
        model=WRITER_MODEL,
        max_tokens=3500,
    )

    skeptic, sk_model, sk_family = _skeptic_provider()
    say(f"skeptic pass ({sk_family})…")
    critique = skeptic.complete(
        system=_SKEPTIC_SYSTEM,
        user=f"Draft to attack:\n\n{draft}",
        model=sk_model,
        max_tokens=1800,
    )

    say("final revision…")
    final = claude.complete(
        system=_FINAL_SYSTEM,
        user=(
            f"Topic: {topic}\n\nYour draft:\n\n{draft}\n\n"
            f"Adversarial critique:\n\n{critique}"
        ),
        model=WRITER_MODEL,
        max_tokens=3500,
    ).strip()

    title = _first_h1(final) or topic
    threads = _extract_threads(final)
    path = _export(topic, title, final, sk_family)

    _append_journal({
        "date": datetime.now().strftime("%Y-%m-%d"),
        "topic": title,
        "tags": _infer_tags(title, topic),
        "file": str(path.relative_to(REPO_ROOT)),
        "threads": threads,
    })
    return {"title": title, "path": path, "threads": threads, "skeptic": sk_family}


def surprise(on_progress=None) -> dict:
    """One option, chosen for you, dived immediately."""
    option = menu(1)
    topic = re.sub(r"^\s*\d+[.)]\s*", "", option.splitlines()[0]).strip()
    topic = topic.replace("**", "")
    return dive(topic, on_progress=on_progress)


def threads() -> list[str]:
    """Open follow-up threads from the most recent dive."""
    entries = load_journal()
    return entries[-1].get("threads", []) if entries else []


# ── queue (batch overnight) ──────────────────────────────

def pick_topics(n: int = 3, topic: str | None = None) -> list[str]:
    """Ask the menu for n topics and parse them into plain dive strings."""
    raw = menu(n=n, topic=topic)
    topics: list[str] = []
    for line in raw.splitlines():
        m = re.match(r"\s*\d+[.)]\s*(.+)", line)
        if m:
            topics.append(m.group(1).replace("**", "").strip())
    return topics[:n]


def queue(
    topics: list[str] | None = None,
    n: int = 3,
    on_progress=None,
    compile_fn=None,
) -> list[dict]:
    """Dive (and optionally compile) a batch of topics back to back.

    ``compile_fn`` is injected by the caller (forge) to avoid an import
    cycle; if given, it's called with the dive's .md path and its return
    value is stored under result['html'].
    """
    say = on_progress or (lambda _m: None)
    if not topics:
        say(f"choosing {n} topics (avoiding your journal)…")
        topics = pick_topics(n)
    results: list[dict] = []
    for i, topic in enumerate(topics, 1):
        label = topic if len(topic) < 70 else topic[:67] + "…"
        say(f"[{i}/{len(topics)}] dive: {label}")
        try:
            result = dive(topic, on_progress=say)
            if compile_fn:
                say(f"[{i}/{len(topics)}] compiling interactive…")
                result["html"] = compile_fn(result["path"])
            results.append(result)
        except Exception as e:  # keep the batch alive if one topic fails
            say(f"[{i}/{len(topics)}] FAILED: {e}")
    return results


# ── helpers ──────────────────────────────────────────────

def _first_h1(md: str) -> str | None:
    for line in md.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return None


def _extract_threads(md: str) -> list[str]:
    """Pull the numbered items from the '## Open threads' section."""
    m = re.search(r"##\s*Open threads(.*)", md, re.IGNORECASE | re.DOTALL)
    if not m:
        return []
    items = re.findall(r"^\s*\d+[.)]\s*(.+)$", m.group(1), re.MULTILINE)
    return [i.strip() for i in items][:3]


def _infer_tags(title: str, topic: str) -> list[str]:
    words = re.findall(r"[a-zA-Z]{5,}", f"{title} {topic}".lower())
    seen: list[str] = []
    for w in words:
        if w not in seen:
            seen.append(w)
    return seen[:5]


def _slugify(text: str, max_len: int = 48) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_len].rstrip("-") or "exploration"


def _export(topic: str, title: str, final_md: str, skeptic_family: str) -> Path:
    EXPLORATIONS_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d")
    path = EXPLORATIONS_DIR / f"{ts}-{_slugify(title)}.md"
    header = (
        f"<!-- exploration: {topic} | "
        f"self-verified (skeptic: {skeptic_family}) | {ts} -->\n\n"
    )
    path.write_text(header + final_md + "\n", encoding="utf-8")
    return path
