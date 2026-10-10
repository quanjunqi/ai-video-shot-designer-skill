"""Validate optional visual review artifacts and legacy storyboards."""

from __future__ import annotations

from shotdesigner.findings import Finding


PASS_STORYBOARD_STATES = {"导演确认", "用户确认"}
REVIEW_PENDING_STATES = {"待审阅", "待确认", "部分受阻-待实际尾帧"}
PROFESSIONAL_STORYBOARD_FORMAT = "professional-state-board-v2"
PROFESSIONAL_PANEL_FIELDS = (
    "panel_id", "shot_id", "scene_id", "state_role", "frame_time", "duration",
    "shot_size", "lens", "camera", "camera_motion", "actor_motion",
    "action", "continuity_in", "continuity_out", "background_continuity", "sound",
    "confirmation_status", "visibility_transitions",
)
ANCHOR_VISIBILITY_FIELDS = ("visible", "occluded", "offscreen", "forbidden")


def _add(findings, severity, code, message):
    findings.append(Finding(code=code, severity=severity, message=message))


def _as_list(value):
    return value if isinstance(value, list) else []


def validate_director_review(
        workflow, artifact_root, shot_by_id, strict_v2, resolve_artifact, sha256):
    findings = []
    """Validate an optional director review sheet without making it a fact source."""
    review = workflow.get("director_review_artifact")
    if review is None:
        return findings
    if not isinstance(review, dict):
        _add(findings, "ERROR", "director-review-artifact-type",
               "director_review_artifact 必须是对象")
        return findings

    required = ("path", "sha256", "covered_shot_ids", "review_status")
    missing = [field for field in required if review.get(field) in (None, "")]
    if missing:
        _add(findings, "ERROR", "director-review-artifact-incomplete",
               f"director_review_artifact 缺少 {missing}")
    covered = review.get("covered_shot_ids")
    if not isinstance(covered, list):
        _add(findings, "ERROR", "director-review-coverage-type",
               "director_review_artifact.covered_shot_ids 必须是数组")
        covered = []
    if all(isinstance(item, str) for item in covered) and len(covered) != len(set(covered)):
        _add(findings, "ERROR", "director-review-coverage-duplicate",
               "director_review_artifact.covered_shot_ids 不能重复")
    unknown = {item for item in covered if isinstance(item, str)} - set(shot_by_id)
    invalid = [item for item in covered if not isinstance(item, str)]
    if invalid:
        _add(findings, "ERROR", "director-review-coverage-id-type",
               "director_review_artifact.covered_shot_ids 只能包含字符串 shot_id")
    if unknown:
        _add(findings, "ERROR", "director-review-coverage-unknown",
               f"总版审阅记录引用未知镜头: {sorted(unknown)}")
    coverage_status = review.get("coverage_status", "complete")
    if coverage_status not in {"complete", "partial"}:
        _add(findings, "ERROR", "director-review-coverage-status",
               "director_review_artifact.coverage_status 必须是 complete 或 partial")
    elif coverage_status == "complete" and set(covered) != set(shot_by_id):
        _add(findings, "ERROR", "director-review-coverage-incomplete",
               "总版标记为 complete，但没有覆盖全部镜头卡")
    elif coverage_status == "partial":
        _add(findings, "WARNING", "director-review-partial",
               "导演总版只覆盖部分镜头；未覆盖内容仍以镜头卡和 H3 为准")

    status = review.get("review_status")
    if status not in PASS_STORYBOARD_STATES | REVIEW_PENDING_STATES:
        _add(findings, "ERROR", "director-review-status-invalid",
               f"总版审阅状态不受控: {status}")

    shot_reviews = review.get("shot_reviews")
    if shot_reviews is None and strict_v2 and status in PASS_STORYBOARD_STATES:
        _add(findings, "ERROR", "director-review-shot-reviews-missing",
               "v2 总版标记为已确认时，必须逐镜记录 script/staging/camera/action/prompt 审阅结论")
    elif shot_reviews is not None:
        if not isinstance(shot_reviews, list):
            _add(findings, "ERROR", "director-review-shot-reviews-type",
                   "director_review_artifact.shot_reviews 必须是数组")
        else:
            review_fields = (
                "shot_id", "script_coverage", "staging_match", "camera_match",
                "action_match", "prompt_match", "issues", "decision",
            )
            result_fields = (
                "script_coverage", "staging_match", "camera_match",
                "action_match", "prompt_match",
            )
            reviewed_ids = []
            for item in shot_reviews:
                if not isinstance(item, dict):
                    _add(findings, "ERROR", "director-review-shot-review-type",
                           "director_review_artifact.shot_reviews 每项必须是对象")
                    continue
                missing_review = [field for field in review_fields if field not in item]
                shot_id = item.get("shot_id", "<unknown>")
                if missing_review:
                    _add(findings, "ERROR", "director-review-shot-review-incomplete",
                           f"{shot_id}: 逐镜审阅记录缺少 {missing_review}")
                if shot_id in shot_by_id:
                    reviewed_ids.append(shot_id)
                elif shot_id != "<unknown>":
                    _add(findings, "ERROR", "director-review-shot-review-unknown",
                           f"逐镜审阅记录引用未知镜头: {shot_id}")
                for field in result_fields:
                    if item.get(field) not in {"match", "mismatch", "not_assessable"}:
                        _add(findings, "ERROR", "director-review-result-invalid",
                               f"{shot_id}: {field} 必须是 match、mismatch 或 not_assessable")
                if not isinstance(item.get("issues"), list):
                    _add(findings, "ERROR", "director-review-issues-type",
                           f"{shot_id}: issues 必须是数组")
                if item.get("decision") not in {"accept", "revise", "blocked"}:
                    _add(findings, "ERROR", "director-review-decision-invalid",
                           f"{shot_id}: decision 必须是 accept、revise 或 blocked")
                if item.get("decision") == "accept" and any(
                    item.get(field) != "match" for field in result_fields
                ):
                    _add(findings, "ERROR", "director-review-accepts-mismatch",
                           f"{shot_id}: 存在 mismatch/not_assessable 时不能 decision=accept")
            if len(reviewed_ids) != len(set(reviewed_ids)):
                _add(findings, "ERROR", "director-review-shot-review-duplicate",
                       "director_review_artifact.shot_reviews 存在重复 shot_id")
            if status in PASS_STORYBOARD_STATES and set(reviewed_ids) != set(covered):
                _add(findings, "ERROR", "director-review-shot-review-coverage-drift",
                       "已确认总版的 shot_reviews 必须与 covered_shot_ids 一一对应")

    if artifact_root is None:
        return findings
    raw_path = review.get("path")
    expected_hash = review.get("sha256")
    if not raw_path or not expected_hash:
        return findings
    try:
        path = resolve_artifact(artifact_root, raw_path)
    except (TypeError, ValueError) as exc:
        _add(findings, "ERROR", "director-review-artifact-path-invalid",
             f"导演总版审阅文件路径非法: {exc}")
        return findings
    if not path.is_file():
        _add(findings, "ERROR", "director-review-artifact-not-found",
               f"导演总版审阅文件不存在: {path}")
        return findings
    actual_hash = sha256(path)
    if actual_hash != expected_hash:
        _add(findings, "ERROR", "director-review-artifact-hash-drift",
               f"导演总版 hash 漂移: manifest={expected_hash}, actual={actual_hash}")
    return findings


def validate_storyboards(storyboards, shot_by_id, unit_by_id, map_by_scene):
    findings = []
    _add(findings, "WARNING", "legacy-storyboard-registry",
           "发现旧式 storyboards/panels；它们只作历史审阅兼容，不是新工作流的生产事实源")
    sheet_ids = [sheet.get("storyboard_sheet_id") for sheet in storyboards if isinstance(sheet, dict)]
    if len(sheet_ids) != len(set(sheet_ids)):
        _add(findings, "ERROR", "storyboard-sheet-id-duplicate", "storyboards 存在重复 storyboard_sheet_id")
    for sheet in storyboards:
        if not isinstance(sheet, dict):
            _add(findings, "ERROR", "storyboard-sheet-type", "storyboards 每项必须是 JSON 对象")
            continue
        sheet_id = sheet.get("storyboard_sheet_id", "<unknown>")
        unit_id = sheet.get("unit_id")
        unit = unit_by_id.get(unit_id)
        if unit is None:
            _add(findings, "ERROR", "storyboard-unit-unknown", f"{sheet_id}: unit_id 不存在: {unit_id}")
            continue
        panels = _as_list(sheet.get("panels"))
        if not panels:
            _add(findings, "ERROR", "storyboard-panels-missing", f"{sheet_id}: 没有状态格")
            continue
        panel_ids = [panel.get("panel_id") for panel in panels if isinstance(panel, dict)]
        if len(panel_ids) != len(panels) or len(panel_ids) != len(set(panel_ids)):
            _add(findings, "ERROR", "storyboard-panel-id-duplicate", f"{sheet_id}: panel_id 缺失或重复")
        actual_order = []
        for panel in panels:
            if not isinstance(panel, dict):
                _add(findings, "ERROR", "storyboard-panel-type", f"{sheet_id}: 状态格必须是 JSON 对象")
                continue
            shot_id = panel.get("shot_id")
            shot = shot_by_id.get(shot_id)
            if shot is None:
                _add(findings, "ERROR", "storyboard-panel-shot-unknown", f"{sheet_id}: 状态格引用未知镜头 {shot_id}")
            elif shot.get("unit_id") != unit_id:
                _add(findings, "ERROR", "storyboard-panel-cross-unit", f"{sheet_id}: 状态格 {panel.get('panel_id')} 跨单元引用 {shot_id}")
            if not actual_order or actual_order[-1] != shot_id:
                actual_order.append(shot_id)
        expected_order = _as_list(unit.get("shot_ids"))
        if actual_order != expected_order:
            _add(findings, "ERROR", "storyboard-shot-coverage-drift",
                   f"{sheet_id}: 状态格镜头顺序/覆盖 {actual_order} 与单元 {expected_order} 不一致")

        if sheet.get("format") != PROFESSIONAL_STORYBOARD_FORMAT:
            _add(findings, "WARNING", "storyboard-legacy-format",
                   f"{sheet_id}: 尚未使用 {PROFESSIONAL_STORYBOARD_FORMAT}，不能宣称为导演交付级状态板")
            continue
        for field in ("version", "confirmation_status", "render_profile", "scene_anchor_sets"):
            if not sheet.get(field):
                _add(findings, "ERROR", "storyboard-professional-field-missing", f"{sheet_id}: 缺少 {field}")
        scene_anchor_sets = sheet.get("scene_anchor_sets")
        if not isinstance(scene_anchor_sets, dict):
            scene_anchor_sets = {}
        for scene_id, declared_anchors in scene_anchor_sets.items():
            scene_map = map_by_scene.get(scene_id)
            if scene_map is None:
                _add(findings, "ERROR", "storyboard-anchor-scene-unknown",
                       f"{sheet_id}: scene_anchor_sets 引用未知场景 {scene_id}")
                continue
            expected_anchors = {
                anchor.get("anchor_id") for anchor in _as_list(scene_map.get("fixed_anchors"))
                if isinstance(anchor, dict) and anchor.get("anchor_id")
            }
            actual_anchors = set(_as_list(declared_anchors))
            if actual_anchors != expected_anchors:
                _add(findings, "ERROR", "storyboard-anchor-set-drift",
                       f"{sheet_id}/{scene_id}: 连续性锚点与 scene_map 不一致；"
                       f"缺少={sorted(expected_anchors - actual_anchors)}，未知={sorted(actual_anchors - expected_anchors)}")
        if not 2 <= len(panels) <= 12:
            _add(findings, "ERROR", "storyboard-panel-count", f"{sheet_id}: 专业单元板必须有 2-12 个动作状态格")
        visible_by_shot = {}
        panels_by_shot = {}
        previous_visibility_by_shot = {}
        previous_panel_by_shot = {}
        for panel in panels:
            if not isinstance(panel, dict):
                continue
            missing = [field for field in PROFESSIONAL_PANEL_FIELDS if panel.get(field) in (None, "")]
            if missing:
                _add(findings, "ERROR", "storyboard-panel-field-missing",
                       f"{sheet_id}/{panel.get('panel_id', '<unknown>')}: 缺少 {missing}")
            panel_id = panel.get("panel_id", "<unknown>")
            scene_id = panel.get("scene_id")
            shot = shot_by_id.get(panel.get("shot_id"), {})
            if scene_id != shot.get("scene_id"):
                _add(findings, "ERROR", "storyboard-panel-scene-drift",
                       f"{sheet_id}/{panel_id}: scene_id={scene_id} 与镜头场景 {shot.get('scene_id')} 不一致")
            expected_anchors = set(_as_list(scene_anchor_sets.get(scene_id)))
            visibility = panel.get("anchor_visibility")
            if not isinstance(visibility, dict):
                _add(findings, "ERROR", "storyboard-anchor-visibility-missing",
                       f"{sheet_id}/{panel_id}: 缺少 anchor_visibility")
            else:
                buckets = {}
                for field in ANCHOR_VISIBILITY_FIELDS:
                    values = visibility.get(field)
                    if not isinstance(values, list):
                        _add(findings, "ERROR", "storyboard-anchor-visibility-type",
                               f"{sheet_id}/{panel_id}: anchor_visibility.{field} 必须是数组")
                        values = []
                    buckets[field] = set(values)
                classified = set().union(*buckets.values())
                overlap = {
                    anchor for anchor in classified
                    if sum(anchor in values for values in buckets.values()) > 1
                }
                if overlap:
                    _add(findings, "ERROR", "storyboard-anchor-overlap",
                           f"{sheet_id}/{panel_id}: 锚点重复分类 {sorted(overlap)}")
                if classified != expected_anchors:
                    _add(findings, "ERROR", "storyboard-anchor-classification-open",
                           f"{sheet_id}/{panel_id}: 锚点分类不闭合；"
                           f"缺少={sorted(expected_anchors - classified)}，未知={sorted(classified - expected_anchors)}")
                shot_id = panel.get("shot_id")
                visible_by_shot.setdefault(shot_id, set()).update(buckets["visible"])
                panels_by_shot.setdefault(shot_id, []).append((panel_id, buckets))
                current_classification = {
                    anchor: field for field, values in buckets.items() for anchor in values
                }
                previous_classification = previous_visibility_by_shot.get(shot_id)
                declared_transitions = set(_as_list(panel.get("visibility_transitions")))
                if previous_classification is None:
                    if declared_transitions:
                        _add(findings, "ERROR", "storyboard-anchor-transition-on-first-panel",
                               f"{sheet_id}/{panel_id}: 镜头首格不能声明显隐变化 {sorted(declared_transitions)}")
                else:
                    changed = {
                        anchor for anchor in expected_anchors
                        if previous_classification.get(anchor) != current_classification.get(anchor)
                    }
                    if changed != declared_transitions:
                        _add(findings, "ERROR", "storyboard-anchor-transition-drift",
                               f"{sheet_id}/{panel_id}: 锚点显隐变化实际={sorted(changed)}，"
                               f"声明={sorted(declared_transitions)}")
                previous_visibility_by_shot[shot_id] = current_classification
                previous_panel = previous_panel_by_shot.get(shot_id)
                if previous_panel is not None and not previous_panel.get("requires_actual_tailframe"):
                    expected_reference = previous_panel.get("panel_id")
                    if panel.get("continuity_reference_panel") != expected_reference:
                        _add(findings, "ERROR", "storyboard-continuity-reference-drift",
                               f"{sheet_id}/{panel_id}: 同镜头后续格必须引用上一格 {expected_reference}")
                previous_panel_by_shot[shot_id] = panel
            if panel.get("requires_actual_tailframe") and panel.get("confirmation_status") != "受阻-待实际尾帧":
                _add(findings, "ERROR", "storyboard-tailframe-gate-drift",
                       f"{sheet_id}/{panel.get('panel_id')}: 缺实际尾帧时必须标为 受阻-待实际尾帧")
        for shot_id, entries in panels_by_shot.items():
            shot = shot_by_id.get(shot_id, {})
            scene_id = shot.get("scene_id")
            expected_anchors = set(_as_list(scene_anchor_sets.get(scene_id)))
            spatial_constraints = shot.get("spatial_constraints", {})
            fixed_visible = set(_as_list(spatial_constraints.get("visible_anchors"))) & expected_anchors
            fixed_forbidden = set(_as_list(spatial_constraints.get("forbidden_anchors"))) & expected_anchors
            if not fixed_visible <= visible_by_shot.get(shot_id, set()):
                _add(findings, "ERROR", "storyboard-required-anchor-not-visible",
                       f"{sheet_id}/{shot_id}: 全部状态格仍未覆盖机位必见锚点: "
                       f"{sorted(fixed_visible - visible_by_shot.get(shot_id, set()))}")
            for panel_id, buckets in entries:
                if not fixed_forbidden <= buckets["forbidden"]:
                    _add(findings, "ERROR", "storyboard-forbidden-anchor-drift",
                           f"{sheet_id}/{panel_id}: 机位禁见锚点未标 forbidden: "
                           f"{sorted(fixed_forbidden - buckets['forbidden'])}")


    return findings
