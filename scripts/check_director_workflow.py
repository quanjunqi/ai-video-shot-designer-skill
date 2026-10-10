#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Check cross-layer consistency of a director workflow manifest.

The existing validators each protect one artifact.  This gate protects the
joins between artifacts: Script IR -> scene map -> shot card -> references ->
unit continuity -> delivery/visual review.  A director review sheet is an
optional visual audit artifact, not a production fact source.  It deliberately
does not pretend to read pixels; generated images still need the visual review
gate.

Usage:
    python3 scripts/check_director_workflow.py workflow.json
    python3 scripts/check_director_workflow.py --json workflow.json

The manifest is an internal, machine-readable planning artifact.  Its stable
entity and shot ids are the bridge that prevents a correct scene map from
silently drifting away from the actual shot card or H3 prompt.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import adapter_config
import workflow_config
from shotdesigner.validators import execution_target as execution_target_validator
from shotdesigner.validators import production_state
from shotdesigner.validators import shot_cards
from shotdesigner.validators import coverage
from shotdesigner.validators import unit_planning
from shotdesigner.validators import script_manifest
from shotdesigner.validators import visual_review
from shotdesigner.validators import spatial_reviews
from shotdesigner.validators import video_production
from shotdesigner.validators import execution_facts
from shotdesigner.validators import text_policy
from shotdesigner.validators import delivery as delivery_validator
from shotdesigner.findings import append_to_legacy
from shotdesigner import workflow_pipeline
from shotdesigner import artifacts as artifact_utils
from shotdesigner import spatial_index


ROOT = Path(__file__).resolve().parents[1]
SPATIAL_SCRIPT = ROOT / "scripts" / "check_spatial_contract.py"
_spatial_spec = importlib.util.spec_from_file_location("check_spatial_contract", SPATIAL_SCRIPT)
if _spatial_spec is None or _spatial_spec.loader is None:  # pragma: no cover
    raise ImportError(f"cannot load {SPATIAL_SCRIPT}")
spatial = importlib.util.module_from_spec(_spatial_spec)
_spatial_spec.loader.exec_module(spatial)


PASS_VISUAL_STATES = {"视觉通过", "用户确认"}
PASS_STORYBOARD_STATES = visual_review.PASS_STORYBOARD_STATES
INDEPENDENT_TRANSITIONS = {"flashback", "independent_start"}
WORKFLOW_CONFIG = workflow_config.state_config()
VERSION_CONFIG = workflow_config.version_config()
WORKFLOW_STATES = workflow_config.states()
UNIT_PRODUCTION_STATES = set(WORKFLOW_CONFIG["unit_production_states"])
IMAGE_ONLY_DELIVERABLES = {
    "assets", "storyboard", "storyboard-panel", "composition-reference",
    "spatial-map", "director-review",
}
NON_PRODUCTION_IMAGE_KINDS = {
    "storyboard", "storyboard-panel", "storyboard-sheet",
    "director-review", "director_review", "planning-map", "camera-map",
}
BASE_REQUIRED_TOP_LEVEL = tuple(WORKFLOW_CONFIG["base_required_fields"])
VIDEO_ASSET_KINDS = video_production.VIDEO_ASSET_KINDS
def _issue(issues, level, code, message):
    issues.append({"level": level, "code": code, "message": message})


def _state_at_least(state, minimum):
    return workflow_config.state_at_least(state, minimum)


def _max_unit_duration(workflow):
    target = workflow.get("execution_target") or {}
    config = adapter_config.resolve(
        target.get("delivery_method"), target.get("target_model"), target.get("api_platform"))
    return adapter_config.limit(config, "unit_duration_seconds", "max", default=15)


def _validate_execution_target(workflow, errors):
    """Compatibility wrapper around the modular execution-target validator."""
    findings, contract = execution_target_validator.validate(workflow, _state_at_least)
    errors.extend(finding.as_dict() for finding in findings)
    return contract


def _inspection_result(errors, warnings, shots=0, units=0, assets=0):
    return {
        "status": "通过" if not errors else "失败",
        "errors": errors,
        "warnings": warnings,
        "counts": {"shots": shots, "units": units, "assets": assets},
    }


def _as_list(value):
    return value if isinstance(value, list) else []


def _ids(items, key="id"):
    return {item.get(key) for item in items if isinstance(item, dict) and item.get(key)}


def _is_number(value):
    return unit_planning.is_number(value)


def _duration_seconds(value):
    return unit_planning.duration_seconds(value)


def _validate_duration_budget(script, strict, errors, warnings):
    append_to_legacy(unit_planning.validate_duration_budget(script, strict), errors, warnings)


def _validate_unit_plan(unit, shot_by_id, strict, errors, max_duration_seconds=15):
    append_to_legacy(
        unit_planning.validate_unit(
            unit, shot_by_id, strict, max_duration_seconds=max_duration_seconds),
        errors,
        [],
    )


def _scene_map_index(scene_maps):
    return spatial_index.scene_maps(scene_maps)


def _scene_map_scene_index(scene_maps):
    return spatial_index.script_scenes(scene_maps)


def _camera_map(scene_map):
    return spatial_index.cameras(scene_map)


def _camera_anchor_ids(camera, field):
    return spatial_index.camera_anchor_ids(camera, field)


def _state_equal(left, right):
    return left == right


def _validate_script_manifest(script, beat_by_id, strict, errors, warnings):
    append_to_legacy(script_manifest.validate(script, beat_by_id, strict), errors, warnings)


def _validate_shot_card(shot, errors, strategy_required=False):
    errors.extend(finding.as_dict() for finding in shot_cards.validate(
        shot, strategy_required=strategy_required))


def _validate_shot_cards(shots, strict, errors, warnings, strategy_required=False):
    append_to_legacy(
        shot_cards.validate_all(shots, strict, strategy_required=strategy_required),
        errors,
        warnings,
    )


def _validate_v22_direction_and_coverage(
        workflow, scene_ids, map_by_scene, shot_list, errors):
    """Compatibility wrapper around the modular coverage validator."""
    errors.extend(finding.as_dict() for finding in coverage.validate(
        workflow,
        scene_ids,
        map_by_scene,
        shot_list,
        _camera_map,
        _camera_anchor_ids,
    ))


def _validate_director_review_artifact(
        workflow, artifact_root, shot_by_id, strict_v2, errors, warnings):
    append_to_legacy(
        visual_review.validate_director_review(
            workflow, artifact_root, shot_by_id, strict_v2, _resolve_artifact, _sha256),
        errors,
        warnings,
    )


def _validate_storyboards(storyboards, shot_by_id, unit_by_id, map_by_scene, errors, warnings):
    append_to_legacy(
        visual_review.validate_storyboards(storyboards, shot_by_id, unit_by_id, map_by_scene),
        errors,
        warnings,
    )


def _sha256(path):
    return artifact_utils.sha256(path)


def _scene_map_signature(scene_map, review_type):
    return spatial.scene_review_signature(scene_map, review_type)


def _validate_spatial_reviews(
        workflow, map_by_scene, artifact_root, required, errors, warnings):
    append_to_legacy(
        spatial_reviews.validate(
            workflow,
            map_by_scene,
            artifact_root,
            required,
            WORKFLOW_STATES,
            _scene_map_signature,
            _resolve_artifact,
            _sha256,
        ),
        errors,
        warnings,
    )


def _resolve_artifact(root, raw_path):
    return artifact_utils.resolve(root, raw_path)


def _asset_derives_from(asset_id, root_id, asset_by_id, seen=None):
    return text_policy.asset_derives_from(asset_id, root_id, asset_by_id, seen)


def _validate_execution_facts(shot, section, strict, errors):
    append_to_legacy(execution_facts.validate(shot, section, strict), errors, [])


def _validate_generated_video_assets(asset_list, unit_by_id, artifact_root, errors):
    append_to_legacy(
        video_production.validate_video_assets(
            asset_list, unit_by_id, artifact_root, _resolve_artifact, _sha256),
        errors,
        [],
    )


def _validate_active_generation(workflow, unit_by_id, asset_by_id, artifact_root, errors):
    append_to_legacy(
        video_production.validate_active_generation(
            workflow, unit_by_id, asset_by_id, artifact_root, _resolve_artifact),
        errors,
        [],
    )


def _text_lock_has_user_proof(text_lock):
    return text_policy.text_lock_has_user_proof(text_lock)


def _validate_text_policy(script, asset_by_id, errors):
    append_to_legacy(text_policy.validate_text_policy(script, asset_by_id), errors, [])


def _validate_lineage_uploads(unit_id, bound_asset_by_slot, errors):
    append_to_legacy(
        text_policy.validate_lineage_uploads(unit_id, bound_asset_by_slot), errors, [])


def _validate_workflow_state(workflow, unit_by_id, errors):
    append_to_legacy(production_state.validate_workflow(workflow, unit_by_id), errors, [])


def _validate_unit_production(unit, asset_by_id, errors):
    findings, status = production_state.validate_unit(
        unit, asset_by_id, UNIT_PRODUCTION_STATES, VIDEO_ASSET_KINDS)
    append_to_legacy(findings, errors, [])
    return status


def _validate_file_artifacts(workflow, artifact_root, errors, warnings):
    append_to_legacy(
        delivery_validator.validate(
            workflow,
            artifact_root,
            _state_at_least,
            _resolve_artifact,
            _sha256,
            _scene_map_index,
        ),
        errors,
        warnings,
    )


def inspect(workflow, artifact_root=None):
    services = workflow_pipeline.PipelineServices(
        BASE_REQUIRED_TOP_LEVEL=BASE_REQUIRED_TOP_LEVEL,
        IMAGE_ONLY_DELIVERABLES=IMAGE_ONLY_DELIVERABLES,
        INDEPENDENT_TRANSITIONS=INDEPENDENT_TRANSITIONS,
        NON_PRODUCTION_IMAGE_KINDS=NON_PRODUCTION_IMAGE_KINDS,
        PASS_STORYBOARD_STATES=PASS_STORYBOARD_STATES,
        PASS_VISUAL_STATES=PASS_VISUAL_STATES,
        UNIT_PRODUCTION_STATES=UNIT_PRODUCTION_STATES,
        VERSION_CONFIG=VERSION_CONFIG,
        WORKFLOW_STATES=WORKFLOW_STATES,
        _as_list=_as_list,
        _camera_anchor_ids=_camera_anchor_ids,
        _camera_map=_camera_map,
        _ids=_ids,
        _inspection_result=_inspection_result,
        _issue=_issue,
        _max_unit_duration=_max_unit_duration,
        _scene_map_index=_scene_map_index,
        _scene_map_scene_index=_scene_map_scene_index,
        _state_at_least=_state_at_least,
        _state_equal=_state_equal,
        _validate_active_generation=_validate_active_generation,
        _validate_director_review_artifact=_validate_director_review_artifact,
        _validate_duration_budget=_validate_duration_budget,
        _validate_execution_target=_validate_execution_target,
        _validate_file_artifacts=_validate_file_artifacts,
        _validate_generated_video_assets=_validate_generated_video_assets,
        _validate_lineage_uploads=_validate_lineage_uploads,
        _validate_script_manifest=_validate_script_manifest,
        _validate_shot_cards=_validate_shot_cards,
        _validate_spatial_reviews=_validate_spatial_reviews,
        _validate_storyboards=_validate_storyboards,
        _validate_text_policy=_validate_text_policy,
        _validate_unit_plan=_validate_unit_plan,
        _validate_unit_production=_validate_unit_production,
        _validate_v22_direction_and_coverage=_validate_v22_direction_and_coverage,
        _validate_workflow_state=_validate_workflow_state,
        spatial=spatial,
    )
    return workflow_pipeline.inspect(workflow, artifact_root, services)


def main(argv=None):
    parser = argparse.ArgumentParser(description="校验 AI 导演工作流的跨层一致性")
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    failed = False
    payload = {}
    for path in args.files:
        try:
            workflow = json.loads(path.read_text(encoding="utf-8"))
            report = inspect(workflow, artifact_root=path.parent)
        except (OSError, json.JSONDecodeError) as exc:
            report = {"status": "失败", "errors": [{"level": "ERROR", "code": "workflow-read", "message": str(exc)}], "warnings": []}
        payload[str(path)] = report
        failed |= report.get("status") == "失败"
        if not args.json:
            print(f"{path}: {report['status']}")
            for item in report.get("errors", []):
                print(f"ERROR [{item.get('code')}]: {item.get('message')}")
            for item in report.get("warnings", []):
                print(f"WARNING [{item.get('code')}]: {item.get('message')}")
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
