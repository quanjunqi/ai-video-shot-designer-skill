#!/usr/bin/env python3
"""Ephemeral regression checks for critical workflow gates.

All fixtures live in memory or TemporaryDirectory and are removed on exit.
"""

from __future__ import annotations

from contextlib import redirect_stdout
import io
import tempfile
import json
from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import autodl_minimax_h3 as autodl
import asset_ledger
import check_asset_prompt
import check_director_workflow as workflow
import check_spatial_contract as spatial
import render_blocking_map_text as blocking_map
import validate_seedance_prompt as seedance
import adapter_config
import workflow_config


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def codes(issues):
    return {item["code"] for item in issues}


def messages(issues):
    return "\n".join(item["message"] for item in issues)


def check_seedance_prompt_contract():
    valid = """【全局声音与字幕约束】
不要BGM、不要字幕，只保留音效。

【素材说明】
@图片1：参考人物身份；不参考姿势和背景。

【一句话概述】
Roko在公寓发现照片；采用2镜头连续剪辑，预计8秒。

【全局视觉设定】
全局风格：低饱和写实电影质感。
关键材质与受光表现：湿风衣吸水变深。
灯光基线：冷色窗光从右后方进入。

【详细情节】
0—4秒｜镜头1
画面动作概述：Roko推门进入。
画面构图：人物位于左侧。
机位：门内低机位后移。
动作/表演：先扫视再停步。
对白：无。
声音：门轴与脚步声。
转场：随视线硬切。

4—8秒｜镜头2
画面动作概述：他发现照片。
画面构图：照片位于右前景。
机位：中近景缓慢推进。
动作/表演：手指触碰照片。
对白：无。
声音：纸张轻响。

【全局连续性与结尾约束】
保持人物、空间、道具与轴线连续；结尾停在照片近景。
"""
    require(not seedance.validate_text(valid), "valid Seedance direct prompt failed")
    bad_material = valid.replace("；不参考姿势和背景", "")
    require("material-boundary" in codes(seedance.validate_text(bad_material)),
            "Seedance material passed without reference exclusion boundary")
    bad_single = valid.replace("采用2镜头连续剪辑", "采用单镜头一镜到底")
    require("single-cut-leak" in codes(seedance.validate_text(bad_single)),
            "Seedance long take accepted explicit cuts")


def check_adapter_config():
    adapters = adapter_config.load_adapters()
    require(len(adapters) == 3, "expected three implemented adapter routes")
    contracts = {item["prompt_contract"] for item in adapters}
    require(contracts == {
        "minimax-h3-direct-v1", "autodl-minimax-h3-v1", "seedance-2.5-direct-v1",
    }, f"unexpected adapter contracts: {contracts}")
    seedance_config = adapter_config.by_contract("seedance-2.5-direct-v1")
    require(adapter_config.limit(seedance_config, "unit_duration_seconds", "max") == 30,
            "Seedance duration did not come from adapter config")
    require(seedance_config["limits"]["unit_duration_seconds"]["evidence"] == "user_contract",
            "Seedance user-provided limit lost its evidence classification")
    require(workflow._max_unit_duration({"execution_target": execution_target(
        "model", "seedance-2.5", None, "seedance-2.5-direct-v1")}) == 30,
            "workflow did not resolve Seedance unit duration from adapter config")
    require(workflow._max_unit_duration({}) == 15,
            "unresolved workflow target lost the conservative duration default")


def check_workflow_config():
    require(workflow_config.states() == workflow.WORKFLOW_STATES,
            "workflow validator state order drifted from configuration")
    require(workflow_config.can_transition("USER_REJECTED", "PROMPTS_VALIDATED"),
            "rejected prompt revision transition is missing")
    require(not workflow_config.can_transition("SOURCE_READY", "DELIVERED"),
            "workflow config permits skipping all gates")
    required = set(workflow_config.required_fields_for("ASSETS_READY"))
    require({"scene_maps", "shots", "units", "assets", "execution_target"} <= required,
            "ASSETS_READY cumulative requirements are incomplete")
    require("coverage_plan" in workflow_config.schema_capabilities("2.2"),
            "v2.2 capability matrix lost coverage planning")
    require("coverage_plan" not in workflow_config.schema_capabilities("2.1"),
            "v2.1 incorrectly gained v2.2 coverage requirements")


def check_coverage_module_boundary():
    errors = []
    workflow._validate_v22_direction_and_coverage(
        {}, ["SC01"], {}, [], errors)
    require([item["code"] for item in errors] == [
        "scene-direction-briefs-missing",
        "coverage-plans-missing",
        "scene-direction-brief-coverage-drift",
        "coverage-plan-scene-coverage-drift",
    ], "coverage module changed legacy error codes or ordering")
    require(all(set(item) == {"level", "code", "message"} for item in errors),
            "coverage compatibility wrapper changed the legacy JSON shape")


def check_script_manifest_module_boundary():
    errors, warnings = [], []
    workflow._validate_script_manifest({}, {}, True, errors, warnings)
    require([item["code"] for item in errors] == ["script-manifest-missing"] and not warnings,
            "strict Script Manifest routing changed")
    errors, warnings = [], []
    workflow._validate_script_manifest({}, {}, False, errors, warnings)
    require(not errors and [item["code"] for item in warnings] == [
        "script-manifest-missing-legacy"], "legacy Script Manifest routing changed")
    require(set(warnings[0]) == {"level", "code", "message"},
            "Script Manifest wrapper changed the legacy JSON shape")


def check_visual_review_module_boundary():
    errors, warnings = [], []
    workflow._validate_director_review_artifact({}, None, {}, True, errors, warnings)
    require(not errors and not warnings, "optional Director Review became mandatory")
    workflow._validate_director_review_artifact(
        {"director_review_artifact": []}, None, {}, True, errors, warnings)
    require([item["code"] for item in errors] == ["director-review-artifact-type"],
            "Director Review type validation changed")
    errors, warnings = [], []
    workflow._validate_storyboards([], {}, {}, {}, errors, warnings)
    require(not errors and [item["code"] for item in warnings] == [
        "legacy-storyboard-registry"], "legacy Storyboard warning routing changed")
    require(set(warnings[0]) == {"level", "code", "message"},
            "visual review wrapper changed the legacy JSON shape")


def check_spatial_review_module_boundary():
    errors, warnings = [], []
    workflow._validate_spatial_reviews(
        {"workflow_state": "SPACE_READY"}, {"SC01": {}}, None, True, errors, warnings)
    require([item["code"] for item in errors] == ["spatial-reviews-missing"] and not warnings,
            "required Spatial Review routing changed")
    require(set(errors[0]) == {"level", "code", "message"},
            "Spatial Review wrapper changed the legacy JSON shape")


def check_audio_bindings():
    prompt = """subject_definitions:
<Subject 1> is ref_image_0 identity reference
<Audio 1> is ref_audio_0 dialogue reference
summary:
[reference generation]
"""
    bindings = autodl.validate_prompt_audio_bindings(prompt, ["https://example.com/a.wav"])
    require(bindings[0]["prompt_slot"] == "<Audio 1>", "audio slot was not bound")
    try:
        autodl.validate_prompt_audio_bindings(prompt, [])
    except SystemExit:
        pass
    else:
        raise AssertionError("referenced-but-not-uploaded audio was accepted")
    wrong_image_prompt = "subject_definitions:\n<Video 1> ref_image_0\nsummary:\nok"
    try:
        autodl.validate_prompt_image_bindings(wrong_image_prompt, ["https://example.com/a.png"])
    except SystemExit:
        pass
    else:
        raise AssertionError("image reference was accepted as a Video tag")


def check_submit_receipt_and_case_defaults():
    prompt = """subject_definitions:
<Subject 1> is the approved identity shown exclusively in ref_image_0.
summary:
[reference generation] test
retention_analysis:
<Subject 1> ([Shot 1]): fully_preserved.
detailed_description:
[Shot 1] At 00:00.000, hold still.
overall_soundscape:
Room tone.
non_diegetic_music:
N/A
"""
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        original_submit = autodl.submit
        original_argv = sys.argv
        try:
            autodl.submit = lambda payload: {
                "code": "Success", "data": {"status": "queued", "task_id": "task-submit-1"}}
            sys.argv = ["autodl_minimax_h3.py", "submit", "--prompt", prompt,
                        "--ref-image", "https://example.com/ref.png",
                        "--unit-id", "U01", "--artifact-root", str(root),
                        "--prefix", "u01"]
            output = io.StringIO()
            with redirect_stdout(output):
                require(autodl.main() == 0, "mock submit did not complete")
        finally:
            autodl.submit = original_submit
            sys.argv = original_argv
        metadata_path = root / "stage5" / "metadata" / "videos" / "u01_result.json"
        require(metadata_path.is_file(), "default metadata path did not derive from artifact root")
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        attempt = metadata.get("active_generation", {})
        require(attempt.get("unit_id") == "U01" and attempt.get("task_id") == "task-submit-1",
                "submit receipt did not bind unit/task")
        require(attempt.get("request_metadata_path") == "stage5/metadata/videos/u01_result.json",
                "submit receipt path was not case-relative")
        require(attempt.get("status") == "queued" and "manifest.active_generation" in output.getvalue(),
                "submit did not emit a ready-to-register generation attempt")


def check_context_reference():
    context_hash = "sha256:" + "a" * 64
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        packet_path = root / "derived" / "contexts" / "video" / "U01.json"
        packet_path.parent.mkdir(parents=True)
        packet_path.write_text(json.dumps({
            "schema_version": "1.0",
            "context_type": "video",
            "scope_id": "U01",
            "context_hash": context_hash,
            "inputs": [{"key": "target_prompt:U01"}],
        }), encoding="utf-8")
        reference_path = root / "U01.reference.json"
        reference_path.write_text(json.dumps({
            "context_type": "video", "scope_id": "U01",
            "context_hash": context_hash,
            "path": "derived/contexts/video/U01.json", "cache_hit": False,
            "artifact_keys": ["target_prompt:U01"],
        }), encoding="utf-8")
        loaded = autodl.load_context_reference(reference_path, root)
        require(loaded["context_type"] == "video" and loaded["artifact_keys"] == ["target_prompt:U01"],
                "valid context reference was not accepted")

        def rejected(reference, packet=None):
            reference_path.write_text(json.dumps(reference), encoding="utf-8")
            if packet is not None:
                packet_path.write_text(json.dumps(packet), encoding="utf-8")
            try:
                autodl.load_context_reference(reference_path, root)
            except SystemExit:
                return
            raise AssertionError("invalid context reference was accepted")

        valid_reference = json.loads(reference_path.read_text(encoding="utf-8"))
        rejected(valid_reference, {"context_type": "video", "scope_id": "U01",
                                   "context_hash": "sha256:" + "b" * 64,
                                   "inputs": [{"key": "target_prompt:U01"}]})
        rejected({**valid_reference, "scope_id": "U02"})
        rejected({**valid_reference, "path": "../outside.json"})
        rejected({**valid_reference, "artifact_keys": ["target_prompt:U01", "scene_master:SC01"]})
        rejected({**valid_reference, "context_type": 7})


def valid_unit(duration=5):
    return {
        "unit_id": "U01", "unit_order": 1, "shot_ids": ["S01"], "beat_ids": ["B1"],
        "narrative_range": {"start_beat_id": "B1", "end_beat_id": "B1", "summary": "result"},
        "generation_duration_seconds": duration, "shooting_form": "multi_shot",
        "boundary": {"entry_reason": "stable", "exit_reason": "result", "exit_state_recoverable": True,
                     "unresolved_causality": []},
        "capacity": {"dialogue_seconds": 0, "observable_beat_count": 1,
                     "beats_per_10_seconds": 2.0, "max_simultaneous_action_lanes": 1,
                     "key_contact_count": 0, "prop_state_change_count": 0,
                     "character_position_change_count": 0, "cut_count": 0,
                     "precision_risks": [], "physical_action_density": 0.0,
                     "execution_risk": "low", "rationale": "one stable beat"},
    }


def check_duration_and_capacity():
    shots = {"S01": {"shot_id": "S01", "beat_ids": ["B1"],
                      "shot_card": {"timing": {"duration": "5.0s"}}}}
    errors = []
    workflow._validate_unit_plan(valid_unit(), shots, True, errors)
    require(not errors, f"valid measurable capacity failed: {errors}")
    errors = []
    workflow._validate_unit_plan(valid_unit(5.5), shots, True, errors)
    require("unit-duration-invalid" in codes(errors), "fractional API duration was accepted")


def check_state_matrix():
    units = {"U01": {"unit_id": "U01", "production_status": "GENERATED_AWAITING_USER"}}
    errors = []
    workflow._validate_workflow_state(
        {"workflow_state": "DELIVERED", "active_unit_id": "U01",
         "delivery": {"mode": "generated-video"}}, units, errors)
    require("workflow-state-evidence-drift" in codes(errors), "DELIVERED bypassed user acceptance")
    units["U01"]["production_status"] = "USER_ACCEPTED"
    errors = []
    workflow._validate_workflow_state(
        {"workflow_state": "DELIVERED", "active_unit_id": "U01",
         "delivery": {"mode": "generated-video"}}, units, errors)
    require(not errors, f"accepted generated-video state failed: {errors}")
    asset = {"asset_id": "V01", "kind": "generated-video", "unit_id": "U01",
             "sha256": "sha256:" + "a" * 64}
    unit = {"unit_id": "U01", "production_status": "USER_ACCEPTED", "video_asset_id": "V01",
            "user_acceptance": {"decision": "accepted", "statement": "通过", "decided_by": "user",
                                "decided_at": "2026-09-16T12:00:00+08:00",
                                "video_asset_id": "V01", "video_asset_sha256": "sha256:" + "b" * 64}}
    errors = []
    workflow._validate_unit_production(unit, {"V01": asset}, errors)
    require("unit-user-acceptance-version-drift" in codes(errors),
            "user decision was not bound to the immutable video version")
    errors = []
    workflow._validate_active_generation(
        {"workflow_state": "IN_PRODUCTION", "active_unit_id": "U01"},
        {"U01": {"production_status": "PROMPT_READY"}}, {}, None, errors)
    require("active-generation-missing" in codes(errors), "IN_PRODUCTION passed without task evidence")


def check_progressive_state_and_paths():
    report = workflow.inspect({
        "schema_version": "2.2", "planning_mode": "shot-card-first",
        "workflow_state": "SOURCE_READY", "workflow_id": "W1", "script_ir": {},
        "delivery": {"mode": "prompt-only"},
    })
    require(report["status"] == "通过", f"SOURCE_READY required downstream layers: {report['errors']}")
    expected_by_state = {
        "SPACE_READY": {"scene_maps", "spatial_reviews", "artifacts"},
        "SHOTS_LOCKED": {"scene_maps", "spatial_reviews", "artifacts", "shots",
                         "scene_direction_briefs", "coverage_plans"},
        "UNITS_READY": {"scene_maps", "spatial_reviews", "artifacts", "shots",
                        "scene_direction_briefs", "coverage_plans", "units", "coverage"},
    }
    base = {"schema_version": "2.2", "planning_mode": "shot-card-first",
            "workflow_id": "W1", "script_ir": {}, "delivery": {"mode": "prompt-only"}}
    for state, required_fields in expected_by_state.items():
        report = workflow.inspect({**base, "workflow_state": state})
        detail = messages(report["errors"])
        require(all(f"缺少工作流字段: {field}" in detail for field in required_fields),
                f"{state} did not require its cumulative layer fields: {detail}")
        future_field = "units" if state == "SPACE_READY" else "assets"
        require(f"缺少工作流字段: {future_field}" not in detail,
                f"{state} prematurely required future field {future_field}")
    errors, warnings = [], []
    workflow._validate_file_artifacts(
        {"workflow_state": "PROMPTS_VALIDATED"}, None, errors, warnings)
    require("artifact-registry-missing" in codes(errors), "prompt gate passed without real artifacts")
    with tempfile.TemporaryDirectory() as case_root, tempfile.TemporaryDirectory() as outside:
        try:
            workflow._resolve_artifact(Path(case_root), str(Path(outside) / "old.md"))
        except ValueError:
            pass
        else:
            raise AssertionError("absolute historical artifact escaped case isolation")


def execution_target(method="model", model="minimax-h3", platform=None,
                     contract="minimax-h3-direct-v1"):
    return {
        "delivery_method": method,
        "target_model": model,
        "api_platform": platform,
        "adapter_id": "minimax_h3_zm_u24" if platform == "autodl-art" else None,
        "prompt_contract": contract,
        "confirmation": {"statement": "用户确认的临时测试目标", "confirmed_by": "user",
                         "confirmed_at": "2026-09-16T12:00:00+08:00"},
        "contract_source": "ephemeral-test-contract",
        "contract_verified_at": "2026-09-16",
    }


def check_execution_target_routing():
    errors = []
    workflow._validate_execution_target({"workflow_state": "ASSETS_READY"}, errors)
    require("execution-target-missing" in codes(errors),
            "ASSETS_READY passed without a user-confirmed execution target")

    errors = []
    workflow._validate_execution_target(
        {"workflow_state": "ASSETS_READY", "execution_target": execution_target()}, errors)
    require(not errors, f"valid direct MiniMax H3 target failed: {errors}")

    autodl_target = execution_target("api", "minimax-h3", "autodl-art",
                                     "autodl-minimax-h3-v1")
    errors = []
    workflow._validate_execution_target(
        {"workflow_state": "PROMPTS_VALIDATED", "execution_target": autodl_target}, errors)
    require(not errors, f"valid AutoDL MiniMax H3 target failed: {errors}")

    seedance_target = execution_target(
        "model", "seedance-2.5", None, "seedance-2.5-direct-v1")
    errors = []
    workflow._validate_execution_target(
        {"workflow_state": "PROMPTS_VALIDATED", "execution_target": seedance_target}, errors)
    require(not errors, f"valid direct Seedance target failed: {errors}")

    seedance_api = execution_target("api", "seedance-2.5", "unknown", "unresolved")
    errors = []
    workflow._validate_execution_target(
        {"workflow_state": "PROMPTS_VALIDATED", "execution_target": seedance_api}, errors)
    require("execution-target-unsupported" in codes(errors),
            "unimplemented Seedance API incorrectly passed as submit-ready")

    direct_block = """```text
subject_definitions:
<Subject 1> is the approved character identity.

summary:
[reference generation] STYLE_LOCK

retention_analysis:
<Subject 1> ([Shot 1]): fully_preserved.

detailed_description:

overall_soundscape:
N/A

non_diegetic_music:
N/A
```
"""
    autodl_block = direct_block.replace(
        "approved character identity.", "approved character identity from ref_image_0.")

    def validate_draft(root, target, body):
        draft = root / "prompt.md"
        draft.write_text(body, encoding="utf-8")
        manifest = {
            "schema_version": "2.2", "workflow_state": "PROMPTS_VALIDATED",
            "execution_target": target, "project_style_lock": "STYLE_LOCK",
            "script_ir": {"beats": [], "on_screen_text": []},
            "scene_maps": [], "shots": [],
            "units": [{"unit_id": "U01", "unit_order": 1, "shot_ids": [],
                       "h3_shot_numbers": [], "input_bindings": [
                           {"order": 1, "media_type": "image", "slot": "<Subject 1>",
                            "asset_id": "A01"}]}],
            "artifacts": {"delivery_draft": {"path": "prompt.md",
                                               "sha256": workflow._sha256(draft),
                                               "unit_ids": ["U01"]}, "scene_maps": []},
        }
        errors, warnings = [], []
        workflow._validate_file_artifacts(manifest, root, errors, warnings)
        return codes(errors)

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        direct_codes = validate_draft(root, execution_target(), direct_block)
        require("direct-prompt-api-leak" not in direct_codes,
                "clean direct-model prompt was rejected")
        direct_leak_codes = validate_draft(root, execution_target(), autodl_block)
        require("direct-prompt-api-leak" in direct_leak_codes,
                "direct-model prompt accepted AutoDL fields")
        autodl_codes = validate_draft(root, autodl_target, autodl_block)
        require(not ({"autodl-binding-count-drift", "autodl-binding-slot-drift"} & autodl_codes),
                f"valid AutoDL binding failed: {autodl_codes}")
        wrong_autodl_codes = validate_draft(root, autodl_target, direct_block)
        require("autodl-binding-count-drift" in wrong_autodl_codes,
                "AutoDL prompt passed without ordered API binding")


def check_video_provenance():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        video = root / "unit.mp4"
        video.write_bytes(b"ephemeral-video-fixture")
        request_meta = {"unit_id": "U01", "duration": 5}
        request_hash = autodl.canonical_hash(request_meta)
        metadata = {"data": {"task_id": "task-1", "status": "completed", "results": [
            {"type": "video", "url": "https://example.com/v.mp4"}]}, "_request": request_meta}
        (root / "result.json").write_text(json.dumps(metadata), encoding="utf-8")
        asset = {"asset_id": "V01", "tag": "generated-video-U01-01", "kind": "generated-video",
                 "unit_id": "U01", "task_id": "task-1", "result_url": "https://example.com/v.mp4",
                 "local_path": "unit.mp4", "sha256": workflow._sha256(video),
                 "request_metadata_hash": request_hash, "request_metadata_path": "result.json"}
        errors = []
        workflow._validate_generated_video_assets([asset], {"U01": {}}, root, errors)
        require(not errors, f"valid video provenance failed: {errors}")
        attempt = {"unit_id": "U01", "task_id": "task-1",
                   "request_metadata_path": "result.json", "request_metadata_hash": request_hash,
                   "submitted_at": "2026-09-16T04:00:00+00:00", "status": "running"}
        errors = []
        workflow._validate_active_generation(
            {"workflow_state": "IN_PRODUCTION", "active_unit_id": "U01",
             "active_generation": attempt}, {"U01": {}}, {}, root, errors)
        require(not errors, f"valid active_generation failed: {errors}")
        require(autodl.normalized_attempt_state(metadata) == "completed",
                "completed API response was not normalized")
        asset["sha256"] = "sha256:" + "0" * 64
        errors = []
        workflow._validate_generated_video_assets([asset], {"U01": {}}, root, errors)
        require("generated-video-file-hash-drift" in codes(errors), "replaced video was accepted")
        asset["sha256"] = workflow._sha256(video)
        metadata["data"].pop("task_id")
        metadata["data"]["status"] = "failed"
        (root / "result.json").write_text(json.dumps(metadata), encoding="utf-8")
        errors = []
        workflow._validate_generated_video_assets([asset], {"U01": {}}, root, errors)
        require({"generated-video-task-proof-missing", "generated-video-result-not-successful"} <= codes(errors),
                "failed task metadata without task_id was accepted")


def check_text_policy_and_h3_facts():
    def locked(expected):
        return {"expected_text": expected, "ocr_status": "passed",
                "ocr_evidence": ["reviews/ocr.txt"], "user_review_status": "passed",
                "user_confirmation_statement": "用户逐字确认",
                "confirmed_file_sha256": "sha256:" + "a" * 64}

    assets = {
        "P01": {"asset_id": "P01", "kind": "canonical", "text_lock": locked("CONSENT")},
        "D01": {"asset_id": "D01", "kind": "canonical", "text_lock": locked("")},
        "D01-before": {"lineage_root_asset_id": "D01", "derived_from": ["D01"],
                       "text_lock": locked("")},
        "D01-after": {"lineage_root_asset_id": "D01", "derived_from": ["D01"],
                      "text_lock": locked("陶然")},
    }
    script = {"on_screen_text": [
        {"text": "CONSENT", "category": "object_intrinsic", "treatment": "asset_locked", "asset_id": "P01"},
        {"text": "SIGNATURE", "category": "dynamic_state", "treatment": "same_source_states",
         "state_asset_ids": ["D01-before", "D01-after"],
         "expected_text_by_asset": {"D01-before": "", "D01-after": "陶然"}},
        {"text": "SUBTITLE", "category": "editorial", "treatment": "post_production"},
    ]}
    errors = []
    workflow._validate_text_policy(script, assets, errors)
    require(not errors, f"valid text categories failed: {errors}")
    assets["D01-mid"] = {"lineage_root_asset_id": "D01", "derived_from": ["D01"],
                         "text_lock": locked("draft")}
    assets["D01-after"]["derived_from"] = ["D01-mid"]
    errors = []
    workflow._validate_text_policy(script, assets, errors)
    require(not errors, f"transitive text lineage failed: {errors}")
    assets["D01-after"]["lineage_root_asset_id"] = "FAKE"
    errors = []
    workflow._validate_text_policy(script, assets, errors)
    require("screen-text-state-lineage-drift" in codes(errors), "fake lineage root was accepted")
    assets["D01-after"]["lineage_root_asset_id"] = "D01"
    script["on_screen_text"][1]["expected_text_by_asset"]["D01-after"] = "wrong"
    errors = []
    workflow._validate_text_policy(script, assets, errors)
    require("screen-text-state-proof-incomplete" in codes(errors), "state text mismatch was accepted")
    script["on_screen_text"][1]["expected_text_by_asset"]["D01-after"] = "陶然"
    assets["D01-after"]["text_lock"]["user_confirmation_statement"] = ""
    errors = []
    workflow._validate_text_policy(script, assets, errors)
    require("screen-text-state-proof-incomplete" in codes(errors),
            "text asset passed without explicit user confirmation")
    shot = {"shot_id": "S01", "h3_execution_facts": {
        "hand": {"value": "right", "required_literals": ["right hand"],
                 "forbidden_literals": ["left hand"]}}}
    errors = []
    workflow._validate_execution_facts(shot, "uses the left hand", True, errors)
    require({"h3-execution-fact-missing", "h3-execution-fact-contradiction"} <= codes(errors),
            "H3 execution contradiction was not detected")
    errors = []
    workflow._validate_execution_facts(
        {"shot_id": "S02", "shot_card": {"action_states": {"start": "idle", "end": "signed"}},
         "h3_execution_facts": {}}, "", True, errors)
    require("h3-execution-facts-incomplete" in codes(errors), "empty H3 execution facts passed")


def check_spatial_signature_split():
    scene = {"scene_id": "S1", "primary_axis": "north-south", "fixed_anchors": [],
             "walkable_zones": [], "occupancy_zones": [], "objects": [],
             "blocking_states": {}, "user_review": {"map_version": "v1"},
             "camera": {"C1": {"position": [0, 0], "orientation": 0}}}
    layout_before = spatial.scene_review_signature(scene, "layout")
    camera_before = spatial.scene_review_signature(scene, "camera_plan")
    scene["camera"]["C1"]["orientation"] = 90
    require(layout_before == spatial.scene_review_signature(scene, "layout"),
            "camera change invalidated layout confirmation")
    require(camera_before != spatial.scene_review_signature(scene, "camera_plan"),
            "camera change did not invalidate camera-plan confirmation")


def check_continuous_space_scene_mapping():
    room = {"scene_id": "SPACE-ROOM", "continuous_space_id": "SPACE-ROOM",
            "scene_ids": ["S1", "S3"]}
    game = {"scene_id": "SPACE-GAME", "continuous_space_id": "SPACE-GAME",
            "scene_ids": ["S2"]}
    aliases, duplicates = workflow._scene_map_scene_index([room, game])
    require(not duplicates and aliases["S1"] is aliases["S3"] is room,
            "two Script IR scenes did not share one canonical continuous-space map")
    conflict = {"scene_id": "SPACE-OTHER", "scene_ids": ["S3"]}
    _, duplicates = workflow._scene_map_scene_index([room, conflict])
    require(duplicates == {"S3"}, "ambiguous scene-to-space binding was not detected")


def check_layout_before_camera_gate():
    scene = {
        "scene_id": "S-layout", "primary_axis": "north-south",
        "space_boundary": {"boundary_type": "room", "polygon": [[0, 0], [4, 0], [4, 4], [0, 4]]},
        "fixed_anchors": [{"anchor_id": "door", "position": [2, 4]}],
        "walkable_zones": [{"zone_id": "main", "polygon": [[0, 0], [4, 0], [4, 4], [0, 4]]}],
        "objects": [{"object_id": "P", "object_type": "person", "role": "story-object",
                     "position": [2, 2], "orientation": 0, "state": "still",
                     "relations": [], "visible_anchors": []}],
        "blocking_states": {"A": {"objects": {"P": {"position": [2, 2]}}}},
        "movement_routes": [], "camera": {},
        "user_review": {"review_phase": "layout", "state_sequence": ["A"]},
    }
    report = spatial.inspect(scene)
    require(not any("camera" in item for item in report["errors"]),
            f"layout phase incorrectly required a fabricated camera: {report['errors']}")
    scene["user_review"]["review_phase"] = "camera_plan"
    report = spatial.inspect(scene)
    require("缺少场景字段: camera" in report["errors"],
            "camera-plan phase passed without a real camera")


def check_user_facing_map_labels():
    scene = {
        "scene_id": "S-map", "primary_axis": "left-right",
        "space_boundary": {"boundary_type": "virtual", "polygon": [[0, 0], [9, 0], [9, 9], [0, 9]]},
        "fixed_anchors": [{"anchor_id": "A-INTERNAL", "position": [4.5, 8],
                           "features": "自然中文锚点，补充说明"}],
        "walkable_zones": [{"zone_id": "main", "polygon": [[0, 0], [9, 0], [9, 9], [0, 9]]}],
        "objects": [
            {"object_id": "P-LONG", "object_type": "person", "role": "story-object",
             "position": [1, 5], "orientation": 90, "state": "起始状态", "relations": [],
             "visible_anchors": ["A-INTERNAL"]},
            {"object_id": "P-SECOND", "object_type": "person", "role": "story-object",
             "position": [2, 5], "orientation": 90, "state": "起始状态", "relations": [],
             "visible_anchors": ["A-INTERNAL"]},
        ],
        "blocking_states": {}, "movement_routes": [], "camera": {},
        "user_review": {"review_phase": "layout", "space_name": "测试空间",
                        "tracked_entities": ["P-LONG", "P-SECOND"],
                        "entity_labels": {"P-LONG": "不会被截断的较长中文人物名称",
                                          "P-SECOND": "同格第二人物"}},
    }
    rendered = blocking_map.render_text_map(scene)
    require("A-INTERNAL" not in rendered, "user-facing map leaked an internal anchor id")
    require("不会被截断的较长中文人物名称" in rendered,
            "user-facing map truncated a long Chinese label")
    diagram = rendered.split("```text", 1)[1].split("```", 1)[0]
    require("同格第二人物" in diagram, "second entity in one map cell was omitted")


def check_spatial_boundary_and_reachability():
    scene = {
        "scene_id": "S1", "primary_axis": "north-south",
        "space_boundary": {"boundary_type": "room", "polygon": [[0, 0], [10, 0], [10, 10], [0, 10]]},
        "fixed_anchors": [{"anchor_id": "door", "position": [5, 10]}],
        "walkable_zones": [{"zone_id": "main", "polygon": [[0, 0], [10, 0], [10, 10], [0, 10]]}],
        "objects": [{"object_id": "P", "object_type": "person", "role": "story-object",
                     "position": [2, 2], "orientation": 0, "state": "still", "relations": [],
                     "visible_anchors": []}],
        "blocking_states": {}, "movement_routes": [],
        "camera": {"C1": {"position": [12, 5], "placement": "inside", "side": "safe",
                            "orientation": 270, "visible_anchors": ["door"], "forbidden_anchors": []}},
    }
    report = spatial.inspect(scene)
    require(any("spatial-camera-placement-drift" in item for item in report["errors"]),
            "camera outside the real boundary passed as inside")
    scene["camera"]["C1"] = {"position": [2, 2], "placement": "attached", "side": "safe",
                              "orientation": 0, "visible_anchors": ["door"],
                              "forbidden_anchors": []}
    report = spatial.inspect(scene)
    require(any("spatial-camera-attachment-missing" in item for item in report["errors"]),
            "attached camera passed without attached_to")

    scene["camera"]["C1"] = {"position": [2, 2], "placement": "inside", "side": "safe",
                              "orientation": 0, "visible_anchors": ["door"],
                              "forbidden_anchors": []}
    scene["blocking_states"] = {
        "A": {"objects": {"P": {"position": [2, 2]}}},
        "B": {"objects": {"P": {"position": [8, 2]}}},
    }
    scene["user_review"] = {"state_sequence": ["A", "B"]}
    report = spatial.inspect(scene)
    require(any("spatial-route-missing" in item for item in report["errors"]),
            "moved person passed without route")
    scene["movement_routes"] = [{"route_id": "R1", "object_id": "P",
                                  "from_state_id": "A", "to_state_id": "B",
                                  "points": [[2, 2], [8, 2]]}]
    report = spatial.inspect(scene)
    require(not any("spatial-route-" in item for item in report["errors"]),
            f"valid route failed: {report['errors']}")
    scene["occupancy_zones"] = [{"zone_id": "blocked", "polygon": [[4, 1], [6, 1], [6, 3], [4, 3]],
                                 "access": "forbidden", "applies_to": ["P"], "reason": "wall"}]
    report = spatial.inspect(scene)
    require(any("spatial-route-forbidden-zone" in item for item in report["errors"]),
            "route through forbidden zone was accepted")


def check_asset_ledger_authority():
    ledger = asset_ledger.new_ledger("ephemeral")
    try:
        asset_ledger.upsert_unit(ledger, 1, status="待用户验收")
    except ValueError:
        pass
    else:
        raise AssertionError("image ledger accepted video review status")
    ledger["units"]["1"] = {"status": "待生成", "video_asset": "V01",
                             "decision_statement": "通过"}
    issue_codes = {code for level, code, _ in asset_ledger.validate_ledger(ledger)
                   if level == "ERROR"}
    require("unit-video-authority-duplicate" in issue_codes,
            "image ledger accepted duplicate video authority")


def check_asset_contracts():
    base = {
        "asset_type": "directional_prop", "identity_scope": ["phone-v1"],
        "prompt_operation": "canonical_create", "style_application": "project-texture-lock",
        "required_view": "front-screen-facing",
        "required_elements": ["one_phone", "front_screen"],
        "forbidden_elements": ["rear_panel", "rear_camera", "second_phone"],
        "topology": {"object_count": 1, "visible_surfaces": ["front_screen"],
                     "mutually_exclusive_surface_groups": [["front_screen", "rear_panel"]]},
        "state": {"screen": "off"}, "variable_regions": ["display_region"],
        "usage_scope": ["canonical_source"],
        "upload_policy": {"mode": "lineage-final-only", "replaces_ancestor_for_video": False},
        "provenance": {"lineage_root_asset_id": "a01", "derived_from": []},
        "review_contract": {"file_check": "passed", "physical_structure": "passed",
                            "visible_surface": "passed",
                            "ocr": {"status": "not_required", "evidence": []},
                            "user_confirmation": {"status": "confirmed", "statement": "确认",
                                                  "file_sha256": "sha256:" + "a" * 64}},
        "required_visible_surface": ["front_screen"],
        "forbidden_visible_surface": ["rear_panel", "rear_camera"],
        "interaction_surface": "front_screen", "orientation": "portrait-upright",
        "reading_direction": "top-to-bottom", "allowed_state_transitions": ["screen_off_to_on"],
    }
    asset = {"asset_id": "a01", "kind": "canonical", "derived_from": [],
             "visual_state": "用户确认", "asset_contract": base}
    require(not asset_ledger.validate_asset_contract(asset), "valid directional asset contract failed")

    conflict = json.loads(json.dumps(base))
    conflict["topology"]["visible_surfaces"].append("rear_panel")
    codes_found = {code for code, _ in asset_ledger.validate_asset_contract(
        {**asset, "asset_contract": conflict})}
    require("asset-contract-mutually-exclusive-surfaces" in codes_found,
            "mutually exclusive phone surfaces were accepted")
    require("asset-contract-forbidden-surface-visible" in codes_found,
            "forbidden rear surface was accepted")

    missing = json.loads(json.dumps(base))
    missing["topology"]["visible_surfaces"] = []
    codes_found = {code for code, _ in asset_ledger.validate_asset_contract(
        {**asset, "asset_contract": missing})}
    require("asset-contract-required-surface-missing" in codes_found,
            "missing required front surface was accepted")

    text_contract = json.loads(json.dumps(base))
    text_contract.update({"asset_type": "screen_text", "physical_carrier_asset_id": "a01",
                          "prompt_operation": "reference_edit", "style_application": "inherit-source",
                          "display_region": "screen bounds", "allowed_exact_text": ["消息"],
                          "forbidden_extra_text": True, "same_device_lineage": True})
    for key in asset_ledger.SPECIALIZED_CONTRACT_FIELDS["directional_prop"]:
        text_contract.pop(key, None)
    text_contract["review_contract"]["ocr"] = {"status": "not_requested", "evidence": []}
    text_asset = {"asset_id": "a02", "kind": "derived", "derived_from": ["a01"],
                  "visual_state": "用户确认", "text_lock": {"expected_text": "消息"},
                  "asset_contract": text_contract}
    text_contract["provenance"] = {"lineage_root_asset_id": "a01", "derived_from": ["a01"]}
    codes_found = {code for code, _ in asset_ledger.validate_asset_contract(text_asset)}
    require("asset-contract-ocr-proof-incomplete" not in codes_found,
            "screen text asset incorrectly required automatic OCR")
    text_contract["review_contract"]["user_confirmation"] = {
        "status": "pending", "statement": "", "file_sha256": "sha256:" + "a" * 64}
    codes_found = {code for code, _ in asset_ledger.validate_asset_contract(text_asset)}
    require("asset-contract-user-confirmation-incomplete" in codes_found,
            "screen text asset passed without a user decision")

    texture_lock = "realistic texture, restrained grain, neutral color response"
    reference_prompt = (
        "Preserve the source image lighting, camera and material texture. "
        "Change only pixels inside the bounded display region."
    )
    require(not check_asset_prompt.inspect(reference_prompt, text_contract, texture_lock),
            "valid reference edit Prompt failed operation-aware style check")
    injected = reference_prompt + " " + texture_lock
    require(any("不得重复完整项目质感锁" in item for item in
                check_asset_prompt.inspect(injected, text_contract, texture_lock)),
            "reference edit accepted a repeated project texture lock")
    canonical_prompt = "One phone on neutral background. " + texture_lock
    require(not check_asset_prompt.inspect(canonical_prompt, base, texture_lock),
            "canonical Prompt failed to apply the project texture lock")

    root_asset = {**asset, "asset_id": "a01"}
    state_asset = {**text_asset, "asset_id": "a02"}
    errors = []
    workflow._validate_lineage_uploads(
        "U02", {"<Subject 1>": root_asset, "<Subject 2>": state_asset}, errors)
    require("input-lineage-duplicate" in codes(errors),
            "canonical and final state from one lineage were both accepted for upload")
    errors = []
    workflow._validate_lineage_uploads("U02", {"<Subject 1>": state_asset}, errors)
    require(not errors, "single final state asset was rejected")

    with tempfile.TemporaryDirectory() as directory:
        user_file = Path(directory) / "user-return.png"
        user_file.write_bytes(b"user-return-fixture")
        ledger = asset_ledger.new_ledger("user-return")
        imported_id, digest = asset_ledger.register_user_file(
            ledger, user_file, "canonical", tags=["phone-user-v1"], role="prop",
            asset_contract=base, model_label="external-image-model")
        imported = ledger["assets"][imported_id]
        require(imported["generation_owner"] == "user" and imported["file_sha256"] == digest,
                "user-returned image did not preserve owner and file hash")
        issue_codes = {code for level, code, _ in asset_ledger.validate_ledger(ledger)
                       if level == "ERROR"}
        require("canonical-model" not in issue_codes,
                "user-returned canonical was incorrectly forced through an internal image model")
