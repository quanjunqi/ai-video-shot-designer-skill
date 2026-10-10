import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import visual_workflow
from scripts.shotdesigner.casting import (
    file_sha256, validate_actor_identity_set, validate_casting_brief, validate_role_profile,
)
from scripts.shotdesigner.ledgers.project import apply_review, new_project, register_artifact
from scripts.shotdesigner.ledgers.reviews import create_review
from scripts.shotdesigner.lookdev import validate_look_state_plan
from scripts.shotdesigner.scene_design import validate_scene_functional_brief
from scripts.shotdesigner.v3_gates import (
    continuity_source_for_next_unit, validate_executable_unit_plan,
    validate_planned_unit_plan,
)


HASH = "sha256:" + "a" * 64


def approved(artifact_id, depends_on=None):
    return {"artifact_id": artifact_id, "version": 1, "sha256": HASH,
            "path": artifact_id + ".json", "status": "USER_APPROVED",
            "depends_on": depends_on or [], "dependency_versions": {}, "review_id": "r"}


def look_plan(component, requirement, *, state_id="LOOK1", scene_id="S1", ref="EV1"):
    label = "同日连续状态"
    recommendation = f"建议{requirement}，待用户确认"
    return {"character_id": "C1", "look_states": [{
        "look_state_id": state_id, "label": label,
        "label_basis": {"basis": "continuity_constraint", "source": label},
        "scene_ids": [scene_id], "script_refs": [ref], "continuity_reason": "同日连续",
        "provenance": {
            "script_facts": [], "script_fact_domains": {}, "continuity_constraints": [label],
            "director_recommendations": [recommendation], "unresolved": [],
            "user_decisions": [],
        },
        "components": [{
            "component_type": component, "requirement": requirement,
            "basis": "director_recommendation", "basis_ref": recommendation,
            "rationale": "独立设计候选", "approval_required": True,
            "ownership": "character_asset",
        }],
    }], "transitions": [], "unknowns": []}


def component_requirement(component, requirement, **extra):
    return {
        "component_id": component, "character_id": "C1", "look_state_id": "LOOK1",
        "component_type": component, "script_refs": ["EV1"],
        "requirements": [requirement], "forbidden_changes": ["演员身份", "背景"],
        "basis": "director_recommendation", "basis_ref": f"建议{requirement}，待用户确认",
        "rationale": "独立设计候选", "approval_required": True,
        "ownership": "character_asset", **extra,
    }


class CoDirectV31Checks(unittest.TestCase):
    def test_visual_prompt_package_preserves_reference_order(self):
        package = visual_workflow.prompt_package(
            "scene-view", "S1:reverse", "保持同一空间", [Path("master.png")], 3)
        self.assertIn("1. `master.png`", package)
        self.assertNotIn("生成 3 张候选", package)
        self.assertNotIn("回传", package)
        self.assertIn("保持同一空间", package)

    def test_identity_view_rejects_unapproved_additional_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec = root / "profile.json"
            ledger_path = root / "ledger.json"
            actor = root / "actor.png"
            brief = root / "brief.json"
            style = root / "style.json"
            production = root / "production.json"
            for path in (actor, brief, style, production):
                path.write_bytes(b"approved")
            spec.write_text(json.dumps({
                "character_id": "C1", "view_type": "profile",
                "reference_view_types": ["front"], "requirements": ["标准侧面"]
            }), encoding="utf-8")
            ledger_path.write_text(json.dumps({"artifacts": {
                "actor_baseline:C1": {**approved("actor"), "path": "actor.png",
                                      "sha256": file_sha256(actor)},
                "casting_brief:C1": {**approved("brief"), "path": "brief.json",
                                     "sha256": file_sha256(brief)},
                "visual_style:PROJECT": {**approved("style"), "path": "style.json",
                                         "sha256": file_sha256(style)},
                "production_spec:PROJECT": {**approved("production"),
                                             "path": "production.json",
                                             "sha256": file_sha256(production)},
            }}), encoding="utf-8")
            argv = ["visual_workflow.py", "export-prompt", "actor-identity-view",
                    str(spec), str(ledger_path), str(root / "prompt.md"),
                    "--project-root", str(root)]
            with patch("sys.argv", argv), self.assertRaisesRegex(
                    SystemExit, "actor_identity_view:C1:front"):
                visual_workflow.main()

    def test_ambiguous_statement_cannot_approve_but_can_continue_provisionally(self):
        with self.assertRaisesRegex(ValueError, "explicit, unambiguous"):
            create_review(review_id="r1", artifact_id="units-v1", artifact_type="unit_plan",
                          scope_id="PROJECT", artifact_version=1, artifact_sha256=HASH,
                          decision="approve", user_statement="现在我也不清楚，先进行下一步")
        review = create_review(
            review_id="r2", artifact_id="units-v1", artifact_type="unit_plan",
            scope_id="PROJECT", artifact_version=1, artifact_sha256=HASH,
            decision="continue_provisionally", user_statement="现在我也不清楚，先进行下一步")
        self.assertEqual(review["resulting_status"], "AWAITING_USER")

    def test_provisional_review_never_approves_an_artifact(self):
        ledger = register_artifact(
            new_project("p", "test"), artifact_id="units-v1", artifact_type="unit_plan",
            scope_id="PROJECT", version=1, sha256=HASH, path="units.json")
        review = create_review(
            review_id="r", artifact_id="units-v1", artifact_type="unit_plan",
            scope_id="PROJECT", artifact_version=1, artifact_sha256=HASH,
            decision="continue_provisionally", user_statement="先继续，稍后确认")
        ledger = apply_review(ledger, review)
        self.assertEqual(ledger["artifacts"]["unit_plan:PROJECT"]["status"], "AWAITING_USER")

    def test_role_analysis_and_casting_brief_are_separate(self):
        profile = {
            "character_id": "C1", "script_refs": ["EV1"], "script_facts": ["医生"],
            "dramatic_function": ["处理急诊"], "scene_state_requirements": ["上班", "下班"],
            "performance_requirements": ["完成诊疗动作"],
            "look_state_clues": ["值班服与便服不同"], "unknowns": []}
        brief = {
            "character_id": "C1", "script_refs": ["EV1"], "visible_age": "30-40",
            "identity_requirements": [], "physical_requirements": [], "user_constraints": [],
            "director_recommendations": [{"field": "age", "value": "30-40",
                                           "rationale": "符合职业可信度"}],
            "required_identity_views": ["front", "three_quarter", "full_body"], "unknowns": []}
        self.assertFalse(validate_role_profile(profile, {"EV1"}))
        self.assertFalse(validate_casting_brief(brief, {"EV1"}))
        brief["performance_tasks"] = ["表现焦虑"]
        self.assertTrue(any("non-casting" in error
                            for error in validate_casting_brief(brief, {"EV1"})))

    def test_legacy_identity_policy_is_not_part_of_new_casting_example(self):
        brief = {
            "character_id": "C1", "script_refs": ["EV1"], "visible_age": "25-30",
            "identity_requirements": [], "physical_requirements": [],
            "user_constraints": [], "director_recommendations": [], "unknowns": [],
        }
        self.assertFalse(validate_casting_brief(brief, {"EV1"}))
        self.assertNotIn("required_identity_views", brief)
        self.assertNotIn("identity_view_policy", brief)

    def test_legacy_identity_types_are_compatibility_only(self):
        from scripts.shotdesigner.ledgers.config import review_policy
        policy = review_policy()
        self.assertEqual(
            set(policy["compatibility_only_artifact_types"]),
            {"actor_identity_view", "actor_identity_set"},
        )
        self.assertNotIn("actor_identity_view", policy["required_reviews"])
        self.assertNotIn("actor_identity_set", policy["required_reviews"])

    def test_multiple_scene_mapped_look_states(self):
        def state(state_id, scene_id, ref, component, requirement):
            return look_plan(component, requirement, state_id=state_id,
                             scene_id=scene_id, ref=ref)["look_states"][0]
        plan = {"character_id": "C1", "look_states": [
            state("WORK", "S1", "EV1", "costume", "医生工作服"),
            state("OFF", "S2", "EV2", "costume", "下班便服"),
            state("STAGE", "S3", "EV3", "makeup", "舞台妆")],
            "transitions": [], "unknowns": []}
        self.assertFalse(validate_look_state_plan(
            plan, {"EV1", "EV2", "EV3"}, {"S1", "S2", "S3"}))

    def test_identity_set_binds_approved_views(self):
        ledger = {"artifacts": {"actor_baseline:C1": approved("actor-v1"),
                                "actor_identity_view:C1:front": approved("front-v1")}}
        value = {"character_id": "C1", "views": [
            {"view_type": "baseline", "artifact_id": "actor-v1", "sha256": HASH,
             "derived_from": "actor-v1"},
            {"view_type": "front", "artifact_id": "front-v1", "sha256": HASH,
             "derived_from": "actor-v1"}]}
        self.assertFalse(validate_actor_identity_set(
            value, ledger, {"required_identity_views": ["front"]}))

    def test_identity_set_can_be_approved_once_with_review_board(self):
        ledger = {"artifacts": {"actor_baseline:C1": approved("actor-v1")}}
        value = {
            "character_id": "C1", "approval_mode": "set",
            "identity_board": {
                "asset_id": "board-v1", "sha256": HASH,
                "path": "identity-board.png", "upload_policy": "video_input",
                "asset_type": "actor_identity_sheet",
            },
            "views": [
                {"view_type": "baseline", "asset_id": "actor-v1", "sha256": HASH,
                 "path": "actor.png", "derived_from": "actor-v1",
                 "input_policy": "atomic_video_input", "approval_scope": "identity_set"},
                {"view_type": "front_face", "asset_id": "front-v1", "sha256": HASH,
                 "path": "front.png", "derived_from": "actor-v1",
                 "input_policy": "atomic_video_input", "approval_scope": "identity_set"},
                {"view_type": "full_body", "asset_id": "body-v1", "sha256": HASH,
                 "path": "body.png", "derived_from": "actor-v1",
                 "input_policy": "atomic_video_input", "approval_scope": "identity_set"},
            ],
        }
        brief = {"identity_view_policy": {"mode": "minimal_by_shot_need",
                                            "initial_views": ["front_face", "full_body"],
                                            "conditional_views": {"back_body": "背面镜头"}}}
        self.assertFalse(validate_actor_identity_set(value, ledger, brief))

    def test_identity_board_rejects_unknown_upload_policy(self):
        ledger = {"artifacts": {"actor_baseline:C1": approved("actor-v1")}}
        value = {"character_id": "C1", "approval_mode": "set",
                 "identity_board": {"asset_id": "board-v1", "sha256": HASH,
                                     "path": "board.png", "upload_policy": "atomic_video_input"},
                 "views": [{"view_type": "baseline", "asset_id": "actor-v1", "sha256": HASH,
                            "path": "actor.png", "derived_from": "actor-v1",
                            "input_policy": "atomic_video_input", "approval_scope": "identity_set"}]}
        errors = validate_actor_identity_set(value, ledger,
                                             {"required_identity_views": []})
        self.assertIn("identity_board upload_policy must be video_input or review_only", errors)

    def test_scene_function_precedes_visual_master(self):
        brief = {"scene_id": "S1", "script_refs": ["EV1"],
                 "narrative_functions": ["呈现孤立"], "required_actions": ["电脑操作"],
                 "blocking_needs": ["桌椅支持坐姿表演"], "continuity_anchors": ["门窗与电脑桌"],
                 "practical_constraints": ["双手可见"], "visual_implications": [{
                     "requirement": "保持出租屋功能并提供电脑操作区域",
                     "basis": "director_recommendation",
                     "basis_ref": "建议保留出租屋功能并设置电脑操作区域，待用户确认",
                     "rationale": "把剧本动作转成可审核的场景功能", "approval_required": True,
                 }], "unknowns": [], "provenance": {
                     "script_facts": ["夜内出租屋"],
                     "script_fact_domains": {"夜内出租屋": ["location", "time"]},
                     "continuity_constraints": [], "director_recommendations": [
                         "建议保留出租屋功能并设置电脑操作区域，待用户确认"],
                     "unresolved": [], "user_decisions": [],
                 }}
        self.assertFalse(validate_scene_functional_brief(brief))

    def test_no_image_api_before_component_requirement_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec, plan_path, ledger_path = (root / name for name in
                                            ("component.json", "look-plan.json", "ledger.json"))
            spec.write_text(json.dumps(component_requirement("hair", "黑色短发")), encoding="utf-8")
            plan_path.write_text(json.dumps(look_plan("hair", "黑色短发")), encoding="utf-8")
            ledger_path.write_text(json.dumps({"artifacts": {"look_state_plan:C1": {
                "artifact_id": "plan-v1", "status": "USER_APPROVED", "path": "look-plan.json",
                "sha256": file_sha256(plan_path)}}}), encoding="utf-8")
            argv = ["visual_workflow.py", "generate", "look-component", str(spec),
                    str(ledger_path), str(root / "batch.json"), str(root / "out"),
                    "--project-root", str(root)]
            with patch("sys.argv", argv), patch.object(visual_workflow, "ImageGenerationService") as service:
                with self.assertRaisesRegex(SystemExit, "look_component_requirement"):
                    visual_workflow.main()
                service.return_value.generate.assert_not_called()
                service.return_value.edit.assert_not_called()

    def test_look_component_export_does_not_require_identity_set(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            actor = root / "actor.png"
            brief = root / "brief.json"
            style = root / "style.json"
            production = root / "production.json"
            plan = root / "plan.json"
            requirement = root / "requirement.json"
            ledger = root / "ledger.json"
            output = root / "look.md"
            for path in (actor, brief, style, production):
                path.write_bytes(b"approved")
            plan.write_text(json.dumps(look_plan("hair", "黑色短发")), encoding="utf-8")
            requirement.write_text(json.dumps(component_requirement("hair", "黑色短发")), encoding="utf-8")
            ledger.write_text(json.dumps({"artifacts": {
                "actor_baseline:C1": {**approved("actor"), "path": "actor.png", "sha256": file_sha256(actor)},
                "casting_brief:C1": {**approved("brief"), "path": "brief.json", "sha256": file_sha256(brief)},
                "visual_style:PROJECT": {**approved("style"), "path": "style.json", "sha256": file_sha256(style)},
                "production_spec:PROJECT": {**approved("production"), "path": "production.json", "sha256": file_sha256(production)},
                "look_state_plan:C1": {**approved("plan"), "path": "plan.json", "sha256": file_sha256(plan)},
                "look_component_requirement:C1:LOOK1:hair": {**approved("requirement"), "path": "requirement.json", "sha256": file_sha256(requirement)},
            }}), encoding="utf-8")
            argv = ["visual_workflow.py", "export-prompt", "look-component", str(requirement),
                    str(ledger), str(output), "--project-root", str(root)]
            with patch("sys.argv", argv):
                visual_workflow.main()
            prompt = output.read_text(encoding="utf-8")
            self.assertIn("不读取、不继承任何演员身份", prompt)
            self.assertNotIn("保持参考演员身份", prompt)

    def test_identity_free_costume_worn_view_does_not_require_actor(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec = root / "costume.json"
            plan = root / "plan.json"
            requirement = root / "requirement.json"
            structure = root / "structure.png"
            fabric = root / "fabric.png"
            style = root / "style.json"
            production = root / "production.json"
            ledger = root / "ledger.json"
            output = root / "worn.md"
            for path in (structure, fabric, style, production):
                path.write_bytes(b"approved")
            spec.write_text(json.dumps(component_requirement(
                "costume", "深色外套", asset_type="costume_worn_view",
                reference_image_status="not_provided",
                reference_decision_ref="review-costume-reference-none")), encoding="utf-8")
            plan.write_text(json.dumps(look_plan("costume", "深色外套")), encoding="utf-8")
            requirement.write_text(spec.read_text(encoding="utf-8"), encoding="utf-8")
            ledger.write_text(json.dumps({"artifacts": {
                "visual_style:PROJECT": {**approved("style"), "path": "style.json",
                                          "sha256": file_sha256(style)},
                "production_spec:PROJECT": {**approved("production"), "path": "production.json",
                                              "sha256": file_sha256(production)},
                "look_state_plan:C1": {**approved("plan"), "path": "plan.json",
                                         "sha256": file_sha256(plan)},
                "look_component_requirement:C1:LOOK1:costume": {
                    **approved("requirement"), "path": "requirement.json",
                    "sha256": file_sha256(requirement)},
                "costume_structure:C1:LOOK1:costume": {
                    **approved("structure"), "path": "structure.png",
                    "sha256": file_sha256(structure)},
                "fabric_detail:C1:LOOK1:costume": {
                    **approved("fabric"), "path": "fabric.png",
                    "sha256": file_sha256(fabric)},
            }}), encoding="utf-8")
            argv = ["visual_workflow.py", "export-prompt", "costume-worn-view",
                    str(spec), str(ledger), str(output), "--project-root", str(root)]
            with patch("sys.argv", argv):
                visual_workflow.main()
            prompt = output.read_text(encoding="utf-8")
            self.assertIn("无身份服装人台或中性人体模特", prompt)
            self.assertIn("不得继承任何演员或模特的脸部", prompt)
            self.assertNotIn("演员穿着后的", prompt)

    def test_makeup_component_requires_actor_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec = root / "makeup.json"
            plan = root / "plan.json"
            requirement = root / "requirement.json"
            style = root / "style.json"
            production = root / "production.json"
            ledger = root / "ledger.json"
            output = root / "makeup.md"
            for path in (style, production):
                path.write_bytes(b"approved")
            spec.write_text(json.dumps(component_requirement(
                "makeup", "自然妆", asset_type="makeup_batch")), encoding="utf-8")
            plan.write_text(json.dumps(look_plan("makeup", "自然妆")), encoding="utf-8")
            requirement.write_text(spec.read_text(encoding="utf-8"), encoding="utf-8")
            ledger.write_text(json.dumps({"artifacts": {
                "visual_style:PROJECT": {**approved("style"), "path": "style.json",
                                          "sha256": file_sha256(style)},
                "production_spec:PROJECT": {**approved("production"), "path": "production.json",
                                              "sha256": file_sha256(production)},
                "look_state_plan:C1": {**approved("plan"), "path": "plan.json",
                                         "sha256": file_sha256(plan)},
                "look_component_requirement:C1:LOOK1:makeup": {
                    **approved("requirement"), "path": "requirement.json",
                    "sha256": file_sha256(requirement)},
            }}), encoding="utf-8")
            argv = ["visual_workflow.py", "export-prompt", "makeup-batch",
                    str(spec), str(ledger), str(output), "--project-root", str(root)]
            with patch("sys.argv", argv), self.assertRaisesRegex(
                    SystemExit, "actor_baseline:C1"):
                visual_workflow.main()

    def test_generic_look_component_cannot_bypass_makeup_actor_application(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec = root / "makeup.json"
            plan = root / "plan.json"
            requirement = root / "requirement.json"
            style = root / "style.json"
            production = root / "production.json"
            ledger = root / "ledger.json"
            output = root / "makeup.md"
            for path in (style, production):
                path.write_bytes(b"approved")
            spec.write_text(json.dumps(component_requirement("makeup", "自然妆")), encoding="utf-8")
            plan.write_text(json.dumps(look_plan("makeup", "自然妆")), encoding="utf-8")
            requirement.write_text(spec.read_text(encoding="utf-8"), encoding="utf-8")
            ledger.write_text(json.dumps({"artifacts": {
                "visual_style:PROJECT": {**approved("style"), "path": "style.json",
                                          "sha256": file_sha256(style)},
                "production_spec:PROJECT": {**approved("production"), "path": "production.json",
                                              "sha256": file_sha256(production)},
                "look_state_plan:C1": {**approved("plan"), "path": "plan.json",
                                         "sha256": file_sha256(plan)},
                "look_component_requirement:C1:LOOK1:makeup": {
                    **approved("requirement"), "path": "requirement.json",
                    "sha256": file_sha256(requirement)},
            }}), encoding="utf-8")
            argv = ["visual_workflow.py", "export-prompt", "look-component", str(spec),
                    str(ledger), str(output), "--project-root", str(root)]
            with patch("sys.argv", argv), self.assertRaisesRegex(
                    SystemExit, "makeup-batch"):
                visual_workflow.main()

    def test_character_four_view_requires_canonical_look(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec = root / "four.json"
            ledger = root / "ledger.json"
            output = root / "four.md"
            spec.write_text(json.dumps({
                "character_id": "C1", "look_state_id": "LOOK1",
                "view_order": ["front_full_body", "profile_full_body", "back_full_body", "front_face_closeup"],
                "requirements": ["同一角色同一造型"], "forbidden": ["文字"],
            }), encoding="utf-8")
            ledger.write_text(json.dumps({"artifacts": {
                "look_state_plan:C1": approved("plan"),
            }}), encoding="utf-8")
            argv = ["visual_workflow.py", "export-prompt", "character-four-view", str(spec),
                    str(ledger), str(output), "--project-root", str(root)]
            with patch("sys.argv", argv):
                with self.assertRaisesRegex(SystemExit, "canonical_character_look"):
                    visual_workflow.main()

    def test_character_fusion_requires_approved_component_requirements(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec = root / "fusion.json"
            plan = root / "plan.json"
            ledger = root / "ledger.json"
            output = root / "fusion.md"
            actor = root / "actor.png"
            style = root / "style.json"
            production = root / "production.json"
            component = root / "hair.png"
            for path in (actor, style, production, component):
                path.write_bytes(b"approved")
            plan.write_text(json.dumps(look_plan("hair", "短发")), encoding="utf-8")
            spec.write_text(json.dumps({
                "character_id": "C1", "look_state_id": "LOOK1",
                "component_types": ["hair"],
                "component_assets": {"hair": "look_component:C1:LOOK1:hair"},
            }), encoding="utf-8")

            def entry(artifact_id, path):
                return {**approved(artifact_id), "path": path.name,
                        "sha256": file_sha256(path)}

            ledger.write_text(json.dumps({"artifacts": {
                "actor_baseline:C1": entry("actor", actor),
                "look_state_plan:C1": entry("plan", plan),
                "visual_style:PROJECT": entry("style", style),
                "production_spec:PROJECT": entry("production", production),
                "look_component:C1:LOOK1:hair": entry("hair", component),
            }}), encoding="utf-8")
            argv = ["visual_workflow.py", "export-prompt", "character-fusion", str(spec),
                    str(ledger), str(output), "--project-root", str(root)]
            with patch("sys.argv", argv):
                with self.assertRaisesRegex(SystemExit, "look component requirement"):
                    visual_workflow.main()

            requirement = root / "requirement.json"
            requirement.write_text(json.dumps({"approved": True}), encoding="utf-8")
            saved = json.loads(ledger.read_text(encoding="utf-8"))
            saved["artifacts"]["look_component_requirement:C1:LOOK1:hair"] = entry(
                "hair-requirement", requirement)
            ledger.write_text(json.dumps(saved), encoding="utf-8")
            with patch("sys.argv", argv):
                visual_workflow.main()
            self.assertIn("类型：`character-fusion`", output.read_text(encoding="utf-8"))

    def test_character_fusion_respects_confirmed_absent_component(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan_path = root / "plan.json"
            spec_path = root / "fusion.json"
            ledger_path = root / "ledger.json"
            output = root / "fusion.md"
            actor = root / "actor.png"
            style = root / "style.json"
            production = root / "production.json"
            hair = root / "hair.png"
            hair_requirement = root / "hair-requirement.json"
            accessories_requirement = root / "accessories-requirement.json"
            for path in (actor, style, production, hair):
                path.write_bytes(b"approved")

            plan = look_plan("hair", "短发")
            state = plan["look_states"][0]
            unresolved = "固定配饰均未指定。"
            state["provenance"]["unresolved"].append(unresolved)
            state["components"].append({
                "component_type": "accessories", "requirement": "固定配饰待确认",
                "basis": "unresolved", "basis_ref": unresolved,
                "rationale": "不得自动添加配饰", "approval_required": False,
                "ownership": "character_asset",
            })
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            spec_path.write_text(json.dumps({
                "character_id": "C1", "look_state_id": "LOOK1",
                "component_types": ["hair"],
                "component_assets": {"hair": "look_component:C1:LOOK1:hair"},
            }), encoding="utf-8")
            hair_requirement.write_text(json.dumps({"approved": True}), encoding="utf-8")
            accessories_requirement.write_text(json.dumps({
                "component_id": "C1:LOOK1:accessories",
                "character_id": "C1", "look_state_id": "LOOK1",
                "component_type": "accessories", "script_refs": ["EV1"],
                "requirements": ["无固定配饰"], "forbidden_changes": ["不得添加配饰"],
                "basis": "user_confirmed", "basis_ref": "用户确认无固定配饰",
                "resolves_basis_ref": unresolved, "decision_ref": "review-none",
                "rationale": "用户明确确认不存在该组件", "approval_required": False,
                "ownership": "character_asset",
                "production_disposition": "confirmed_absent", "downstream_assets": [],
            }), encoding="utf-8")

            def entry(artifact_id, path):
                return {**approved(artifact_id), "path": path.name,
                        "sha256": file_sha256(path)}

            ledger_path.write_text(json.dumps({"artifacts": {
                "actor_baseline:C1": entry("actor", actor),
                "look_state_plan:C1": entry("plan", plan_path),
                "visual_style:PROJECT": entry("style", style),
                "production_spec:PROJECT": entry("production", production),
                "look_component_requirement:C1:LOOK1:hair": entry(
                    "hair-requirement", hair_requirement),
                "look_component_requirement:C1:LOOK1:accessories": entry(
                    "accessories-requirement", accessories_requirement),
                "look_component:C1:LOOK1:hair": entry("hair", hair),
            }}), encoding="utf-8")
            argv = ["visual_workflow.py", "export-prompt", "character-fusion",
                    str(spec_path), str(ledger_path), str(output),
                    "--project-root", str(root)]
            with patch("sys.argv", argv):
                visual_workflow.main()

            prompt = output.read_text(encoding="utf-8")
            self.assertIn("已确认以下组件不存在", prompt)
            self.assertIn("accessories", prompt)
            saved = json.loads(ledger_path.read_text(encoding="utf-8"))
            context = saved["derived_cache"]["context:character_fusion:C1:LOOK1"]
            self.assertIn("look_component_requirement:C1:LOOK1:accessories",
                          context["artifact_keys"])

    def test_planned_units_compile_only_after_shot_and_edit_reviews(self):
        planned = {"artifact_id": "planned-v1", "phase": "PLANNED", "units": [{
            "unit_id": "U1", "unit_order": 1, "scene_id": "S1", "script_refs": ["EV1"],
            "entry_state": {}, "exit_state": {}, "handoff": {"to_next": "stable desk state"},
            "boundary_reason": "action settles"}]}
        self.assertFalse(validate_planned_unit_plan(planned, ["EV1"]))
        executable = {"phase": "EXECUTABLE", "derived_from": "planned-v1", "units": [{
            "unit_id": "U1", "script_refs": ["EV1"], "shot_ids": ["SH1"],
            "entry_state": {}, "planned_exit_state": {}, "handoff": {}, "duration_seconds": 8}]}
        ledger = {"artifacts": {"shot_plan:U1": approved("shot"),
                                "editorial_plan:U1": approved("edit")}}
        self.assertFalse(validate_executable_unit_plan(executable, planned, ledger))
        ledger["artifacts"]["editorial_plan:U1"]["status"] = "AWAITING_USER"
        self.assertTrue(validate_executable_unit_plan(executable, planned, ledger))

    def test_accepted_actual_tailframe_precedes_planned_exit(self):
        ledger = {"artifacts": {
            "generated_video:U1": approved("video-v1"),
            "actual_tailframe:U1": approved("tail-v1", ["generated_video:U1"])}}
        self.assertEqual(continuity_source_for_next_unit(
            "U1", ledger, {"pose": "planned"})["source"], "ACTUAL_TAILFRAME")
        ledger["artifacts"]["generated_video:U1"]["status"] = "AWAITING_USER"
        self.assertEqual(continuity_source_for_next_unit(
            "U1", ledger, {"pose": "planned"})["source"], "PLANNED_EXIT_STATE")


if __name__ == "__main__":
    unittest.main()
