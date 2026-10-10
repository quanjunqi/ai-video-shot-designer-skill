import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.shotdesigner.casting import (
    actor_candidate_prompt, actor_candidate_prompt_package, actor_style_text, finalize_batch,
    select_candidate, validate_candidate_image, validate_character_requirement,
)
from scripts.shotdesigner.image_generation import ImageGenerationService


def requirement():
    return {
        "character_id": "C01", "script_refs": ["EV001", "DLG001"],
        "visible_age": "25-30", "identity_requirements": ["剧本明确为女性"],
        "physical_requirements": [], "user_constraints": [],
        "director_recommendations": [],
        "required_identity_views": ["three-quarter-full-body"], "unknowns": [],
    }


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return self.body


class CastingChecks(unittest.TestCase):
    def test_new_casting_brief_does_not_require_identity_views(self):
        brief = {
            "character_id": "C01", "script_refs": ["EV001"],
            "visible_age": "22-27岁", "identity_requirements": ["男性"],
            "physical_requirements": ["普通至偏清瘦体型"], "user_constraints": [],
            "director_recommendations": [], "unknowns": [],
        }
        self.assertFalse(validate_character_requirement(brief, {"EV001"}))

    def test_requirement_is_objective_and_script_bound(self):
        self.assertFalse(validate_character_requirement(requirement(), {"EV001", "DLG001"}))
        ranked = {**requirement(), "ranking": ["更适合"]}
        self.assertIn("casting brief must not rank or evaluate actors",
                      validate_character_requirement(ranked, {"EV001", "DLG001"}))
        unknown = {**requirement(), "script_refs": ["EV999"]}
        self.assertTrue(any("unknown IDs" in item
                            for item in validate_character_requirement(unknown, {"EV001"})))

    def test_actor_prompt_keeps_candidate_out_of_character_look(self):
        actor_requirement = {
            **requirement(),
            "user_constraints": ["22-25岁亚洲男性"],
        }
        prompt = actor_candidate_prompt(actor_requirement, "写实电影质感")
        for phrase in ("中性基础服装", "无角色妆容", "无角色发型设计", "无剧情道具", "无场景家具"):
            self.assertIn(phrase, prompt)
        self.assertIn("双手完全离开衣袋", prompt)
        self.assertIn("十指完整可见", prompt)
        self.assertIn("22-25岁亚洲男性", prompt)
        for phrase in ("王者1247分", "出租屋", "疲惫面容", "空洞眼神"):
            self.assertNotIn(phrase, prompt)

    def test_actor_style_extracts_only_character_neutral_project_texture(self):
        value = actor_style_text({"style_lock": {
            "medium": "真人实拍", "realism": "生活流写实",
            "grain_and_sharpness": "中等锐度", "color_baseline": "电脑冷蓝光",
        }})
        self.assertIn("真人实拍", value)
        self.assertNotIn("电脑冷蓝光", value)
        self.assertNotIn("表演克制", value)

    def test_actor_prompt_compiles_approved_recommendation_without_pending_marker(self):
        actor_requirement = {
            **requirement(),
            "visible_age": "22-27岁（导演建议，待用户确认）",
            "director_recommendations": [
                {"field": "visible_age", "value": "22-27岁", "rationale": "导演建议"},
                {"field": "appearance_context", "value": "东亚面孔", "rationale": "语境"},
            ],
        }
        prompt = actor_candidate_prompt(actor_requirement, "真人实拍")
        self.assertEqual(prompt.count("可视年龄22-27岁"), 1)
        self.assertIn("东亚面孔", prompt)
        self.assertNotIn("待用户确认", prompt)

    def test_actor_prompt_omits_casting_evidence_and_scene_specific_style(self):
        actor_requirement = {
            **requirement(),
            "identity_requirements": ["男性；剧本持续使用男性代词指代王力。"],
        }
        style = actor_style_text({"style_lock": {
            "medium": "真人实拍",
            "grain_and_sharpness": "中等自然锐度；眼神、手部和屏幕跟踪区域清晰",
        }})
        prompt = actor_candidate_prompt(actor_requirement, style)
        self.assertIn("男性", prompt)
        self.assertNotIn("男性代词", prompt)
        self.assertNotIn("屏幕跟踪", prompt)

    def test_external_prompt_package_does_not_prescribe_candidate_workflow(self):
        package = actor_candidate_prompt_package(requirement(), "写实电影质感", 4)
        self.assertIn("演员基准图 Prompt", package)
        self.assertIn("无角色妆容", package)
        self.assertNotIn("生成 4", package)
        self.assertNotIn("回传", package)
        self.assertNotIn("候选 01", package)

    def test_external_candidate_file_must_be_decodable_raster(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "candidate.png"
            path.write_bytes(b"not-an-image")
            self.assertTrue(any("cannot be decoded" in error
                                for error in validate_candidate_image(path)))

    def test_openai_compatible_adapter_saves_base64_candidates(self):
        adapter = {
            "adapter_id": "test", "base_url_env": "BASE", "token_env": "TOKEN",
            "model_env": "MODEL", "endpoint": "/images/generations", "default_size": "1x1",
        }
        body = ('{"id":"task-1","data":[{"b64_json":"' +
                base64.b64encode(b"png-fixture").decode("ascii") + '"}]}').encode()
        service = ImageGenerationService(adapter, {"BASE": "https://example.test/v1",
                                                    "TOKEN": "secret", "MODEL": "image-model"})
        with tempfile.TemporaryDirectory() as directory, \
                patch("scripts.shotdesigner.image_generation.urlopen", return_value=FakeResponse(body)):
            candidates, metadata = service.generate("candidate", 1, Path(directory))
            self.assertEqual(Path(candidates[0]["path"]).read_bytes(), b"png-fixture")
            self.assertEqual(metadata["model"], "image-model")
            self.assertNotIn("secret", str(metadata))

    def test_adapter_splits_candidate_batch_by_provider_request_limit(self):
        adapter = {
            "adapter_id": "test", "base_url_env": "BASE", "token_env": "TOKEN",
            "model_env": "MODEL", "endpoint": "/images/generations", "default_size": "1x1",
            "max_images_per_request": 1,
        }
        body = ('{"id":"task","data":[{"b64_json":"' +
                base64.b64encode(b"png-fixture").decode("ascii") + '"}]}').encode()
        service = ImageGenerationService(adapter, {"BASE": "https://example.test/v1",
                                                    "TOKEN": "secret", "MODEL": "image-model"})
        with tempfile.TemporaryDirectory() as directory, \
                patch("scripts.shotdesigner.image_generation.urlopen",
                      return_value=FakeResponse(body)) as request:
            candidates, metadata = service.generate("candidate", 3, Path(directory))
            self.assertEqual(request.call_count, 3)
            self.assertEqual([item["candidate_id"] for item in candidates],
                             ["candidate-01", "candidate-02", "candidate-03"])
            self.assertEqual(metadata["request"]["n"], 3)
            self.assertEqual(len(metadata["provider_response_ids"]), 3)

    def test_reference_edit_uses_multipart_without_leaking_token(self):
        adapter = {"adapter_id":"test","base_url_env":"BASE","token_env":"TOKEN",
                   "model_env":"MODEL","endpoint":"/images/generations","edit_endpoint":"/images/edits",
                   "reference_model_env":"REFERENCE_MODEL",
                   "default_size":"1x1"}
        body = ('{"id":"edit-1","data":[{"b64_json":"' +
                base64.b64encode(b"edited").decode("ascii") + '"}]}').encode()
        service = ImageGenerationService(adapter, {"BASE":"https://example.test/v1",
                                                    "TOKEN":"secret","MODEL":"image-model",
                                                    "REFERENCE_MODEL":"reference-model"})
        with tempfile.TemporaryDirectory() as directory, \
                patch("scripts.shotdesigner.image_generation.urlopen", return_value=FakeResponse(body)):
            root = Path(directory); source = root / "source.png"; source.write_bytes(b"source")
            candidates, metadata = service.edit("edit", [source], 1, root / "out")
            self.assertEqual(Path(candidates[0]["path"]).read_bytes(), b"edited")
            self.assertEqual(metadata["reference_count"], 1)
            self.assertEqual(metadata["model"], "reference-model")
            self.assertNotIn("secret", str(metadata))

    def test_user_selection_preserves_candidate_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "candidate.png"
            path.write_bytes(b"candidate")
            batch = finalize_batch("C01", "batch-1", "prompt", [
                {"candidate_id": "candidate-01", "path": str(path), "source": "base64"}
            ], {"adapter_id": "test", "model": "model"})
            selected = select_candidate(batch, "candidate-01")
            self.assertEqual(selected["sha256"], batch["candidates"][0]["sha256"])
            self.assertEqual(selected["artifact_type"], "actor_baseline")

    def test_user_selection_rejects_replaced_candidate_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "candidate.png"
            path.write_bytes(b"candidate")
            batch = finalize_batch("C01", "batch-1", "prompt", [
                {"candidate_id": "candidate-01", "path": "candidate.png", "source": "base64"}
            ], {"adapter_id": "test", "model": "model"}, root,
                depends_on=["casting_brief:C01", "visual_style:PROJECT"])
            path.write_bytes(b"replaced")
            with self.assertRaisesRegex(ValueError, "hash changed"):
                select_candidate(batch, "candidate-01", root)

    def test_user_selection_rejects_superseded_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "candidate.png"
            path.write_bytes(b"candidate")
            batch = finalize_batch("C01", "batch-1", "prompt", [
                {"candidate_id": "candidate-01", "path": str(path), "source": "base64"}
            ], {"adapter_id": "test", "model": "model"})
            batch["batch_status"] = "SUPERSEDED"
            with self.assertRaisesRegex(ValueError, "batch is not awaiting"):
                select_candidate(batch, "candidate-01")


if __name__ == "__main__":
    unittest.main()
