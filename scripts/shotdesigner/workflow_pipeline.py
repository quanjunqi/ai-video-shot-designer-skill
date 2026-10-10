"""Workflow validation pipeline separated from the CLI entrypoint."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

import workflow_config


@dataclass(frozen=True)
class PipelineServices:
    BASE_REQUIRED_TOP_LEVEL: Any
    IMAGE_ONLY_DELIVERABLES: Any
    INDEPENDENT_TRANSITIONS: Any
    NON_PRODUCTION_IMAGE_KINDS: Any
    PASS_STORYBOARD_STATES: Any
    PASS_VISUAL_STATES: Any
    UNIT_PRODUCTION_STATES: Any
    VERSION_CONFIG: Any
    WORKFLOW_STATES: Any
    _as_list: Any
    _camera_anchor_ids: Any
    _camera_map: Any
    _ids: Any
    _inspection_result: Any
    _issue: Any
    _max_unit_duration: Any
    _scene_map_index: Any
    _scene_map_scene_index: Any
    _state_at_least: Any
    _state_equal: Any
    _validate_active_generation: Any
    _validate_director_review_artifact: Any
    _validate_duration_budget: Any
    _validate_execution_target: Any
    _validate_file_artifacts: Any
    _validate_generated_video_assets: Any
    _validate_lineage_uploads: Any
    _validate_script_manifest: Any
    _validate_shot_cards: Any
    _validate_spatial_reviews: Any
    _validate_storyboards: Any
    _validate_text_policy: Any
    _validate_unit_plan: Any
    _validate_unit_production: Any
    _validate_v22_direction_and_coverage: Any
    _validate_workflow_state: Any
    spatial: Any


def inspect(workflow, artifact_root, services):
    BASE_REQUIRED_TOP_LEVEL = services.BASE_REQUIRED_TOP_LEVEL
    IMAGE_ONLY_DELIVERABLES = services.IMAGE_ONLY_DELIVERABLES
    INDEPENDENT_TRANSITIONS = services.INDEPENDENT_TRANSITIONS
    NON_PRODUCTION_IMAGE_KINDS = services.NON_PRODUCTION_IMAGE_KINDS
    PASS_STORYBOARD_STATES = services.PASS_STORYBOARD_STATES
    PASS_VISUAL_STATES = services.PASS_VISUAL_STATES
    UNIT_PRODUCTION_STATES = services.UNIT_PRODUCTION_STATES
    VERSION_CONFIG = services.VERSION_CONFIG
    WORKFLOW_STATES = services.WORKFLOW_STATES
    _as_list = services._as_list
    _camera_anchor_ids = services._camera_anchor_ids
    _camera_map = services._camera_map
    _ids = services._ids
    _inspection_result = services._inspection_result
    _issue = services._issue
    _max_unit_duration = services._max_unit_duration
    _scene_map_index = services._scene_map_index
    _scene_map_scene_index = services._scene_map_scene_index
    _state_at_least = services._state_at_least
    _state_equal = services._state_equal
    _validate_active_generation = services._validate_active_generation
    _validate_director_review_artifact = services._validate_director_review_artifact
    _validate_duration_budget = services._validate_duration_budget
    _validate_execution_target = services._validate_execution_target
    _validate_file_artifacts = services._validate_file_artifacts
    _validate_generated_video_assets = services._validate_generated_video_assets
    _validate_lineage_uploads = services._validate_lineage_uploads
    _validate_script_manifest = services._validate_script_manifest
    _validate_shot_cards = services._validate_shot_cards
    _validate_spatial_reviews = services._validate_spatial_reviews
    _validate_storyboards = services._validate_storyboards
    _validate_text_policy = services._validate_text_policy
    _validate_unit_plan = services._validate_unit_plan
    _validate_unit_production = services._validate_unit_production
    _validate_v22_direction_and_coverage = services._validate_v22_direction_and_coverage
    _validate_workflow_state = services._validate_workflow_state
    spatial = services.spatial
    errors = []
    warnings = []
    if not isinstance(workflow, dict):
        return {"status": "失败", "errors": [{"code": "workflow-type", "message": "工作流 manifest 必须是 JSON 对象"}], "warnings": []}

    raw_schema_version = workflow.get("schema_version")
    schema_version = str(raw_schema_version or "1.0")
    strict_v2 = schema_version.startswith("2.")
    capabilities = workflow_config.schema_capabilities(schema_version)
    strategy_required = "strategy_selection" in capabilities
    coverage_required = "coverage_plan" in capabilities
    state = workflow.get("workflow_state")
    required_fields = list(
        workflow_config.required_fields_for(state) if strict_v2 else BASE_REQUIRED_TOP_LEVEL)
    if not strict_v2:
        required_fields.extend(("scene_maps", "shots", "units", "assets"))
    missing = [field for field in dict.fromkeys(required_fields) if field not in workflow]
    for field in missing:
        _issue(errors, "ERROR", "workflow-field-missing", f"缺少工作流字段: {field}")
    if missing:
        return {"status": "失败", "errors": errors, "warnings": warnings}

    if raw_schema_version is None:
        _issue(warnings, "WARNING", "schema-version-missing-legacy",
               "未声明 schema_version，按 legacy v1 只读兼容；新项目必须使用 2.2")
    elif not capabilities:
        _issue(errors, "ERROR", "schema-version-unsupported",
               f"不支持的 schema_version: {schema_version}")
    if strict_v2:
        expected_mode = VERSION_CONFIG["new_project"]["planning_mode"]
        if workflow.get("planning_mode") != expected_mode:
            _issue(errors, "ERROR", "planning-mode-invalid",
                   f"v2 planning_mode 必须是 {expected_mode}")
        if state not in WORKFLOW_STATES:
            _issue(errors, "ERROR", "workflow-state-invalid",
                   f"v2 workflow_state 必须是受控状态，当前={state}")

    script = workflow.get("script_ir")
    if not isinstance(script, dict):
        _issue(errors, "ERROR", "script-ir-type", "script_ir 必须是 JSON 对象")
        return {"status": "失败", "errors": errors, "warnings": warnings}

    delivery = workflow.get("delivery")
    if not isinstance(delivery, dict):
        _issue(errors, "ERROR", "delivery-type", "delivery 必须是对象")
    elif delivery.get("mode") not in {"prompt-only", "generated-video"}:
        _issue(errors, "ERROR", "delivery-mode-invalid",
               "delivery.mode 必须是 prompt-only 或 generated-video")
    if strict_v2:
        _validate_execution_target(workflow, errors)
    if strict_v2 and state == "SOURCE_READY":
        return _inspection_result(errors, warnings)

    scenes = _as_list(script.get("scenes"))
    characters = _as_list(script.get("characters"))
    props = _as_list(script.get("props"))
    beats = _as_list(script.get("beats"))
    scene_ids = _ids(scenes, "scene_id") | _ids(scenes, "id")
    character_ids = _ids(characters, "character_id") | _ids(characters, "id")
    prop_ids = _ids(props, "prop_id") | _ids(props, "id")
    beat_by_id = {item.get("beat_id", item.get("id")): item for item in beats
                  if isinstance(item, dict) and item.get("beat_id", item.get("id"))}
    _validate_script_manifest(script, beat_by_id, strict_v2, errors, warnings)
    _validate_duration_budget(script, strict_v2, errors, warnings)
    if strict_v2 and state == "SCRIPT_LOCKED":
        return _inspection_result(errors, warnings)
    map_by_space = _scene_map_index(workflow.get("scene_maps"))
    map_by_scene, duplicate_scene_map_aliases = _scene_map_scene_index(workflow.get("scene_maps"))
    if duplicate_scene_map_aliases:
        _issue(errors, "ERROR", "scene-map-scene-alias-duplicate",
               f"剧情场次不能同时绑定多个连续空间: {sorted(duplicate_scene_map_aliases)}")
    scene_by_id = {
        item.get("scene_id", item.get("id")): item for item in scenes
        if isinstance(item, dict) and item.get("scene_id", item.get("id"))
    }
    if _state_at_least(state, "SPACE_READY"):
        for scene_id, scene in scene_by_id.items():
            scene_map = map_by_scene.get(scene_id)
            if not scene_map:
                _issue(errors, "ERROR", "scene-map-script-scene-uncovered",
                       f"Script IR 场次没有连续空间图: {scene_id}")
                continue
            expected_space = scene.get("continuous_space_id", scene_id)
            actual_space = scene_map.get("continuous_space_id", scene_map.get("scene_id"))
            if expected_space != actual_space:
                _issue(errors, "ERROR", "scene-map-continuous-space-drift",
                       f"{scene_id}: Script IR continuous_space_id={expected_space}，scene_map={actual_space}")
        unknown_aliases = set(map_by_scene) - set(scene_by_id)
        if unknown_aliases:
            _issue(errors, "ERROR", "scene-map-scene-alias-unknown",
                   f"scene_map.scene_ids 含 Script IR 未知场次: {sorted(unknown_aliases)}")
    shot_list = _as_list(workflow.get("shots"))
    unit_list = _as_list(workflow.get("units"))
    asset_list = _as_list(workflow.get("assets"))
    shot_by_id = {item.get("shot_id"): item for item in shot_list
                  if isinstance(item, dict) and item.get("shot_id")}
    unit_by_id = {item.get("unit_id"): item for item in unit_list
                  if isinstance(item, dict) and item.get("unit_id")}
    asset_by_tag = {item.get("tag"): item for item in asset_list
                    if isinstance(item, dict) and item.get("tag")}
    asset_by_id = {item.get("asset_id"): item for item in asset_list
                   if isinstance(item, dict) and item.get("asset_id")}
    storyboard_list = _as_list(workflow.get("storyboards"))
    storyboard_by_id = {item.get("storyboard_sheet_id"): item for item in storyboard_list
                        if isinstance(item, dict) and item.get("storyboard_sheet_id")}

    if len(shot_by_id) != len(shot_list):
        _issue(errors, "ERROR", "shot-id-duplicate", "shots 中存在缺少 shot_id 或重复的 shot_id")
    if len(unit_by_id) != len(unit_list):
        _issue(errors, "ERROR", "unit-id-duplicate", "units 中存在缺少 unit_id 或重复的 unit_id")
    if len(asset_by_tag) != len(asset_list):
        _issue(errors, "ERROR", "asset-tag-duplicate", "assets 中存在缺少 tag 或重复的 tag")
    if len(asset_by_id) != len(asset_list):
        _issue(errors, "ERROR", "asset-id-duplicate", "assets 中存在缺少 asset_id 或重复的 asset_id")
    if strict_v2 and _state_at_least(state, "ASSETS_READY"):
        for asset in asset_list:
            if isinstance(asset, dict) and asset.get("kind") in NON_PRODUCTION_IMAGE_KINDS:
                _issue(errors, "ERROR", "v2-planning-asset-forbidden",
                       f"{asset.get('tag', '<unknown>')}: v2 不得把导演总版/规划图登记为生产资产")
        if coverage_required:
            _validate_text_policy(script, asset_by_id, errors)
    if coverage_required and _state_at_least(state, "SHOTS_LOCKED") \
            and (not isinstance(workflow.get("project_style_lock"), str)
                 or not workflow.get("project_style_lock", "").strip()):
        _issue(errors, "ERROR", "project-style-lock-missing",
               "进入 SHOTS_LOCKED 前必须登记完整 project_style_lock")
    if coverage_required and _state_at_least(state, "UNITS_READY"):
        _validate_workflow_state(workflow, unit_by_id, errors)
    if coverage_required and _state_at_least(state, "IN_PRODUCTION"):
        _validate_active_generation(workflow, unit_by_id, asset_by_id, artifact_root, errors)
    if coverage_required and _state_at_least(state, "USER_REVIEW_PENDING"):
        _validate_generated_video_assets(asset_list, unit_by_id, artifact_root, errors)

    _validate_director_review_artifact(
        workflow, artifact_root, shot_by_id, strict_v2, errors, warnings)
    if not strict_v2 or _state_at_least(state, "SPACE_READY"):
        _validate_spatial_reviews(
            workflow, map_by_space, artifact_root, strategy_required, errors, warnings)
        _validate_file_artifacts(workflow, artifact_root, errors, warnings)
        for scene_id, scene_map in map_by_space.items():
            report = spatial.inspect(scene_map)
            for message in report.get("errors", []):
                _issue(errors, "ERROR", "scene-map-invalid", f"{scene_id}: {message}")
            for message in report.get("warnings", []):
                _issue(warnings, "WARNING", "scene-map-warning", f"{scene_id}: {message}")
    if strict_v2 and state == "SPACE_READY":
        return _inspection_result(errors, warnings)
    if storyboard_list:
        _validate_storyboards(storyboard_list, shot_by_id, unit_by_id, map_by_scene, errors, warnings)
        if strict_v2:
            _issue(errors, "ERROR", "v2-storyboards-forbidden",
                   "v2 manifest 不登记 storyboards；历史故事板只能保存在 v1 兼容清单")
    if not strict_v2 or _state_at_least(state, "SHOTS_LOCKED"):
        _validate_shot_cards(
            shot_list,
            strict=strict_v2 or not storyboard_list or workflow.get("planning_mode") == "shot-card-first",
            errors=errors,
            warnings=warnings,
            strategy_required=strategy_required,
        )
    ordered_units = sorted(
        [u for u in unit_list if isinstance(u, dict) and isinstance(u.get("unit_order"), int)],
        key=lambda item: item["unit_order"],
    )

    if coverage_required and _state_at_least(state, "SHOTS_LOCKED"):
        _validate_v22_direction_and_coverage(
            workflow, scene_ids, map_by_scene, shot_list, errors)
    if strict_v2 and _state_at_least(state, "SHOTS_LOCKED"):
        for shot in shot_list:
            if not isinstance(shot, dict):
                continue
            shot_id = shot.get("shot_id", "<unknown>")
            shot_beat_ids = set(_as_list(shot.get("beat_ids")))
            vfx_beat_ids = {
                beat_id for beat_id in shot_beat_ids
                if isinstance(beat_by_id.get(beat_id), dict)
                and beat_by_id[beat_id].get("vfx_special")
            }
            effects = _as_list(shot.get("shot_card", {}).get("effects"))
            bound_effect_beats = {
                beat_id
                for effect in effects if isinstance(effect, dict)
                for beat_id in _as_list(effect.get("beat_ids"))
            }
            missing_vfx = vfx_beat_ids - bound_effect_beats
            if missing_vfx:
                _issue(errors, "ERROR", "shot-card-vfx-contract-missing",
                       f"{shot_id}: 含 vfx_special 的 beat 未绑定 effects 合同: {sorted(missing_vfx)}")
            unrelated_effect_beats = bound_effect_beats - shot_beat_ids
            if unrelated_effect_beats:
                _issue(errors, "ERROR", "shot-card-effect-beat-drift",
                       f"{shot_id}: effects 引用了本镜未覆盖的 beat: {sorted(unrelated_effect_beats)}")
    if strict_v2 and state == "SHOTS_LOCKED":
        return _inspection_result(errors, warnings, shots=len(shot_list))
    if strict_v2 and state == "UNITS_READY":
        unit_beat_owners = {}
        for unit in unit_list:
            if not isinstance(unit, dict):
                continue
            unit_id = unit.get("unit_id", "<unknown>")
            _validate_unit_plan(
                unit, shot_by_id, strict_v2, errors, _max_unit_duration(workflow))
            unit_shots = _as_list(unit.get("shot_ids"))
            missing_shots = [shot_id for shot_id in unit_shots if shot_id not in shot_by_id]
            if missing_shots:
                _issue(errors, "ERROR", "unit-shot-unknown",
                       f"{unit_id}: 引用了不存在的镜头: {missing_shots}")
            wrong_unit = [shot_id for shot_id in unit_shots
                          if shot_id in shot_by_id and shot_by_id[shot_id].get("unit_id") != unit_id]
            if wrong_unit:
                _issue(errors, "ERROR", "unit-shot-drift",
                       f"{unit_id}: 镜头的 unit_id 不一致: {wrong_unit}")
            _validate_unit_production(unit, asset_by_id, errors)
            for beat_id in _as_list(unit.get("beat_ids")):
                unit_beat_owners.setdefault(beat_id, []).append(unit_id)
        included = set(_as_list((workflow.get("coverage") or {}).get("included_beat_ids")))
        if set(unit_beat_owners) != included:
            _issue(errors, "ERROR", "unit-coverage-drift",
                   f"unit beat 覆盖 {sorted(unit_beat_owners)} 与当前批次 included {sorted(included)} 不一致")
        duplicated = {beat_id: owners for beat_id, owners in unit_beat_owners.items() if len(owners) > 1}
        if duplicated:
            _issue(errors, "ERROR", "unit-beat-cross-unit-duplicate",
                   f"同一 beat 被拆入多个生成单元: {duplicated}")
        return _inspection_result(errors, warnings, shots=len(shot_list), units=len(unit_list))

    # A composition reference is optional.  If present in the new workflow it
    # must be traceable to the shot card and scene map; old storyboard_source
    # records remain readable only for backwards compatibility.
    for asset in asset_list:
        if not isinstance(asset, dict) or asset.get("kind") != "composition-reference":
            continue
        tag = asset.get("tag", "<unknown>")
        source = asset.get("composition_source")
        legacy_source = asset.get("storyboard_source")
        if strict_v2 and legacy_source is not None:
            _issue(errors, "ERROR", "v2-storyboard-source-forbidden",
                   f"{tag}: v2 构图参考图不得声明 storyboard_source")
        if isinstance(source, dict):
            required_source = (
                "type", "shot_id", "scene_id", "basis", "canonical_asset_ids",
            )
            missing_source = [field for field in required_source
                              if field not in source or source.get(field) in (None, "")]
            if missing_source:
                _issue(errors, "ERROR", "composition-shot-card-source-incomplete",
                       f"{tag}: 镜头构图参考图来源字段不完整: {missing_source}")
                continue
            if source.get("type") != "shot_card":
                _issue(errors, "ERROR", "composition-source-type-invalid",
                       f"{tag}: 新式构图参考图来源 type 必须是 shot_card")
            if asset.get("shot_id") != source.get("shot_id"):
                _issue(errors, "ERROR", "composition-shot-card-shot-drift",
                       f"{tag}: 构图镜头 {asset.get('shot_id')} 与 shot_card 来源 {source.get('shot_id')} 不一致")
            source_shot = shot_by_id.get(source.get("shot_id"))
            if source_shot is None:
                _issue(errors, "ERROR", "composition-shot-card-unknown",
                       f"{tag}: 来源 shot_card 不存在: {source.get('shot_id')}")
            elif source.get("scene_id") != source_shot.get("scene_id"):
                _issue(errors, "ERROR", "composition-scene-drift",
                       f"{tag}: 来源 scene_id 与 shot_card 不一致")
            basis = source.get("basis")
            required_basis = {"scene_map", "shot_card", "canonical-assets"}
            if not isinstance(basis, list) or not required_basis <= set(basis):
                _issue(errors, "ERROR", "composition-shot-card-basis-incomplete",
                       f"{tag}: 构图参考图 basis 必须包含 shot_card、scene_map 和 canonical-assets")
            canonical_ids = source.get("canonical_asset_ids")
            if not isinstance(canonical_ids, list) or not canonical_ids:
                _issue(errors, "ERROR", "composition-canonical-source-missing",
                       f"{tag}: 构图参考图必须登记实际使用的 canonical_asset_ids")
            else:
                known_asset_ids = {
                    item.get("asset_id") for item in asset_list
                    if isinstance(item, dict) and item.get("kind") not in {
                        "composition-reference", "tailframe", "video",
                        "generated-video", "video-output",
                    } | NON_PRODUCTION_IMAGE_KINDS
                }
                unknown_canonical = set(canonical_ids) - known_asset_ids
                if unknown_canonical:
                    _issue(errors, "ERROR", "composition-canonical-source-unknown",
                           f"{tag}: canonical 来源资产不存在: {sorted(unknown_canonical)}")
            continue

        if strict_v2:
            _issue(errors, "ERROR", "composition-shot-card-source-missing",
                   f"{tag}: v2 构图参考图缺少 composition_source")
            continue

        # Legacy records are checked as before, but their presence no longer
        # makes a storyboard registry mandatory for the whole workflow.
        source = legacy_source
        if not isinstance(source, dict):
            _issue(errors, "ERROR", "composition-storyboard-source-missing",
                   f"{tag}: 按需构图参考图缺少 shot_card/scene_map 来源记录")
            continue
        required_source = ("storyboard_sheet_id", "panel_id", "version", "confirmation_status")
        missing_source = [field for field in required_source
                          if field not in source or source.get(field) in (None, "")]
        if missing_source:
            _issue(errors, "ERROR", "composition-storyboard-source-incomplete",
                   f"{tag}: 旧式导演分镜来源字段不完整: {missing_source}")
        elif source.get("confirmation_status") not in PASS_STORYBOARD_STATES:
            _issue(errors, "ERROR", "composition-storyboard-not-approved",
                   f"{tag}: 旧式来源分格尚未导演/用户确认，当前状态={source.get('confirmation_status')}")
        sheet = storyboard_by_id.get(source.get("storyboard_sheet_id"))
        if sheet is None:
            _issue(errors, "ERROR", "composition-storyboard-sheet-unknown",
                   f"{tag}: 旧式来源分镜板不存在: {source.get('storyboard_sheet_id')}")
            continue
        if source.get("version") != sheet.get("version"):
            _issue(errors, "ERROR", "composition-storyboard-version-drift",
                   f"{tag}: 来源版本 {source.get('version')} 与分镜板 {sheet.get('version')} 不一致")
        panels = {panel.get("panel_id"): panel for panel in _as_list(sheet.get("panels"))
                  if isinstance(panel, dict) and panel.get("panel_id")}
        panel = panels.get(source.get("panel_id"))
        if panel is None:
            _issue(errors, "ERROR", "composition-storyboard-panel-unknown",
                   f"{tag}: 来源分格不存在: {source.get('panel_id')}")
        else:
            if asset.get("shot_id") != panel.get("shot_id"):
                _issue(errors, "ERROR", "composition-storyboard-shot-drift",
                       f"{tag}: 构图镜头 {asset.get('shot_id')} 与来源分格镜头 {panel.get('shot_id')} 不一致")
            registry_status = panel.get("confirmation_status", sheet.get("confirmation_status"))
            if source.get("confirmation_status") != registry_status:
                _issue(errors, "ERROR", "composition-storyboard-confirmation-drift",
                       f"{tag}: 来源声明状态 {source.get('confirmation_status')} 与 registry {registry_status} 不一致")

    for asset in asset_list:
        if not isinstance(asset, dict) or asset.get("kind") != "tailframe":
            continue
        tag = asset.get("tag", "<unknown>")
        provenance = asset.get("tailframe_source")
        if not isinstance(provenance, dict):
            _issue(errors, "ERROR", "tailframe-provenance-missing",
                   f"{tag}: 实际尾帧缺少来源视频、来源单元、截取时间码和帧哈希")
            continue
        required_tail = ("source_unit_id", "source_video_asset_id", "timestamp", "frame_hash")
        missing_tail = [field for field in required_tail
                        if field not in provenance or provenance.get(field) in (None, "")]
        if missing_tail:
            _issue(errors, "ERROR", "tailframe-provenance-incomplete",
                   f"{tag}: 实际尾帧来源字段不完整: {missing_tail}")
        source_unit = provenance.get("source_unit_id")
        source_unit_record = unit_by_id.get(source_unit)
        if source_unit and source_unit_record is None:
            _issue(errors, "ERROR", "tailframe-source-unit-unknown",
                   f"{tag}: 来源单元不存在: {source_unit}")
        elif source_unit_record:
            if source_unit_record.get("production_status") != "USER_ACCEPTED":
                _issue(errors, "ERROR", "tailframe-source-unit-not-user-accepted",
                       f"{tag}: 来源单元 {source_unit} 尚未由用户接受")
            if source_unit_record.get("video_asset_id") != provenance.get("source_video_asset_id"):
                _issue(errors, "ERROR", "tailframe-source-video-unit-drift",
                       f"{tag}: 尾帧来源视频与 {source_unit} 的已验收视频不一致")
        source_video = provenance.get("source_video_asset_id")
        source_video_asset = next(
            (asset for asset in asset_list
             if isinstance(asset, dict)
             and asset.get("asset_id") == source_video),
            None,
        )
        if source_video and source_video_asset is None:
            _issue(errors, "ERROR", "tailframe-source-video-unknown",
                   f"{tag}: 来源视频资产不存在: {source_video}")
        elif source_video_asset and source_video_asset.get("kind") not in {
            "video", "generated-video", "video-output"
        }:
            _issue(errors, "ERROR", "tailframe-source-video-kind",
                   f"{tag}: source_video_asset_id 必须指向视频资产，当前 kind={source_video_asset.get('kind')}")

    storyboard_candidates = _as_list(workflow.get("storyboard_candidates"))
    if strict_v2 and storyboard_candidates:
        _issue(errors, "ERROR", "v2-storyboard-candidates-forbidden",
               "v2 manifest 不使用 storyboard_candidates；构图图需求直接登记在镜头卡资产决策中")
    for candidate in storyboard_candidates:
        if not isinstance(candidate, dict):
            continue
        candidate_id = candidate.get("candidate_id", "<unknown>")
        if candidate.get("tag"):
            _issue(errors, "ERROR", "composition-candidate-has-tag",
                   f"{candidate_id}: 未确认候选不得注册正式 Picture 标签")
        sheet = storyboard_by_id.get(candidate.get("storyboard_sheet_id"))
        if sheet is None:
            _issue(errors, "ERROR", "composition-candidate-sheet-unknown",
                   f"{candidate_id}: 候选来源分镜板不存在")
            continue
        panels = {panel.get("panel_id"): panel for panel in _as_list(sheet.get("panels"))
                  if isinstance(panel, dict) and panel.get("panel_id")}
        if candidate.get("panel_id") not in panels:
            _issue(errors, "ERROR", "composition-candidate-panel-unknown",
                   f"{candidate_id}: 候选来源分格不存在: {candidate.get('panel_id')}")
        if candidate.get("version") != sheet.get("version"):
            _issue(errors, "ERROR", "composition-candidate-version-drift",
                   f"{candidate_id}: 候选版本与分镜板版本不一致")

    # 1. Scene maps were structurally validated before downstream Gate checks.
    if strict_v2:
        dynamic_scene_ids = {
            shot.get("scene_id") for shot in shot_list
            if isinstance(shot, dict)
            and isinstance(shot.get("shot_card"), dict)
            and shot["shot_card"].get("design_mode") in {"dynamic", "mixed"}
        }
        for scene_id in sorted(dynamic_scene_ids):
            scene_map = map_by_scene.get(scene_id, {})
            for field in ("persistent_landmarks", "occupancy_zones", "scale_anchors"):
                if not isinstance(scene_map.get(field), list) or not scene_map.get(field):
                    _issue(errors, "ERROR", "dynamic-scene-control-missing",
                           f"{scene_id}: dynamic/mixed 场景缺少非空 {field}")

            landmark_ids = {
                item.get("anchor_id") for item in _as_list(scene_map.get("persistent_landmarks"))
                if isinstance(item, dict) and item.get("anchor_id")
            }
            zone_ids = {
                item.get("zone_id") for item in _as_list(scene_map.get("occupancy_zones"))
                if isinstance(item, dict) and item.get("zone_id")
            }
            scale_ids = {
                item.get("anchor_id") for item in _as_list(scene_map.get("scale_anchors"))
                if isinstance(item, dict) and item.get("anchor_id")
            }
            for shot in shot_list:
                if not isinstance(shot, dict) or shot.get("scene_id") != scene_id:
                    continue
                card = shot.get("shot_card", {})
                if card.get("design_mode") not in {"dynamic", "mixed"}:
                    continue
                declared = shot.get("spatial_constraints", {})
                for field, expected in (
                    ("persistent_landmarks", landmark_ids),
                    ("occupancy_zone_ids", zone_ids),
                    ("scale_anchor_ids", scale_ids),
                ):
                    actual = set(_as_list(declared.get(field)))
                    if actual != expected:
                        _issue(errors, "ERROR", "dynamic-spatial-control-drift",
                               f"{shot.get('shot_id')}: {field}={sorted(actual)} "
                               f"与 scene_map={sorted(expected)} 不一致")

    # 2. Script coverage: every beat must be in the current batch or explicitly
    # deferred. This catches a polished H3 that silently omits story content.
    coverage = workflow.get("coverage", {})
    included = set(_as_list(coverage.get("included_beat_ids")))
    deferred = set(_as_list(coverage.get("deferred_beat_ids")))
    known_beats = set(beat_by_id)
    if coverage:
        overlap = included & deferred
        if overlap:
            _issue(errors, "ERROR", "coverage-overlap", f"剧本 beat 同时列入当前批次和延期: {sorted(overlap)}")
        unknown = (included | deferred) - known_beats
        if unknown:
            _issue(errors, "ERROR", "coverage-unknown-beat", f"coverage 引用了不存在的 beat: {sorted(unknown)}")
        missing_beats = known_beats - included - deferred
        if missing_beats:
            _issue(errors, "ERROR", "coverage-missing-beat", f"剧本 beat 未决定当前交付还是延期: {sorted(missing_beats)}")
    else:
        _issue(warnings, "WARNING", "coverage-missing", "未提供 coverage，无法确认是否漏掉剧本动作")

    # 3. Each shot must point into the Script IR, a scene map camera, and one
    # delivery unit. No layer may invent a new scene/entity silently.
    seen_unit_shots = set()
    for shot in shot_list:
        if not isinstance(shot, dict):
            _issue(errors, "ERROR", "shot-type", "每个 shot 必须是 JSON 对象")
            continue
        shot_id = shot.get("shot_id", "<unknown>")
        scene_id = shot.get("scene_id")
        unit_id = shot.get("unit_id")
        camera_id = shot.get("camera_id", shot_id)
        if scene_id not in scene_ids:
            _issue(errors, "ERROR", "shot-scene-unknown", f"{shot_id}: scene_id 不在 Script IR 中: {scene_id}")
        if scene_id not in map_by_scene:
            _issue(errors, "ERROR", "shot-scene-map-missing", f"{shot_id}: 没有对应 scene_map: {scene_id}")
        if unit_id not in unit_by_id:
            _issue(errors, "ERROR", "shot-unit-unknown", f"{shot_id}: unit_id 不存在: {unit_id}")
        else:
            seen_unit_shots.add(shot_id)
        scene_map = map_by_scene.get(scene_id)
        if scene_map:
            cameras = _camera_map(scene_map)
            if camera_id not in cameras:
                _issue(errors, "ERROR", "shot-camera-unknown", f"{shot_id}: camera_id 不在 scene_map 中: {camera_id}")
            else:
                camera = cameras[camera_id]
                expected_visible = set(_camera_anchor_ids(camera, "visible_anchors"))
                expected_forbidden = set(_camera_anchor_ids(camera, "forbidden_anchors"))
                declared = shot.get("spatial_constraints", {})
                actual_visible = set(_as_list(declared.get("visible_anchors")))
                actual_forbidden = set(_as_list(declared.get("forbidden_anchors")))
                if actual_visible != expected_visible:
                    _issue(errors, "ERROR", "spatial-constraint-drift",
                           f"{shot_id}: Prompt 可见锚点 {sorted(actual_visible)} 与 scene_map {sorted(expected_visible)} 不一致")
                if actual_forbidden != expected_forbidden:
                    _issue(errors, "ERROR", "spatial-forbidden-drift",
                           f"{shot_id}: Prompt 禁见锚点 {sorted(actual_forbidden)} 与 scene_map {sorted(expected_forbidden)} 不一致")
                expected_state = camera.get("blocking_state_id")
                if declared.get("blocking_state_id") != expected_state:
                    _issue(errors, "ERROR", "spatial-blocking-state-drift",
                           f"{shot_id}: Prompt 调度快照 {declared.get('blocking_state_id')} 与 scene_map {expected_state} 不一致")
                expected_screen = camera.get("screen_positions", {}) or {}
                actual_screen = declared.get("screen_positions", {}) or {}
                if actual_screen != expected_screen:
                    _issue(errors, "ERROR", "spatial-screen-position-drift",
                           f"{shot_id}: Prompt 画面左右 {actual_screen} 与 scene_map {expected_screen} 不一致")
                card = shot.get("shot_card")
                if isinstance(card, dict):
                    card_camera = card.get("camera", {})
                    if isinstance(card_camera, dict):
                        if card_camera.get("position") != camera.get("position"):
                            _issue(errors, "ERROR", "shot-card-camera-position-drift",
                                   f"{shot_id}: shot_card 机位坐标与 scene_map 不一致")
                        if card_camera.get("axis_side") != camera.get("side"):
                            _issue(errors, "ERROR", "shot-card-camera-side-drift",
                                   f"{shot_id}: shot_card 轴线侧 {card_camera.get('axis_side')} "
                                   f"与 scene_map {camera.get('side')} 不一致")
                    staging_actors = card.get("staging", {}).get("actors", {})
                    if isinstance(staging_actors, dict):
                        card_screen = {
                            entity_id: state.get("screen_position")
                            for entity_id, state in staging_actors.items()
                            if isinstance(state, dict) and state.get("screen_position")
                        }
                        expected_actor_screen = {
                            entity_id: position for entity_id, position in expected_screen.items()
                            if entity_id in set(_as_list(shot.get("characters")))
                        }
                        if expected_actor_screen and card_screen != expected_actor_screen:
                            _issue(errors, "ERROR", "shot-card-screen-position-drift",
                                   f"{shot_id}: shot_card 人物画面位置 {card_screen} "
                                   f"与 scene_map {expected_actor_screen} 不一致")
                    fixed_anchor_ids = _ids(_as_list(scene_map.get("fixed_anchors")), "anchor_id")
                    required_background = expected_visible & fixed_anchor_ids
                    declared_background = set(_as_list(card.get("composition", {}).get("background")))
                    if not required_background <= declared_background:
                        _issue(errors, "ERROR", "shot-card-background-anchor-missing",
                               f"{shot_id}: shot_card 构图漏掉 scene_map 必见固定锚点 "
                               f"{sorted(required_background - declared_background)}")
                derived = spatial.derive_shot_constraints(scene_map).get(camera_id, {})
                if declared.get("orientation") != derived.get("facing"):
                    _issue(errors, "ERROR", "spatial-orientation-drift",
                           f"{shot_id}: Prompt 朝向 {declared.get('orientation')} 与 scene_map 推导值 {derived.get('facing')} 不一致")

        beat_ids = _as_list(shot.get("beat_ids"))
        if not beat_ids:
            _issue(errors, "ERROR", "shot-beat-missing", f"{shot_id}: 没有绑定剧本 beat")
        beat_entities = set()
        for beat_id in beat_ids:
            beat = beat_by_id.get(beat_id)
            if not beat:
                _issue(errors, "ERROR", "shot-beat-unknown", f"{shot_id}: beat 不存在: {beat_id}")
                continue
            if beat.get("scene_id") != scene_id:
                _issue(errors, "ERROR", "shot-beat-scene-drift", f"{shot_id}: beat {beat_id} 属于 {beat.get('scene_id')}，不是 {scene_id}")
            beat_entities |= set(_as_list(beat.get("characters")))
            beat_entities |= set(_as_list(beat.get("props")))
        shot_characters = set(_as_list(shot.get("characters")))
        shot_props = set(_as_list(shot.get("props")))
        unknown_entities = (shot_characters - character_ids) | (shot_props - prop_ids)
        if unknown_entities:
            _issue(errors, "ERROR", "shot-entity-unknown", f"{shot_id}: 引用了不存在的角色/道具: {sorted(unknown_entities)}")
        if beat_entities and not (shot_characters | shot_props) <= beat_entities:
            extra = (shot_characters | shot_props) - beat_entities
            _issue(errors, "ERROR", "shot-entity-beat-drift", f"{shot_id}: 镜头实体不在绑定 beat 中: {sorted(extra)}")
        if not shot.get("language_card_shot_id"):
            _issue(errors, "ERROR", "shot-language-card-missing", f"{shot_id}: 未绑定镜头语言卡 ID")
        elif shot["language_card_shot_id"] != shot_id:
            _issue(errors, "ERROR", "shot-language-card-drift", f"{shot_id}: 镜头语言卡绑定为 {shot['language_card_shot_id']}")

    # 4. Unit ordering, reference accounting, and visual readiness.
    for unit in unit_list:
        if not isinstance(unit, dict):
            continue
        unit_id = unit.get("unit_id", "<unknown>")
        _validate_unit_plan(
            unit, shot_by_id, strict_v2, errors, _max_unit_duration(workflow))
        unit_shots = _as_list(unit.get("shot_ids"))
        if not unit_shots:
            _issue(errors, "ERROR", "unit-shots-missing", f"{unit_id}: 没有镜头")
        missing = [shot_id for shot_id in unit_shots if shot_id not in shot_by_id]
        if missing:
            _issue(errors, "ERROR", "unit-shot-unknown", f"{unit_id}: 引用了不存在的镜头: {missing}")
        wrong_unit = [shot_id for shot_id in unit_shots
                      if shot_id in shot_by_id and shot_by_id[shot_id].get("unit_id") != unit_id]
        if wrong_unit:
            _issue(errors, "ERROR", "unit-shot-drift", f"{unit_id}: 镜头的 unit_id 不一致: {wrong_unit}")
        h3_numbers = _as_list(unit.get("h3_shot_numbers"))
        planned_numbers = [shot_by_id[shot_id].get("h3_shot_number") for shot_id in unit_shots if shot_id in shot_by_id]
        if planned_numbers != h3_numbers:
            _issue(errors, "ERROR", "unit-h3-shot-drift", f"{unit_id}: H3 镜号 {h3_numbers} 与镜头计划 {planned_numbers} 不一致")

        refs = unit.get("references", {})
        required = set(_as_list(refs.get("required")))
        optional = set(_as_list(refs.get("optional")))
        forbidden = set(_as_list(refs.get("forbidden")))
        raw_bindings = unit.get("input_bindings")
        bound_asset_by_slot = {}
        if raw_bindings is not None:
            if not isinstance(raw_bindings, list):
                _issue(errors, "ERROR", "input-bindings-type",
                       f"{unit_id}: input_bindings 必须是数组")
            else:
                seen_asset_ids = set()
                for binding_index, binding in enumerate(raw_bindings, 1):
                    if not isinstance(binding, dict) or not binding.get("slot") or not binding.get("asset_id"):
                        _issue(errors, "ERROR", "input-binding-incomplete",
                               f"{unit_id}: 每项 input_bindings 必须包含 slot 与 asset_id")
                        continue
                    if coverage_required and _state_at_least(state, "ASSETS_READY"):
                        if binding.get("order") != binding_index:
                            _issue(errors, "ERROR", "input-binding-order-drift",
                                   f"{unit_id}: input_bindings[{binding_index}] 的 order 必须为 {binding_index}")
                        if binding.get("media_type") not in {"image", "audio", "video"}:
                            _issue(errors, "ERROR", "input-binding-media-type-invalid",
                                   f"{unit_id}: input_bindings[{binding_index}] 必须声明 image/audio/video")
                    slot, asset_id = binding["slot"], binding["asset_id"]
                    if slot in bound_asset_by_slot:
                        _issue(errors, "ERROR", "input-binding-slot-duplicate",
                               f"{unit_id}: 输入槽位重复绑定: {slot}")
                        continue
                    asset = asset_by_id.get(asset_id)
                    if asset is None:
                        _issue(errors, "ERROR", "input-binding-asset-unknown",
                               f"{unit_id}: {slot} 绑定了未登记资产 {asset_id}")
                    elif binding.get("media_type") == "image" and coverage_required \
                            and _state_at_least(state, "ASSETS_READY"):
                        contract = asset.get("asset_contract")
                        if not isinstance(contract, dict):
                            _issue(errors, "ERROR", "input-asset-contract-missing",
                                   f"{unit_id}: 图片资产 {asset_id} 缺少 asset_contract")
                        elif contract.get("upload_policy", {}).get("mode") == "never-video-input":
                            _issue(errors, "ERROR", "input-asset-upload-forbidden",
                                   f"{unit_id}: 图片资产 {asset_id} 的契约禁止进入视频输入")
                    if asset_id in seen_asset_ids:
                        _issue(errors, "ERROR", "input-binding-asset-duplicate",
                               f"{unit_id}: 同一资产不得重复占用上传顺序: {asset_id}")
                    seen_asset_ids.add(asset_id)
                    bound_asset_by_slot[slot] = asset
                subject_numbers = sorted(
                    int(match.group(1))
                    for slot in bound_asset_by_slot
                    if (match := re.fullmatch(r"<Subject\s+(\d+)>", slot))
                )
                if subject_numbers and subject_numbers != list(range(1, len(subject_numbers) + 1)):
                    _issue(errors, "ERROR", "input-subject-slots-noncontiguous",
                           f"{unit_id}: 本次请求的 Subject 槽位必须从1连续编号，当前={subject_numbers}")
                _validate_lineage_uploads(unit_id, bound_asset_by_slot, errors)
        if (required | optional) & forbidden:
            _issue(errors, "ERROR", "reference-conflict", f"{unit_id}: 参考图同时被选择和禁止: {sorted((required | optional) & forbidden)}")
        selected = required | optional
        available_slots = set(bound_asset_by_slot) if raw_bindings is not None else set(asset_by_tag)
        undefined = selected - available_slots
        if undefined:
            _issue(errors, "ERROR", "reference-asset-unknown", f"{unit_id}: 参考图未登记资产: {sorted(undefined)}")
        forbidden_asset_ids = set(_as_list(unit.get("forbidden_asset_ids")))
        bound_asset_ids = {
            asset.get("asset_id") for asset in bound_asset_by_slot.values() if isinstance(asset, dict)
        }
        if forbidden_asset_ids & bound_asset_ids:
            _issue(errors, "ERROR", "forbidden-asset-bound",
                   f"{unit_id}: 禁止资产仍被绑定到输入槽位: {sorted(forbidden_asset_ids & bound_asset_ids)}")
        video_inputs = set(_as_list(unit.get("video_inputs")))
        review = workflow.get("director_review_artifact")
        review_paths = {
            review.get("path"),
            review.get("asset_tag"),
        } if isinstance(review, dict) else set()
        for tag in video_inputs:
            asset = bound_asset_by_slot.get(tag) if raw_bindings is not None else asset_by_tag.get(tag)
            asset_kind = asset.get("kind") if isinstance(asset, dict) else None
            if (
                tag in review_paths
                or asset_kind in NON_PRODUCTION_IMAGE_KINDS
            ):
                _issue(errors, "ERROR", "director-review-video-input",
                       f"{unit_id}: 导演总版/分镜规划图 {tag} 不得作为视频模型输入")
            if asset is None:
                _issue(errors, "ERROR", "video-input-unknown", f"{unit_id}: 视频输入未登记资产: {tag}")
            elif tag in forbidden:
                _issue(errors, "ERROR", "forbidden-video-input", f"{unit_id}: 禁止混用的 {tag} 被送入视频模型")
            elif asset.get("visual_state") not in ({"用户确认"} if strict_v2 else PASS_VISUAL_STATES):
                _issue(errors, "ERROR", "video-input-not-approved", f"{unit_id}: {tag} 尚未由用户确认")
        for shot_id in unit_shots:
            if shot_id not in shot_by_id:
                continue
            shot_refs = set(_as_list(shot_by_id[shot_id].get("references")))
            if not shot_refs <= selected:
                _issue(errors, "ERROR", "shot-reference-not-accounted", f"{shot_id}: 镜头参考图未列入单元清单: {sorted(shot_refs - selected)}")

        continuity = unit.get("continuity", {})
        if not isinstance(continuity.get("in"), dict) or not isinstance(continuity.get("out"), dict):
            _issue(errors, "ERROR", "unit-continuity-missing", f"{unit_id}: continuity.in/out 必须是结构化状态对象")
        elif unit.get("unit_order", 0) == 1 and continuity.get("actual_tail_frame"):
            _issue(errors, "ERROR", "first-unit-tail-frame", f"{unit_id}: 首单元不能伪造上一段实际尾帧")

    if strict_v2:
        unit_beat_owners = {}
        for unit in unit_list:
            if not isinstance(unit, dict):
                continue
            for beat_id in _as_list(unit.get("beat_ids")):
                unit_beat_owners.setdefault(beat_id, []).append(unit.get("unit_id"))
        planned_beats = set(unit_beat_owners)
        if planned_beats != included:
            _issue(errors, "ERROR", "unit-coverage-drift",
                   f"unit beat 覆盖 {sorted(planned_beats)} 与当前批次 included {sorted(included)} 不一致")
        duplicated = {beat_id: owners for beat_id, owners in unit_beat_owners.items()
                      if len(owners) > 1}
        if duplicated:
            _issue(errors, "ERROR", "unit-beat-cross-unit-duplicate",
                   f"同一 beat 被拆入多个生成单元: {duplicated}")

    if coverage_required:
        for index, unit in enumerate(ordered_units):
            unit_id = unit.get("unit_id", "<unknown>")
            production_status = _validate_unit_production(unit, asset_by_id, errors)
            if production_status not in UNIT_PRODUCTION_STATES:
                continue

            if index > 0 and production_status != "PLANNED_BLOCKED":
                previous = ordered_units[index - 1]
                if previous.get("production_status") != "USER_ACCEPTED":
                    _issue(errors, "ERROR", "unit-unlocked-without-user-acceptance",
                           f"{unit_id}: 前一单元 {previous.get('unit_id')} 尚未由用户接受，"
                           "当前单元必须保持 PLANNED_BLOCKED")

    # 5. Adjacent unit state handoff. A transition must be explicit; otherwise
    # the next unit cannot silently reset space or object ownership.
    for previous, current in zip(ordered_units, ordered_units[1:]):
        continuity = current.get("continuity", {})
        transition_type = current.get("transition_type") or continuity.get("transition_type")
        if transition_type in INDEPENDENT_TRANSITIONS:
            continue
        if transition_type is None and (current.get("transition") is True or continuity.get("transition") is True):
            _issue(warnings, "WARNING", "transition-type-missing",
                   f"{current.get('unit_id')}: 使用未类型化 transition=true；请区分 continuous_space 与 independent_start")
            continue
        previous_out = previous.get("continuity", {}).get("out")
        current_in = current.get("continuity", {}).get("in")
        if isinstance(previous_out, dict) and isinstance(current_in, dict) and not _state_equal(previous_out, current_in):
            _issue(errors, "ERROR", "continuity-handoff-drift",
                   f"{previous.get('unit_id')} 尾状态与 {current.get('unit_id')} 首状态不一致；必须补交接动作或显式时空转换")

    # 6. Delivery scope is a user-facing contract. H3-only output must not
    # accidentally require or emit internal image artifacts.
    delivery = workflow.get("delivery", {})
    scope = delivery.get("scope")
    emitted = set(_as_list(delivery.get("emitted")))
    if scope not in {"h3-only", "full"}:
        _issue(errors, "ERROR", "delivery-scope-invalid", "delivery.scope 必须是 h3-only 或 full")
    if scope == "h3-only":
        leaked = emitted & IMAGE_ONLY_DELIVERABLES
        if leaked:
            _issue(errors, "ERROR", "h3-only-scope-leak", f"H3-only 交付泄漏内部图片产物: {sorted(leaked)}")
    if scope == "full" and _state_at_least(state, "PROMPTS_VALIDATED") and "h3" not in emitted:
        _issue(errors, "ERROR", "full-delivery-h3-missing", "完整交付缺少 h3 成品")
    if delivery.get("mode") == "generated-video" and workflow.get("workflow_state") == "DELIVERED" \
            and "video" not in emitted:
        _issue(errors, "ERROR", "generated-video-delivery-missing",
               "generated-video 模式进入 DELIVERED 时 emitted 必须包含 video")

    if not workflow.get("visual_review"):
        _issue(warnings, "WARNING", "visual-review-missing", "未提供 visual_review；空间计划通过不等于生成图片通过")
    elif not isinstance(workflow.get("visual_review"), list):
        _issue(errors, "ERROR", "visual-review-type", "visual_review 必须是列表")
    else:
        reviewed_assets = {
            item.get("asset_id"): item.get("status")
            for item in workflow["visual_review"]
            if isinstance(item, dict) and item.get("asset_id")
        }
        for asset in asset_list:
            if not isinstance(asset, dict) or not asset.get("tag"):
                continue
            review_id = asset.get("asset_id")
            if review_id and review_id not in reviewed_assets:
                _issue(warnings, "WARNING", "asset-review-missing",
                       f"{asset['tag']}: manifest 声明了 asset_id {review_id}，但 visual_review 未登记")
            if review_id and review_id in reviewed_assets and asset.get("visual_state") != reviewed_assets[review_id]:
                _issue(errors, "ERROR", "asset-review-state-drift",
                       f"{asset['tag']}: visual_state={asset.get('visual_state')} 与 visual_review={reviewed_assets[review_id]} 不一致")

    return _inspection_result(
        errors, warnings, shots=len(shot_list), units=len(unit_list), assets=len(asset_list))
