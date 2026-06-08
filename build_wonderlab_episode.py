#!/usr/bin/env python3
"""Build the first Wonderlab episode artifact from Agent Forge fixtures."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agent_forge.wonderlab import build_money_episode, write_wonderlab_run


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compile a Wonderlab interactive documentary JSON artifact.",
    )
    parser.add_argument(
        "--mode",
        choices=["quick", "deep", "masterpiece"],
        default="deep",
        help="Quality/cost mode to stamp on the episode artifact.",
    )
    parser.add_argument(
        "--output",
        default="wonderlab_money_episode.json",
        help="Where to write the generated JSON artifact.",
    )
    parser.add_argument(
        "--verify-sources",
        action="store_true",
        help="Fetch source URLs and update verification statuses before writing JSON.",
    )
    args = parser.parse_args()

    run = build_money_episode(
        mode=args.mode,
        verify_sources=args.verify_sources,
    )
    out_path = write_wonderlab_run(run, Path(args.output))

    episode = run.episode
    eval_report = run.eval_report
    print(f"Built {episode.title}")
    print(f"Run: {run.run_id}")
    print(f"Output: {out_path}")
    print(
        "Artifact: "
        f"{len(episode.scenes)} scenes, "
        f"{len(episode.claim_ledger)} claims, "
        f"{len(episode.source_graph)} sources, "
        f"{len(episode.disagreements)} disagreements"
    )
    print(
        "Eval: "
        f"decision={eval_report.publish_decision}, "
        f"citation_coverage={eval_report.citation_coverage}, "
        f"claim_scene_coverage={eval_report.claim_scene_coverage}"
    )
    if eval_report.required_fixes:
        print("Required fixes:")
        for fix in eval_report.required_fixes:
            print(f"- {fix}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
