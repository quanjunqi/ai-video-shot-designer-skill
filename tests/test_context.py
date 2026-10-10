import json
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from scripts.shotdesigner.context import (
    ContextError, build_context, cache_context, cached_context_entry, content_hash,
    resolve_artifact_keys,
)
from scripts.shotdesigner.context_runtime import prepare_context
from scripts.shotdesigner.ledgers.dependencies import mark_stale
from scripts.shotdesigner.ledgers.project import new_project, register_artifact
from scripts.shotdesigner.validators.project_ledger import validate_project_ledger
import scripts.project_ledger as project_ledger


HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64


def add_approved(ledger, root, artifact_type, scope_id, name, payload, artifact_id=None):
    path = root / name
    if isinstance(payload, dict):
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    else:
        path.write_text(payload, encoding="utf-8")
    from scripts.shotdesigner.casting import file_sha256
    value = register_artifact(
        ledger, artifact_id=artifact_id or f"{artifact_type}-v1",
        artifact_type=artifact_type, scope_id=scope_id, version=1,
        sha256=file_sha256(path), path=name)
    value["artifacts"][f"{artifact_type}:{scope_id}"]["status"] = "USER_APPROVED"
    value["artifacts"][f"{artifact_type}:{scope_id}"]["review_id"] = "fixture-review"
    return value


class ContextChecks(unittest.TestCase):
    def test_context_runtime_resolves_configured_defaults_and_inspect_is_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = new_project("p", "test")
            for artifact_type, name in (("source_script", "script.md"),
                                        ("director_analysis", "analysis.json"),
                                        ("media_implementation_plan", "media.json"),
                                        ("visual_style", "style.json"),
                                        ("production_spec", "spec.json")):
                payload = {"value": "same"} if name.endswith(".json") else "same"
                ledger = add_approved(ledger, root, artifact_type, "PROJECT", name, payload)
            self.assertEqual(resolve_artifact_keys("project", "PROJECT"), [
                "source_script:PROJECT", "director_analysis:PROJECT",
                "media_implementation_plan:PROJECT", "visual_style:PROJECT",
                "production_spec:PROJECT",
            ])
            packet, ledger, built = prepare_context(ledger, "project", "PROJECT", root)
            self.assertFalse(built["cache_hit"])
            self.assertTrue((root / built["path"]).is_file())
            before = json.dumps(ledger, ensure_ascii=False, sort_keys=True)
            _, inspected_ledger, inspected = prepare_context(
                ledger, "project", "PROJECT", root, inspect_only=True)
            self.assertTrue(inspected["cache_hit"])
            self.assertEqual(json.dumps(inspected_ledger, ensure_ascii=False, sort_keys=True), before)
            self.assertEqual(packet["context_hash"], inspected["context_hash"])

    def test_dynamic_context_requires_explicit_artifact_keys(self):
        with self.assertRaisesRegex(ContextError, "requires explicit artifact_keys: video"):
            resolve_artifact_keys("video", "U01")
        self.assertEqual(
            resolve_artifact_keys(
                "video", "U01",
                artifact_keys=["target_prompt:U01", "scene_master:SC01"]),
            ["target_prompt:U01", "scene_master:SC01"],
        )

    def test_cli_build_writes_reference_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger_path = root / "project-ledger.json"
            ledger = new_project("p", "test")
            for artifact_type, name in (("source_script", "script.md"),
                                        ("director_analysis", "analysis.json"),
                                        ("media_implementation_plan", "media.json"),
                                        ("visual_style", "style.json"),
                                        ("production_spec", "spec.json")):
                ledger = add_approved(
                    ledger, root, artifact_type, "PROJECT", name,
                    {"value": "same"} if name.endswith(".json") else "same")
            ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
            original_argv = sys.argv
            try:
                sys.argv = [
                    "project_ledger.py", "--path", str(ledger_path), "context", "build",
                    "project", "PROJECT", "--project-root", str(root),
                    "--reference-output", "derived/project.reference.json",
                ]
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(project_ledger.main(), 0)
            finally:
                sys.argv = original_argv
            reference_path = root / "derived" / "project.reference.json"
            self.assertTrue(reference_path.is_file())
            reference = json.loads(reference_path.read_text(encoding="utf-8"))
            self.assertEqual(reference["context_type"], "project")
            self.assertEqual(reference["scope_id"], "PROJECT")
            self.assertEqual(len(reference["artifact_keys"]), 5)

    def test_same_approved_inputs_have_stable_context_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = new_project("p", "test")
            for artifact_type, scope, name, payload in (
                ("source_script", "PROJECT", "script.md", "剧本"),
                ("director_analysis", "PROJECT", "analysis.json", {"facts": ["事实"]}),
                ("media_implementation_plan", "PROJECT", "media.json", {"mode": "live-action"}),
                ("visual_style", "PROJECT", "style.json", {"texture": "cinematic"}),
                ("production_spec", "PROJECT", "spec.json", {"ratio": "16:9"}),
            ):
                ledger = add_approved(ledger, root, artifact_type, scope, name, payload)
            first = build_context(ledger, "project", "PROJECT", root)
            second = build_context(ledger, "project", "PROJECT", root)
            self.assertEqual(first["context_hash"], second["context_hash"])
            self.assertEqual(first, second)

    def test_unrelated_approved_artifact_does_not_change_packet_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = new_project("p", "test")
            for artifact_type, name in (("source_script", "script.md"),
                                        ("director_analysis", "analysis.json"),
                                        ("media_implementation_plan", "media.json"),
                                        ("visual_style", "style.json"),
                                        ("production_spec", "spec.json")):
                payload = {"value": "same"} if name.endswith(".json") else "same"
                ledger = add_approved(ledger, root, artifact_type, "PROJECT", name, payload)
            before = build_context(ledger, "project", "PROJECT", root)["context_hash"]
            ledger = add_approved(ledger, root, "actor_baseline", "C1", "actor.png", "actor")
            after = build_context(ledger, "project", "PROJECT", root)["context_hash"]
            self.assertEqual(before, after)

    def test_changed_input_invalidates_cache_and_user_review_remains_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = new_project("p", "test")
            for artifact_type, name in (("source_script", "script.md"),
                                        ("director_analysis", "analysis.json"),
                                        ("media_implementation_plan", "media.json"),
                                        ("visual_style", "style.json"),
                                        ("production_spec", "spec.json")):
                payload = {"value": "same"} if name.endswith(".json") else "same"
                ledger = add_approved(ledger, root, artifact_type, "PROJECT", name, payload)
            packet = build_context(ledger, "project", "PROJECT", root)
            ledger = cache_context(ledger, packet, "derived/project-context.json", HASH_A)
            self.assertIsNotNone(cached_context_entry(ledger, packet))
            ledger, affected = mark_stale(ledger, "visual_style", "PROJECT")
            self.assertIn("production_spec:PROJECT", affected)
            self.assertEqual(ledger["derived_cache"], {})

    def test_unapproved_or_missing_input_cannot_enter_context(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = new_project("p", "test")
            ledger = add_approved(ledger, root, "visual_style", "PROJECT", "style.json", "style")
            with self.assertRaisesRegex(ContextError, "required context artifact is missing"):
                build_context(ledger, "project", "PROJECT", root)
            ledger = add_approved(ledger, root, "character_role_profile", "C1", "profile.json", {})
            ledger = add_approved(ledger, root, "casting_brief", "C1", "brief.json", {})
            ledger["artifacts"]["casting_brief:C1"]["status"] = "AWAITING_USER"
            with self.assertRaisesRegex(ContextError, "required context artifact is not approved"):
                build_context(ledger, "casting", "C1", root)

    def test_old_ledger_without_cache_is_compatible(self):
        ledger = new_project("p", "test")
        ledger.pop("derived_cache")
        self.assertEqual(validate_project_ledger(ledger), [])

    def test_cache_index_is_validated_without_copying_context_payload(self):
        ledger = new_project("p", "test")
        ledger["derived_cache"] = {
            "context:project:PROJECT": {
                "kind": "context", "status": "VALID", "context_hash": HASH_A,
                "input_keys": ["source_script:PROJECT"],
                "output_path": "derived/context.json", "output_sha256": HASH_B,
            }
        }
        self.assertEqual(validate_project_ledger(ledger), [])
        self.assertNotIn("payload", ledger["derived_cache"]["context:project:PROJECT"])

    def test_canonical_hash_ignores_mapping_order(self):
        self.assertEqual(content_hash({"b": 2, "a": 1}), content_hash({"a": 1, "b": 2}))

    def test_runtime_reuses_same_packet_but_keeps_cache_separate_from_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = new_project("p", "test")
            ledger = add_approved(ledger, root, "visual_style", "PROJECT", "style.json", "style")
            spec = root / "request.json"
            spec.write_text('{"kind":"hair"}', encoding="utf-8")

            first, ledger, first_ref = prepare_context(
                ledger, "look_component", "C1:LOOK1:hair", root,
                artifact_keys=["visual_style:PROJECT"], request_path=spec)
            second, same_ledger, second_ref = prepare_context(
                ledger, "look_component", "C1:LOOK1:hair", root,
                artifact_keys=["visual_style:PROJECT"], request_path=spec)

            self.assertEqual(first, second)
            self.assertFalse(first_ref["cache_hit"])
            self.assertTrue(second_ref["cache_hit"])
            self.assertEqual(same_ledger, ledger)

    def test_runtime_cache_misses_when_request_or_dependencies_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = new_project("p", "test")
            ledger = add_approved(ledger, root, "visual_style", "PROJECT", "style.json", "style")
            ledger = add_approved(ledger, root, "production_spec", "PROJECT", "production.txt", "production")
            spec = root / "request.json"
            spec.write_text('{"kind":"hair"}', encoding="utf-8")
            _, ledger, first = prepare_context(
                ledger, "look_component", "C1:LOOK1:hair", root,
                artifact_keys=["visual_style:PROJECT"], request_path=spec)
            self.assertFalse(first["cache_hit"])

            spec.write_text('{"kind":"makeup"}', encoding="utf-8")
            _, ledger, changed_request = prepare_context(
                ledger, "look_component", "C1:LOOK1:hair", root,
                artifact_keys=["visual_style:PROJECT"], request_path=spec)
            self.assertFalse(changed_request["cache_hit"])

            _, _, changed_dependencies = prepare_context(
                ledger, "look_component", "C1:LOOK1:hair", root,
                artifact_keys=["production_spec:PROJECT"], request_path=spec)
            self.assertFalse(changed_dependencies["cache_hit"])

    def test_runtime_rejects_unapproved_inputs_and_supports_legacy_json_placeholders(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = add_approved(new_project("p", "test"), root, "visual_style", "PROJECT",
                                  "style.json", "legacy text")
            ledger["artifacts"]["visual_style:PROJECT"]["status"] = "AWAITING_USER"
            with self.assertRaisesRegex(ContextError, "required context artifact is not approved"):
                prepare_context(
                    ledger, "look_component", "C1:LOOK1:hair", root,
                    artifact_keys=["visual_style:PROJECT"])

            ledger["artifacts"]["visual_style:PROJECT"]["status"] = "USER_APPROVED"
            packet, _, _ = prepare_context(
                ledger, "look_component", "C1:LOOK1:hair", root,
                artifact_keys=["visual_style:PROJECT"])
            self.assertEqual(packet["inputs"][0]["payload"], "legacy text")


if __name__ == "__main__":
    unittest.main()
