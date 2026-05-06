"""HotpotQA loader — starter set + on-disk full-dataset loader.

The starter set is 10 hand-selected hard multi-hop questions from the public
HotpotQA dev/distractor split (Yang et al. 2018). The questions are public;
no copyrighted text is included beyond the questions themselves and the
brief expected-answer phrases. For full-scale runs, point load_hotpot_from_
file at your own copy of hotpot_dev_distractor_v1.json.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..tasks import BenchTask, RubricCheck


def _make_hotpot_task(qid: str, question: str, expected_answer: str) -> BenchTask:
    """Convert a HotpotQA item into a multi-agent BenchTask.

    The expected answer appears as a forbidden-phrase guard *inverted*: we
    require the answer phrase to appear in the transcript. Multi-hop nature
    of HotpotQA means citation requirement and uncertainty acknowledgement
    matter heavily — both are required.
    """
    return BenchTask(
        id=f"hotpot_{qid}",
        title=question[:60] + ("..." if len(question) > 60 else ""),
        domain="research",
        difficulty="hard",
        prompt=(
            f"{question}\n\n"
            "Answer this multi-hop question. Cite at least two independent sources, "
            "reconcile any disagreement, and explicitly acknowledge what would change "
            "your conclusion."
        ),
        expected_deliverable="answer with multi-source support and explicit reconciliation",
        checks=(
            RubricCheck(
                id="answer_present",
                description=f"Must include the expected answer phrase: {expected_answer!r}",
                required_phrases=(expected_answer,),
            ),
            RubricCheck(
                id="multi_source",
                description="Must cite multiple sources",
                must_have_citation=True,
            ),
            RubricCheck(
                id="uncertainty",
                description="Must acknowledge uncertainty or what would change the conclusion",
                must_acknowledge_uncertainty=True,
            ),
        ),
        source="adapted_public",
        tags=("hotpot", "multihop", "public"),
    )


# Starter set: 10 hand-selected items. Question + expected_answer only (questions
# are public knowledge; we include no Wikipedia paragraphs from the dataset).
_STARTER: list[tuple[str, str, str]] = [
    (
        "5a8b57f25542995d1e6f1371",
        "Were Scott Derrickson and Ed Wood of the same nationality?",
        "yes",
    ),
    (
        "5a8c7595554299585d9e36b6",
        "What government position was held by the woman who portrayed Corliss Archer "
        "in the film Kiss and Tell?",
        "Chief of Protocol",
    ),
    (
        "5a85ea095542994775f606a8",
        "What science fantasy young adult series, told in first person, has a set of "
        "companion books narrating the stories of enslaved worlds and alien species?",
        "Animorphs",
    ),
    (
        "5adbf0a255429947ff17385a",
        "Are Local H and For Against both from the United States?",
        "yes",
    ),
    (
        "5a89c14f5542993b751ca98a",
        "James Henry Miller was the husband of which English folk singer-songwriter?",
        "Peggy Seeger",
    ),
    (
        "5ab92dba554299131ca422a2",
        "Which magazine was started first, Arthur's Magazine or First for Women?",
        "Arthur's Magazine",
    ),
    (
        "5a754ab5554299439321a8b3",
        "The Oberoi family is part of a hotel company that has a head office in what city?",
        "Delhi",
    ),
    (
        "5a8e3ea95542995a26add48d",
        "Allen Iverson, the most prolific scorer per game in National Basketball "
        "Association history, played for what team coached by Larry Brown that won the "
        "1983 NCAA Championship?",
        "North Carolina State",
    ),
    (
        "5a90620055429916c41bfe87",
        "Are Random House Tower and 888 7th Avenue both used for real estate?",
        "yes",
    ),
    (
        "5ae0185b55429942ec259c1b",
        "Which writer was from England, Henry Roth or Robert Erskine Childers?",
        "Robert Erskine Childers",
    ),
]


def load_hotpot_starter() -> list[BenchTask]:
    return [_make_hotpot_task(qid, q, a) for qid, q, a in _STARTER]


def load_hotpot_from_file(path: str | Path, *, limit: int | None = None) -> list[BenchTask]:
    """Load tasks from a HotpotQA distractor JSON file.

    Expected schema: list of {"_id": str, "question": str, "answer": str, ...}.
    Use the public dev/distractor split:
      hotpot_dev_distractor_v1.json from hotpotqa.github.io.
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    items = data if limit is None else data[:limit]
    return [_make_hotpot_task(it["_id"], it["question"], it["answer"]) for it in items]
