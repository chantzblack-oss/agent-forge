from __future__ import annotations

import unittest

from agent_forge.wonderlab import FetchedPage, build_money_episode, verify_sources
from agent_forge.wonderlab.fixtures import money_dossier
from agent_forge.wonderlab.simulations import (
    bank_run_resilience,
    barter_success_rate,
    inflation_pressure,
)


class WonderlabCompilerTests(unittest.TestCase):
    def test_money_episode_links_claims_sources_and_scenes(self) -> None:
        run = build_money_episode()
        episode = run.episode

        claim_ids = {claim.id for claim in episode.claim_ledger}
        source_ids = {source.id for source in episode.source_graph}
        scene_ids = {scene.id for scene in episode.scenes}

        self.assertGreaterEqual(len(episode.scenes), 8)
        self.assertGreaterEqual(len(episode.claim_ledger), 6)
        self.assertGreaterEqual(len(episode.source_graph), 4)

        for scene in episode.scenes:
            self.assertTrue(set(scene.claims_used).issubset(claim_ids), scene.id)
            self.assertTrue(set(scene.source_refs).issubset(source_ids), scene.id)

        for claim in episode.claim_ledger:
            self.assertTrue(set(claim.sources).issubset(source_ids), claim.id)
            self.assertTrue(set(claim.used_in_scenes).issubset(scene_ids), claim.id)

    def test_eval_flags_seed_sources_for_review(self) -> None:
        run = build_money_episode()

        self.assertEqual(run.eval_report.publish_decision, "human-review")
        self.assertIn(
            "Seed sources must be fetched, quoted, and verified before public publication.",
            run.eval_report.required_fixes,
        )
        self.assertEqual(run.eval_report.citation_coverage, 100)
        self.assertEqual(run.eval_report.claim_scene_coverage, 100)

    def test_simulation_kernels_are_deterministic(self) -> None:
        barter = barter_success_rate(0.22, 0.35, 18)
        bank = bank_run_resilience(0.12, 0.08, 0.6)
        inflation = inflation_pressure(0.08, 0.02, 0.03, 0.04)

        self.assertEqual(barter.value, 25.0)
        self.assertEqual(bank.value, 0.9)
        self.assertEqual(inflation.value, 0.11)

    def test_static_renderer_is_wired_to_episode_artifact(self) -> None:
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        index = root / "wonderlab_renderer" / "index.html"
        script = root / "wonderlab_renderer" / "app.js"
        styles = root / "wonderlab_renderer" / "styles.css"
        artifact = root / "wonderlab_money_episode.json"

        self.assertTrue(index.exists())
        self.assertTrue(script.exists())
        self.assertTrue(styles.exists())
        self.assertTrue(artifact.exists())
        self.assertIn("./app.js", index.read_text(encoding="utf-8"))
        self.assertIn("./styles.css", index.read_text(encoding="utf-8"))
        self.assertIn("../wonderlab_money_episode.json", script.read_text(encoding="utf-8"))

    def test_source_verifier_updates_url_sources(self) -> None:
        dossier = money_dossier()

        def fake_fetch(source):
            return FetchedPage(
                url=source.url,
                status_code=200,
                content_type="text/html",
                text=(
                    f"<html><title>{source.title}</title>"
                    f"<body>{source.publisher} publishes {source.title}.</body></html>"
                ),
            )

        verified = verify_sources(
            dossier.source_graph,
            fetcher=fake_fetch,
            checked_at="2026-06-08T12:00:00",
        )
        by_id = {source.id: source for source in verified}

        self.assertEqual(by_id["src-imf-what-is-money"].verification_status, "verified")
        self.assertEqual(by_id["src-boe-money-creation"].verification_status, "verified")
        self.assertEqual(by_id["src-graeber-debt"].verification_status, "needs-human-review")
        self.assertEqual(by_id["src-bitcoin-whitepaper"].verification_status, "verified-pdf")
        self.assertEqual(by_id["src-imf-what-is-money"].checked_at, "2026-06-08T12:00:00")

    def test_source_verifier_routes_403_to_human_review(self) -> None:
        source = money_dossier().source_graph[0]

        def blocked_fetch(_source):
            return FetchedPage(
                url=_source.url,
                status_code=403,
                content_type="text/html",
                text="Forbidden",
            )

        verified = verify_sources(
            [source],
            fetcher=blocked_fetch,
            checked_at="2026-06-08T12:00:00",
        )

        self.assertEqual(verified[0].verification_status, "access-blocked")
        self.assertIn("automated verifier", verified[0].verification_error)

    def test_verified_build_lifts_source_scores_but_keeps_human_review_gate(self) -> None:
        def fake_fetch(source):
            return FetchedPage(
                url=source.url,
                status_code=200,
                content_type="text/html",
                text=f"<title>{source.title}</title>{source.publisher} {source.title}",
            )

        run = build_money_episode(verify_sources=True, source_fetcher=fake_fetch)
        statuses = {source.id: source.verification_status for source in run.episode.source_graph}

        self.assertEqual(statuses["src-imf-what-is-money"], "verified")
        self.assertEqual(statuses["src-bitcoin-whitepaper"], "verified-pdf")
        self.assertEqual(statuses["src-graeber-debt"], "manual-packet")
        self.assertEqual(run.eval_report.publish_decision, "human-review")
        self.assertNotIn(
            "Seed sources must be fetched, quoted, and verified before public publication.",
            run.eval_report.required_fixes,
        )
        self.assertGreaterEqual(run.eval_report.source_quality, 70)


if __name__ == "__main__":
    unittest.main()
