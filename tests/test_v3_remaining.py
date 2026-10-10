import unittest

from scripts.shotdesigner.directing_map import render, validate_routes
from scripts.shotdesigner.lookdev import (
    component_is_declared, costume_structure_prompt, fusable_component_types,
    validate_component, validate_costume_structure_design, validate_four_view_spec,
    validate_fusion_sources, validate_look_state_plan,
)
from scripts.shotdesigner.scene_design import validate_scene_functional_brief
from scripts.shotdesigner.scene_design import validate_scene_map_binding, validate_view_set
from scripts.shotdesigner.v3_gates import rejection_target, validate_shot_plan
from scripts.shotdesigner.v3_gates import validate_media_implementation_plan
from scripts.shotdesigner.validators.shot_cards import validate as validate_shot_card
from scripts.shotdesigner.ledgers.project import apply_review, new_project, register_artifact
from scripts.shotdesigner.ledgers.reviews import create_review
from scripts.shotdesigner.ledgers.stages import validate_advance


def artifact(aid, status="USER_APPROVED", sha256="sha256:" + "a" * 64):
    return {"artifact_id": aid, "status": status, "version": 1,
            "sha256": sha256, "path": aid + ".png"}


def provenance(*, script_facts=(), continuity_constraints=(),
               director_recommendations=(), unresolved=(), user_decisions=(),
               script_fact_domains=None):
    facts = list(script_facts)
    return {
        "script_facts": facts,
        "script_fact_domains": script_fact_domains or {
            fact: ["behavior"] for fact in facts
        },
        "continuity_constraints": list(continuity_constraints),
        "director_recommendations": list(director_recommendations),
        "unresolved": list(unresolved),
        "user_decisions": list(user_decisions),
    }


class RemainingV3Checks(unittest.TestCase):
    def test_new_provenance_model_keeps_unspecified_look_open(self):
        plan = {
            "character_id": "C1", "look_states": [{
                "look_state_id": "SAME_NIGHT", "label": "同一晚连续状态",
                "label_basis": {"basis": "continuity_constraint", "source": "同一晚连续状态"},
                "scene_ids": ["S1"], "script_refs": ["EV1"],
                "continuity_reason": "三场连续发生，服装保持连续",
                "provenance": provenance(
                    script_facts=["人物在出租屋内持续活动"],
                    continuity_constraints=["同一晚连续状态", "三场使用同一套已确认造型"],
                    unresolved=["服装类别、发型和鞋子未由剧本指定"]),
                "components": [{
                    "component_type": "costume", "requirement": "服装类别待设计，不预设为居家服",
                    "basis": "unresolved", "basis_ref": "服装类别、发型和鞋子未由剧本指定",
                    "rationale": "剧本未给出服装事实",
                    "approval_required": False, "ownership": "character_asset",
                }],
            }], "transitions": [], "unknowns": [],
        }
        self.assertFalse(validate_look_state_plan(plan, {"EV1"}, {"S1"}))

    def test_new_provenance_model_rejects_unlabeled_concrete_inference(self):
        plan = {
            "character_id": "C1", "look_states": [{
                "look_state_id": "SAME_NIGHT", "label": "出租屋居家服状态",
                "label_basis": {"basis": "continuity_constraint", "source": "同一晚连续状态"},
                "scene_ids": ["S1"], "script_refs": ["EV1"],
                "continuity_reason": "同晚连续",
                "provenance": provenance(
                    script_facts=["出租屋，夜/内"],
                    continuity_constraints=["同一晚连续状态", "服装连续"],
                    unresolved=["服装类别未指定"]),
                "components": [{
                    "component_type": "costume", "requirement": "居家服",
                    "basis": "unresolved", "basis_ref": "服装类别未指定",
                    "rationale": "地点推断", "approval_required": False,
                    "ownership": "character_asset",
                }],
            }], "transitions": [], "unknowns": [],
        }
        errors = validate_look_state_plan(plan, {"EV1"}, {"S1"})
        self.assertTrue(any("label must exactly match" in error for error in errors))
        self.assertTrue(any("must explicitly remain open" in error for error in errors))

    def test_new_look_state_cannot_use_legacy_inference_without_provenance(self):
        plan = {
            "character_id": "C1", "look_states": [{
                "look_state_id": "SAME_NIGHT", "label": "出租屋居家服状态",
                "scene_ids": ["S1"], "script_refs": ["EV1"],
                "continuity_reason": "同晚连续",
                "components": [{"component_type": "costume", "requirement": "居家服",
                                "basis": "director_inference", "rationale": "地点推断"}],
            }], "transitions": [], "unknowns": [],
        }
        errors = validate_look_state_plan(plan, {"EV1"}, {"S1"})
        self.assertTrue(any("provenance is required" in error for error in errors))

    def test_malformed_provenance_returns_errors_instead_of_crashing(self):
        plan = {
            "character_id": "C1", "look_states": [{
                "look_state_id": "S1", "label": "同晚连续状态",
                "label_basis": {"basis": "continuity_constraint", "source": "同晚连续状态"},
                "scene_ids": ["SC1"], "script_refs": ["EV1"], "continuity_reason": "连续",
                "provenance": ["invalid"],
                "components": [{
                    "component_type": "hair", "requirement": "发型待设计",
                    "basis": "unresolved", "basis_ref": "发型未指定",
                    "rationale": "保持开放", "ownership": "character_asset",
                }],
            }], "transitions": [], "unknowns": [],
        }
        errors = validate_look_state_plan(plan, {"EV1"}, {"SC1"})
        self.assertTrue(any("provenance must be an object" in error for error in errors))
        brief = {"scene_id": "SC1", "script_refs": ["EV1"],
                 "narrative_functions": [], "required_actions": [], "blocking_needs": [],
                 "continuity_anchors": [], "practical_constraints": [], "unknowns": [],
                 "provenance": ["invalid"], "visual_implications": [{
                     "requirement": "风格待确认", "basis": "unresolved",
                     "basis_ref": "风格未指定", "rationale": "保持开放",
                 }]}
        errors = validate_scene_functional_brief(brief)
        self.assertTrue(any("provenance must be an object" in error for error in errors))

    def test_prop_is_not_a_character_fusion_component(self):
        component = {"component_id": "phone", "character_id": "C1",
                     "look_state_id": "LOOK01", "component_type": "prop",
                     "script_refs": ["EV1"], "requirements": ["手机"],
                     "forbidden_changes": [], "ownership": "shot_asset",
                     "basis": "script_fact", "basis_ref": "人物查看手机",
                     "rationale": "剧本明确手持物"}
        self.assertTrue(any("scene/shot asset workflow" in error
                            for error in validate_component(component)))
        ledger = {"artifacts": {"actor_baseline:C1": artifact("actor"),
                                 "look_component_requirement:C1:LOOK01:prop": artifact("req"),
                                 "look_component:C1:LOOK01:prop": artifact("prop")}}
        errors, _ = validate_fusion_sources(ledger, "C1", "LOOK01", ["prop"])
        self.assertTrue(any("scene or shot asset" in error for error in errors))

    def test_prop_state_is_declared_but_excluded_from_character_fusion(self):
        recommendation = "建议短发，待用户确认"
        state = {
            "look_state_id": "SAME_NIGHT", "label": "同一晚连续状态",
            "label_basis": {"basis": "continuity_constraint", "source": "同一晚连续状态"},
            "scene_ids": ["S1"], "script_refs": ["EV1"], "continuity_reason": "同场连续",
            "provenance": provenance(
                script_facts=["人物查看手机"],
                script_fact_domains={"人物查看手机": ["prop", "behavior"]},
                continuity_constraints=["同一晚连续状态"],
                director_recommendations=[recommendation]),
            "components": [
                {"component_type": "hair", "requirement": "短发候选",
                 "basis": "director_recommendation", "basis_ref": recommendation,
                 "rationale": "造型建议", "approval_required": True,
                 "ownership": "character_asset"},
                {"component_type": "prop", "requirement": "手机",
                 "basis": "script_fact", "basis_ref": "人物查看手机",
                 "rationale": "剧本动作对象", "ownership": "shot_asset"},
            ],
        }
        plan = {"character_id": "C1", "look_states": [state],
                "transitions": [], "unknowns": []}
        self.assertFalse(validate_look_state_plan(plan, {"EV1"}, {"S1"}))
        self.assertEqual(fusable_component_types(state), ["hair"])

    def test_user_confirmed_basis_requires_a_review_reference(self):
        component = {
            "component_id": "hair", "character_id": "C1", "look_state_id": "LOOK1",
            "component_type": "hair", "script_refs": ["EV1"],
            "requirements": ["用户选择的短发"], "forbidden_changes": [],
            "basis": "user_confirmed", "basis_ref": "用户选择短发",
            "rationale": "使用用户选择", "ownership": "character_asset",
        }
        self.assertTrue(any("decision_ref" in error for error in validate_component(component)))

    def test_scene_provenance_is_validated_when_present(self):
        brief = {"scene_id": "S1", "script_refs": ["EV1"],
                 "narrative_functions": ["呈现孤立"], "required_actions": ["电脑操作"],
                 "blocking_needs": ["桌椅支持坐姿表演"], "continuity_anchors": ["电脑桌"],
                 "practical_constraints": [], "visual_implications": [{
                     "requirement": "使用冷蓝屏幕光作为可见光源",
                     "basis": "director_recommendation",
                     "basis_ref": "建议使用冷蓝屏幕光，待用户确认",
                     "rationale": "使电脑操作在夜内可见", "approval_required": True,
                 }], "unknowns": [], "provenance": provenance(
                     script_facts=["出租屋，夜/内"],
                     continuity_constraints=["电脑桌位置连续"],
                     director_recommendations=["建议使用冷蓝屏幕光，待用户确认"],
                     unresolved=["房间具体装修档次未指定"])}
        self.assertFalse(validate_scene_functional_brief(brief))

    def test_scene_appearance_cannot_bypass_provenance(self):
        brief = {"scene_id": "S1", "script_refs": ["EV1"],
                 "narrative_functions": ["呈现生活空间"], "required_actions": ["电脑操作"],
                 "blocking_needs": [], "continuity_anchors": ["电脑桌"],
                 "practical_constraints": [],
                 "visual_implications": ["破旧、廉价、凌乱的房间"], "unknowns": []}
        errors = validate_scene_functional_brief(brief)
        self.assertTrue(any("provenance is required" in error for error in errors))
        self.assertTrue(any("must contain requirement" in error for error in errors))

    def test_wang_li_fatigue_does_not_authorize_makeup_or_tears(self):
        unresolved = "黑眼圈、肤色变化、眼泪、出汗和衣物凌乱均未指定"
        plan = {
            "character_id": "WANG_LI", "look_states": [{
                "look_state_id": "SAME_NIGHT", "label": "同一晚连续状态",
                "label_basis": {"basis": "continuity_constraint", "source": "同一晚连续状态"},
                "scene_ids": ["1-1"], "script_refs": ["EV_FATIGUE", "EV_TREMBLE"],
                "continuity_reason": "场景连续发生",
                "provenance": provenance(
                    script_facts=["疲惫的脸", "肩膀微微颤抖", "长时间打游戏"],
                    continuity_constraints=["同一晚连续状态"],
                    unresolved=[unresolved, "发型、服装、鞋子和配饰未指定"]),
                "components": [{
                    "component_type": "special_state", "requirement": "眼泪和出汗待确认",
                    "basis": "unresolved", "basis_ref": unresolved,
                    "rationale": "剧本只写肩膀微微颤抖",
                    "approval_required": False, "ownership": "performance_state",
                }],
            }], "transitions": [], "unknowns": [],
        }
        self.assertFalse(validate_look_state_plan(
            plan, {"EV_FATIGUE", "EV_TREMBLE"}, {"1-1"}))
        component = {
            "component_id": "tears", "character_id": "WANG_LI",
            "look_state_id": "SAME_NIGHT", "component_type": "special_state",
            "script_refs": ["EV_TREMBLE"], "requirements": ["眼泪和出汗待确认"],
            "forbidden_changes": [], "basis": "unresolved", "basis_ref": unresolved,
            "rationale": "剧本只写肩膀颤抖", "approval_required": False,
            "ownership": "performance_state",
        }
        self.assertTrue(any("cannot enter a production Prompt" in error
                            for error in validate_component(component, for_production=True)))

    def test_wang_li_player_context_does_not_authorize_gamer_styling(self):
        recommendation = "建议评估耳机、眼镜或电竞元素，待用户确认"
        plan = {
            "character_id": "WANG_LI", "look_states": [{
                "look_state_id": "SAME_NIGHT", "label": "同一晚连续状态",
                "label_basis": {"basis": "continuity_constraint", "source": "同一晚连续状态"},
                "scene_ids": ["1-1"], "script_refs": ["EV_GAME"],
                "continuity_reason": "同场连续",
                "provenance": provenance(
                    script_facts=["王力长时间打游戏"],
                    continuity_constraints=["同一晚连续状态"],
                    director_recommendations=[recommendation]),
                "components": [{
                    "component_type": "accessories", "requirement": "耳机、眼镜或电竞配饰建议",
                    "basis": "director_recommendation", "basis_ref": recommendation,
                    "rationale": "候选设计，不是玩家身份事实", "approval_required": True,
                    "ownership": "character_asset",
                }],
            }], "transitions": [], "unknowns": [],
        }
        self.assertFalse(validate_look_state_plan(plan, {"EV_GAME"}, {"1-1"}))

    def test_costume_production_requires_reference_image_decision(self):
        component = {
            "component_id": "costume", "character_id": "C1",
            "look_state_id": "LOOK1", "component_type": "costume",
            "script_refs": ["EV1"], "requirements": ["灰色圆领T恤和长裤"],
            "forbidden_changes": [], "basis": "user_confirmed",
            "basis_ref": "用户选择方案A", "decision_ref": "review-costume-a",
            "rationale": "用户确认的文字设计", "ownership": "character_asset",
        }
        errors = validate_component(component, for_production=True)
        self.assertTrue(any("reference_image_status" in error for error in errors))
        self.assertTrue(any("reference_decision_ref" in error for error in errors))
        component.update({
            "reference_image_status": "not_provided",
            "reference_decision_ref": "review-costume-a",
        })
        self.assertFalse(validate_component(component, for_production=True))
        component["reference_image_status"] = "provided"
        errors = validate_component(component, for_production=True)
        self.assertTrue(any("requires reference_image" in error for error in errors))

    def test_user_decision_can_resolve_declared_unresolved_component(self):
        unresolved = "服装类别、版型、颜色、面料和层次均未指定。"
        plan = {
            "look_states": [{
                "look_state_id": "LOOK1",
                "components": [{
                    "component_type": "costume", "basis": "unresolved",
                    "basis_ref": unresolved, "ownership": "character_asset",
                }],
            }],
        }
        component = {
            "look_state_id": "LOOK1", "component_type": "costume",
            "basis": "user_confirmed", "basis_ref": "用户选择方案A",
            "resolves_basis_ref": unresolved, "decision_ref": "review-costume-a",
            "ownership": "character_asset",
        }
        self.assertTrue(component_is_declared(component, plan))
        component.pop("decision_ref")
        self.assertFalse(component_is_declared(component, plan))

    def test_costume_structure_requires_confirmed_structured_design(self):
        component = {"component_type": "costume"}
        errors = validate_costume_structure_design(component)
        self.assertTrue(any("structure_design" in error for error in errors))
        component["structure_design"] = {
            "status": "user_confirmed", "decision_ref": "review-structure-a",
            "garment_combination": "圆领短袖T恤搭配长裤",
            "confirmed_design": {
                "fit": "上衣常规略宽松，长裤直筒",
                "color": "中灰色上衣，深灰色长裤",
                "material_category": "棉质针织",
                "layering": "单层穿着",
                "graphics_and_trim": "纯色，无图案、Logo或装饰",
            },
            "upper_structure": {
                "category": "圆领短袖T恤", "neckline": "窄罗纹圆领",
                "shoulder": "自然肩线", "sleeve": "直筒短袖",
                "body_and_hem": "直身衣身，平直下摆",
                "seams_and_pockets": "基础侧缝，无口袋",
            },
            "lower_structure": {
                "category": "直筒长裤", "waistband": "平整腰头",
                "rise_and_leg": "常规裤裆，直筒裤腿", "pockets": "无外露口袋",
                "hem": "平直裤脚", "front_back_structure": "正背面基础裤缝结构",
            },
        }
        self.assertFalse(validate_costume_structure_design(component))
        prompt = costume_structure_prompt(component)
        self.assertIn("这不是角色定妆图，也不是穿搭场景图", prompt)
        self.assertIn("从左到右依次为正面、标准90度侧面、背面", prompt)
        self.assertIn("不出现真人、模特、人体", prompt)
        self.assertIn("画面内不生成标题、尺寸、箭头", prompt)
        self.assertNotIn("拿取手机", prompt)
        self.assertNotIn("演员身份", prompt)

    def test_gameplay_requires_an_explicit_media_representation(self):
        base = {
            "scene_strategies": [{
                "scene_id": "1-2", "script_refs": ["EV_GAME"],
                "source_medium": "gameplay", "rationale": "剧本标注游戏内",
            }],
            "screen_media_strategy": [], "text_rendering_strategy": [],
            "vfx_requirements": [], "sound_requirements": [],
            "production_risks": [], "unknowns": [],
        }
        errors = validate_media_implementation_plan(base)
        self.assertTrue(any("representation_mode" in error for error in errors))
        base["scene_strategies"][0]["representation_mode"] = "direct_gameplay"
        self.assertFalse(validate_media_implementation_plan(base))
        base["scene_strategies"][0]["representation_mode"] = "characterized_performance"
        errors = validate_media_implementation_plan(base)
        self.assertTrue(any("approval_required=true" in error for error in errors))

    def test_wang_li_shoulder_tremble_cannot_become_tears_as_script_fact(self):
        performance_provenance = provenance(
            script_facts=["肩膀微微颤抖"],
            script_fact_domains={"肩膀微微颤抖": ["performance"]})
        shot = {"shot_id": "SH1", "characters": ["WANG_LI"], "shot_card": {
            "design_mode": "drama", "performance_provenance": performance_provenance,
            "performance_beats": [{
                "trigger": "看到失败提示", "visible_response": "眼泪滑落",
                "timing": "结尾一秒", "basis": "script_fact",
                "basis_ref": "肩膀微微颤抖", "rationale": "表现受挫",
            }],
        }}
        findings = validate_shot_card(shot)
        self.assertTrue(any(item.code == "shot-card-performance-script-expansion"
                            for item in findings))
        shot["shot_card"]["performance_beats"][0]["visible_response"] = "肩膀微微颤抖"
        findings = validate_shot_card(shot)
        self.assertFalse(any(item.code == "shot-card-performance-script-expansion"
                             for item in findings))

    def test_context_fact_cannot_directly_define_another_design_domain(self):
        context = "冷蓝屏幕光"
        plan = {
            "character_id": "C1", "look_states": [{
                "look_state_id": "SAME_NIGHT", "label": "同一晚连续状态",
                "label_basis": {"basis": "continuity_constraint", "source": "同一晚连续状态"},
                "scene_ids": ["S1"], "script_refs": ["EV1"], "continuity_reason": "同晚连续",
                "provenance": provenance(
                    script_facts=[context], script_fact_domains={context: ["lighting"]},
                    continuity_constraints=["同一晚连续状态"]),
                "components": [{
                    "component_type": "costume", "requirement": "蓝黑色服装",
                    "basis": "script_fact", "basis_ref": context,
                    "rationale": "从屏幕光反推服装颜色", "ownership": "character_asset",
                }],
            }], "transitions": [], "unknowns": [],
        }
        errors = validate_look_state_plan(plan, {"EV1"}, {"S1"})
        self.assertTrue(any("cannot directly define costume" in error for error in errors))

        body_type = "演员偏清瘦"
        plan["look_states"][0]["provenance"] = provenance(
            script_facts=[body_type], script_fact_domains={body_type: ["identity"]},
            continuity_constraints=["同一晚连续状态"])
        plan["look_states"][0]["components"][0].update({
            "requirement": "宽松版型服装", "basis_ref": body_type,
            "rationale": "从演员体型反推服装版型",
        })
        errors = validate_look_state_plan(plan, {"EV1"}, {"S1"})
        self.assertTrue(any("cannot directly define costume" in error for error in errors))
    def test_look_components_and_fusion_require_approval(self):
        component = {"component_id":"hair-1","character_id":"C1","look_state_id":"LOOK01","component_type":"hair",
                     "script_refs":[],"requirements":["黑色短发"],"forbidden_changes":["face"],
                     "basis":"director_recommendation", "basis_ref":"建议黑色短发",
                     "rationale":"候选设计", "approval_required":True,
                     "ownership":"character_asset"}
        self.assertFalse(validate_component(component))
        ledger = {"artifacts": {"actor_baseline:C1": artifact("actor"),
                                "actor_identity_set:C1": artifact("identity")}}
        errors, _ = validate_fusion_sources(ledger, "C1", "LOOK01", ["hair"])
        self.assertIn("approved look component requirement is required: hair", errors)
        self.assertIn("approved look component is required: hair", errors)
        ledger["artifacts"]["look_component_requirement:C1:LOOK01:hair"] = artifact("hair-requirement")
        ledger["artifacts"]["look_component:C1:LOOK01:hair"] = artifact("hair")
        self.assertFalse(validate_fusion_sources(ledger, "C1", "LOOK01", ["hair"])[0])

    def test_look_components_and_fusion_do_not_require_legacy_identity_set(self):
        ledger = {"artifacts": {
            "actor_baseline:C1": artifact("actor"),
            "look_component_requirement:C1:LOOK01:hair": artifact("hair-requirement"),
            "look_component:C1:LOOK01:hair": artifact("hair"),
        }}
        self.assertFalse(validate_fusion_sources(ledger, "C1", "LOOK01", ["hair"])[0])

    def test_confirmed_absent_component_requires_no_asset(self):
        absent = {
            "component_id": "C1:LOOK01:accessories",
            "character_id": "C1",
            "look_state_id": "LOOK01",
            "component_type": "accessories",
            "script_refs": [],
            "requirements": ["无固定配饰"],
            "forbidden_changes": ["不得添加配饰"],
            "basis": "user_confirmed",
            "basis_ref": "用户确认无固定配饰",
            "resolves_basis_ref": "固定配饰均未指定。",
            "decision_ref": "review-accessories-none",
            "rationale": "用户明确选择无固定配饰",
            "approval_required": False,
            "ownership": "character_asset",
            "production_disposition": "confirmed_absent",
            "downstream_assets": [],
        }
        self.assertFalse(validate_component(absent))
        self.assertTrue(any("does not produce an image asset" in error for error in
                            validate_component(absent, for_production=True)))
        state = {"components": [
            {"component_type": "hair", "ownership": "character_asset"},
            {"component_type": "accessories", "ownership": "character_asset"},
        ]}
        self.assertEqual(fusable_component_types(
            state, {"accessories": absent}), ["hair"])

        with_asset_type = {**absent, "asset_type": "accessory_batch"}
        self.assertIn("confirmed_absent component cannot declare an asset_type",
                      validate_component(with_asset_type))

    def test_specialized_costume_assets_can_feed_fusion(self):
        ledger = {"artifacts": {
            "actor_baseline:C1": artifact("actor"),
            "look_component_requirement:C1:LOOK01:costume": artifact("costume-requirement"),
            "costume_structure:C1:LOOK01:costume": artifact("structure"),
            "fabric_detail:C1:LOOK01:costume": artifact("fabric"),
            "costume_worn_view:C1:LOOK01:costume": artifact("worn"),
        }}
        errors, sources = validate_fusion_sources(
            ledger, "C1", "LOOK01", ["costume"],
            {"costume": [
                "costume_structure:C1:LOOK01:costume",
                "fabric_detail:C1:LOOK01:costume",
                "costume_worn_view:C1:LOOK01:costume",
            ]})
        self.assertFalse(errors)
        self.assertEqual([item["artifact_id"] for item in sources], ["actor", "structure", "fabric", "worn"])

    def test_four_view_contract_is_fixed_and_ordered(self):
        valid = {
            "character_id": "C1", "look_state_id": "LOOK01",
            "view_order": ["front_full_body", "profile_full_body", "back_full_body", "front_face_closeup"],
            "requirements": ["同一角色同一造型"], "forbidden": ["文字", "分割线"],
        }
        self.assertFalse(validate_four_view_spec(valid))
        valid["view_order"] = list(reversed(valid["view_order"]))
        self.assertTrue(validate_four_view_spec(valid))

    def test_scene_views_share_approved_master_and_map_binds_set(self):
        hashes = {key: "sha256:" + value * 64 for key, value in (
            ("master", "a"), ("reverse", "b"), ("left_or_right", "c"))}
        ledger = {"artifacts": {
            "scene_master:S1": artifact("master", sha256=hashes["master"]),
            "scene_view:S1:reverse": artifact("reverse", sha256=hashes["reverse"]),
            "scene_view:S1:left_or_right": artifact(
                "left_or_right", sha256=hashes["left_or_right"]),
        }}
        views = {"view_set_id":"views-S1-v1","scene_id":"S1","views":[
            {"view_type":"master","asset_id":"master","sha256":hashes["master"],"derived_from":"master"},
            {"view_type":"reverse","asset_id":"reverse","sha256":hashes["reverse"],"derived_from":"master"},
            {"view_type":"left_or_right","asset_id":"left_or_right","sha256":hashes["left_or_right"],"derived_from":"master"}]}
        self.assertFalse(validate_view_set(views, ledger))
        scene_map = {"scene_id":"S1","source_view_set_id":"views-S1-v1","space_boundary":{},
                     "fixed_anchors":[],"walkable_zones":[],"objects":[]}
        self.assertFalse(validate_scene_map_binding(scene_map, views))

    def test_directing_map_contains_actor_and_camera_routes(self):
        scene = {"scene_id":"S1","space_boundary":{"polygon":[[-2,-2],[2,-2],[2,2],[-2,2]]},
                 "fixed_anchors":[{"anchor_id":"door","position":[0,2]}],
                 "objects":[{"object_id":"C1","position":[0,0]}],
                 "movement_routes":[{"object_id":"C1","points":[[0,0],[2,2]]}],
                 "camera":{"CAM1":{"movement":"dolly","position":[-1,-1]}},
                 "camera_paths":[{"camera_id":"CAM1","points":[[-1,0],[1,0]]}]}
        self.assertFalse(validate_routes(scene))
        svg = render(scene)
        self.assertIn("C1", svg); self.assertIn("CAM1", svg); self.assertIn("polygon", svg)
        scene["camera_paths"] = []
        self.assertTrue(any(item.startswith("moving cameras require camera_paths")
                            for item in validate_routes(scene)))
        static = {"scene_id":"S2","fixed_anchors":[],"objects":[],"camera":{},
                  "blocking_states":{"only":{"objects":{}}}}
        self.assertFalse(validate_routes(static))

    def test_shots_are_script_bound_and_rejection_routes_exactly(self):
        plan = {"shots":[{"shot_id":"SH1","script_refs":["EV1"],"visible_content":"动作",
                          "framing":"中景","camera":"CAM1","performance":"克制",
                          "start_state":{},"end_state":{},"cut_reason":"信息转折"}]}
        self.assertFalse(validate_shot_plan(plan, {"EV1"}))
        plan["shots"][0]["script_refs"] = ["EV9"]
        self.assertTrue(validate_shot_plan(plan, {"EV1"}))
        self.assertEqual(rejection_target("performance"), "blocking_plan")
        self.assertEqual(rejection_target("generation_variance"), "generated_video")

    def test_stage_advance_requires_all_registered_scopes(self):
        ledger = new_project("p", "title")
        self.assertTrue(validate_advance(ledger, "SCRIPT_LOCKED"))
        ledger = register_artifact(ledger, artifact_id="script-v1", artifact_type="source_script",
                                   scope_id="PROJECT", version=1, sha256="sha256:"+"a"*64,
                                   path="script.md")
        review = create_review(review_id="r", artifact_id="script-v1", artifact_type="source_script",
                               scope_id="PROJECT", artifact_version=1, artifact_sha256="sha256:"+"a"*64,
                               decision="approve", user_statement="剧本锁定")
        ledger = apply_review(ledger, review); self.assertFalse(validate_advance(ledger,"SCRIPT_LOCKED"))
        ledger["current_stage"] = "COVERAGE_READY"; ledger["scope_registry"]["characters"] = ["C1","C2"]
        ledger["artifacts"]["actor_baseline:C1"] = artifact("a1")
        self.assertIn("stage CAST_READY requires approved actor_baseline:C2",
                      validate_advance(ledger,"CAST_READY"))

    def test_cast_ready_does_not_require_internal_role_profile_approval(self):
        ledger = new_project("p", "title")
        ledger["current_stage"] = "COVERAGE_READY"
        ledger["scope_registry"]["characters"] = ["C1"]
        ledger["artifacts"].update({
            "casting_brief:C1": artifact("brief"),
            "actor_baseline:C1": artifact("actor"),
            "actor_identity_set:C1": artifact("identity"),
        })
        self.assertFalse(validate_advance(ledger, "CAST_READY"))


if __name__ == "__main__": unittest.main()
