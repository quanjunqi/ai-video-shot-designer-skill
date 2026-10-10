import tempfile
import unittest
from pathlib import Path

from scripts.shotdesigner.ledgers.dependencies import mark_stale
from scripts.shotdesigner.ledgers.project import apply_review, new_project, register_artifact
from scripts.shotdesigner.ledgers.reviews import (
    append_review, create_review, is_explicit_approval_statement, load_reviews,
)
from scripts.shotdesigner.validators.project_ledger import validate_project_ledger


HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64


class ProjectLedgerChecks(unittest.TestCase):
    def test_natural_selected_image_statement_is_explicit(self):
        self.assertTrue(is_explicit_approval_statement("这是我挑选好的"))
        self.assertTrue(is_explicit_approval_statement("就用这张"))
        self.assertFalse(is_explicit_approval_statement("我还没选好"))

    def test_registration_cannot_bypass_user_review(self):
        ledger = new_project("p1", "Test")
        with self.assertRaisesRegex(ValueError, "must start as"):
            register_artifact(
                ledger, artifact_id="style-v1", artifact_type="visual_style",
                scope_id="PROJECT", version=1, sha256=HASH_A, path="style.json",
                status="USER_APPROVED")

    def test_review_binds_exact_immutable_version(self):
        ledger = new_project("p1", "Test", now="2026-09-18T00:00:00+00:00")
        ledger = register_artifact(
            ledger, artifact_id="actor-c1-v1", artifact_type="actor_baseline",
            scope_id="C1", version=1, sha256=HASH_A, path="casting/c1-v1.png")
        review = create_review(
            review_id="r1", artifact_id="actor-c1-v1", artifact_type="actor_baseline",
            scope_id="C1", artifact_version=1, artifact_sha256=HASH_A,
            decision="select_candidate", user_statement="选择第一位演员",
            decided_at="2026-09-18T00:01:00+00:00")
        ledger = apply_review(ledger, review, now="2026-09-18T00:01:00+00:00")
        self.assertEqual(ledger["artifacts"]["actor_baseline:C1"]["status"], "USER_APPROVED")
        self.assertFalse(validate_project_ledger(ledger, [review]))

        wrong = dict(review, artifact_sha256=HASH_B)
        with self.assertRaisesRegex(ValueError, "immutable version"):
            apply_review(ledger, wrong)

    def test_replacing_actor_invalidates_only_same_character(self):
        ledger = new_project("p1", "Test")
        for artifact_id, artifact_type, scope in (
            ("actor-c1-v1", "actor_baseline", "C1"),
            ("look-c1-v1", "canonical_character_look", "C1"),
            ("look-c2-v1", "canonical_character_look", "C2"),
            ("prompt-u1-v1", "target_prompt", "U1"),
        ):
            ledger = register_artifact(
                ledger, artifact_id=artifact_id, artifact_type=artifact_type,
                scope_id=scope, version=1, sha256=HASH_A, path=f"{artifact_id}.json")
        ledger, affected = mark_stale(ledger, "actor_baseline", "C1")
        self.assertEqual(affected, ["canonical_character_look:C1"])
        self.assertEqual(ledger["artifacts"]["canonical_character_look:C1"]["status"], "STALE")
        self.assertEqual(ledger["artifacts"]["canonical_character_look:C2"]["status"], "AWAITING_USER")

    def test_project_scope_change_invalidates_all_downstream_scopes(self):
        ledger = new_project("p1", "Test")
        ledger = register_artifact(
            ledger, artifact_id="style-v1", artifact_type="visual_style",
            scope_id="PROJECT", version=1, sha256=HASH_A, path="style.json")
        ledger = register_artifact(
            ledger, artifact_id="actor-c1-v1", artifact_type="actor_baseline",
            scope_id="C1", version=1, sha256=HASH_A, path="actor.png")
        ledger = register_artifact(
            ledger, artifact_id="scene-s1-v1", artifact_type="scene_master",
            scope_id="S1", version=1, sha256=HASH_A, path="scene.png")
        ledger, affected = mark_stale(ledger, "visual_style", "PROJECT")
        self.assertEqual(affected, ["actor_baseline:C1", "scene_master:S1"])

    def test_review_log_is_append_only_jsonl(self):
        review = create_review(
            review_id="r1", artifact_id="style-v1", artifact_type="visual_style",
            scope_id="PROJECT", artifact_version=1, artifact_sha256=HASH_A,
            decision="approve", user_statement="风格通过")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reviews.jsonl"
            append_review(path, review)
            append_review(path, dict(review, review_id="r2", decision="defer",
                                     resulting_status="AWAITING_USER"))
            self.assertEqual([item["review_id"] for item in load_reviews(path)], ["r1", "r2"])

    def test_defer_keeps_review_pending(self):
        ledger = new_project("p1", "Test")
        ledger = register_artifact(
            ledger, artifact_id="style-v1", artifact_type="visual_style",
            scope_id="PROJECT", version=1, sha256=HASH_A, path="style.json")
        review = create_review(
            review_id="r1", artifact_id="style-v1", artifact_type="visual_style",
            scope_id="PROJECT", artifact_version=1, artifact_sha256=HASH_A,
            decision="defer", user_statement="稍后再决定")
        ledger = apply_review(ledger, review)
        self.assertEqual(ledger["pending_reviews"], ["visual_style:PROJECT"])

    def test_dependency_snapshot_and_automatic_stale_propagation(self):
        ledger = new_project("p1", "Test")
        ledger = register_artifact(ledger, artifact_id="actor-v1", artifact_type="actor_baseline",
                                   scope_id="C1", version=1, sha256=HASH_A, path="actor.png")
        review = create_review(review_id="r1", artifact_id="actor-v1", artifact_type="actor_baseline",
                               scope_id="C1", artifact_version=1, artifact_sha256=HASH_A,
                               decision="approve", user_statement="演员通过")
        ledger = apply_review(ledger, review)
        ledger = register_artifact(
            ledger, artifact_id="look-v1", artifact_type="canonical_character_look",
            scope_id="C1", version=1, sha256=HASH_A, path="look.png",
            depends_on=["actor_baseline:C1"])
        self.assertEqual(ledger["artifacts"]["canonical_character_look:C1"]
                         ["dependency_versions"]["actor_baseline:C1"]["artifact_id"], "actor-v1")
        ledger = register_artifact(ledger, artifact_id="actor-v2", artifact_type="actor_baseline",
                                   scope_id="C1", version=2, sha256=HASH_B, path="actor2.png")
        self.assertEqual(ledger["artifacts"]["canonical_character_look:C1"]["status"], "STALE")

    def test_explicit_dependencies_invalidate_across_scopes_transitively(self):
        ledger = new_project("p1", "Test")
        ledger = register_artifact(
            ledger, artifact_id="look-v1", artifact_type="canonical_character_look",
            scope_id="C1", version=1, sha256=HASH_A, path="look.png")
        review = create_review(
            review_id="look-r1", artifact_id="look-v1", artifact_type="canonical_character_look",
            scope_id="C1", artifact_version=1, artifact_sha256=HASH_A,
            decision="approve", user_statement="定妆通过")
        ledger = apply_review(ledger, review)
        ledger = register_artifact(
            ledger, artifact_id="assets-v1", artifact_type="unit_assets",
            scope_id="U1", version=1, sha256=HASH_A, path="assets.json",
            depends_on=["canonical_character_look:C1"])
        assets_review = create_review(
            review_id="assets-r1", artifact_id="assets-v1", artifact_type="unit_assets",
            scope_id="U1", artifact_version=1, artifact_sha256=HASH_A,
            decision="approve", user_statement="资产通过")
        ledger = apply_review(ledger, assets_review)
        ledger = register_artifact(
            ledger, artifact_id="prompt-v1", artifact_type="target_prompt",
            scope_id="U1", version=1, sha256=HASH_A, path="prompt.txt",
            depends_on=["unit_assets:U1"])

        ledger, affected = mark_stale(ledger, "canonical_character_look", "C1")

        self.assertEqual(affected, ["target_prompt:U1", "unit_assets:U1"])
        self.assertEqual(ledger["artifacts"]["unit_assets:U1"]["status"], "STALE")
        self.assertEqual(ledger["artifacts"]["target_prompt:U1"]["status"], "STALE")

    def test_rejecting_an_approved_upstream_invalidates_dependents(self):
        ledger = new_project("p1", "Test")
        ledger = register_artifact(
            ledger, artifact_id="style-v1", artifact_type="visual_style",
            scope_id="PROJECT", version=1, sha256=HASH_A, path="style.json")
        approval = create_review(
            review_id="style-r1", artifact_id="style-v1", artifact_type="visual_style",
            scope_id="PROJECT", artifact_version=1, artifact_sha256=HASH_A,
            decision="approve", user_statement="风格通过")
        ledger = apply_review(ledger, approval)
        ledger = register_artifact(
            ledger, artifact_id="actor-v1", artifact_type="actor_baseline",
            scope_id="C1", version=1, sha256=HASH_A, path="actor.png",
            depends_on=["visual_style:PROJECT"])
        rejection = create_review(
            review_id="style-r2", artifact_id="style-v1", artifact_type="visual_style",
            scope_id="PROJECT", artifact_version=1, artifact_sha256=HASH_A,
            decision="request_changes", user_statement="需要调整质感")

        ledger = apply_review(ledger, rejection)

        self.assertEqual(ledger["artifacts"]["visual_style:PROJECT"]["status"], "USER_REJECTED")
        self.assertEqual(ledger["artifacts"]["actor_baseline:C1"]["status"], "STALE")


if __name__ == "__main__":
    unittest.main()
