"""Validate two-phase spatial review evidence."""

from __future__ import annotations

from shotdesigner.findings import Finding


SPATIAL_REVIEW_FIELDS = (
    "review_id", "review_type", "scene_id", "map_version", "source_scene_map_signature",
    "text_map", "covered_state_ids", "confirmation_status", "confirmed_scope",
    "change_class",
)
SPATIAL_REVIEW_ACCEPTED = {"用户确认", "继承确认"}


def _add(findings, severity, code, message):
    findings.append(Finding(code=code, severity=severity, message=message))


def validate(
        workflow, map_by_scene, artifact_root, required, workflow_states,
        scene_map_signature, resolve_artifact, sha256):
    findings = []
    workflow_state = workflow.get("workflow_state")
    layout_approval = workflow_state in workflow_states[2:]
    camera_approval = workflow_state in workflow_states[3:]
    reviews = workflow.get("spatial_reviews")
    if reviews is None:
        if required and layout_approval:
            _add(findings, "ERROR", "spatial-reviews-missing",
                   "v2.1 必须为每个连续空间登记用户场景空间确认稿")
        return findings
    if not isinstance(reviews, list):
        _add(findings, "ERROR", "spatial-reviews-type", "spatial_reviews 必须是数组")
        return findings

    review_by_id = {
        item.get("review_id"): item for item in reviews
        if isinstance(item, dict) and item.get("review_id")
    }
    if len(review_by_id) != len(reviews):
        _add(findings, "ERROR", "spatial-review-id-duplicate",
               "spatial_reviews 存在缺少或重复的 review_id")
    active_by_key = {}
    for index, review in enumerate(reviews, 1):
        if not isinstance(review, dict):
            _add(findings, "ERROR", "spatial-review-type",
                   f"spatial_reviews[{index}] 必须是对象")
            continue
        review_id = review.get("review_id", f"review-{index}")
        missing = [field for field in SPATIAL_REVIEW_FIELDS
                   if field not in review or review.get(field) in (None, "")]
        if missing:
            _add(findings, "ERROR", "spatial-review-incomplete",
                   f"{review_id}: 缺少 {missing}")
        scene_id = review.get("scene_id")
        review_type = review.get("review_type")
        if review_type not in {"layout", "camera_plan"}:
            _add(findings, "ERROR", "spatial-review-type-invalid",
                   f"{review_id}: review_type 必须是 layout 或 camera_plan")
            continue
        scene_map = map_by_scene.get(scene_id)
        if not scene_map:
            _add(findings, "ERROR", "spatial-review-scene-unknown",
                   f"{review_id}: 引用未知 scene_id={scene_id}")
            continue
        status = review.get("confirmation_status")
        if status not in {"待确认", "用户确认", "继承确认", "已替代"}:
            _add(findings, "ERROR", "spatial-review-status-invalid",
                   f"{review_id}: confirmation_status 非法: {status}")
        if status != "已替代":
            key = (scene_id, review_type)
            if key in active_by_key:
                _add(findings, "ERROR", "spatial-review-active-duplicate",
                       f"{scene_id}/{review_type}: 同类投影只能有一份当前有效确认")
            active_by_key[key] = review

        expected_signature = scene_map_signature(scene_map, review_type)
        if review.get("source_scene_map_signature") != expected_signature:
            _add(findings, "ERROR", "spatial-review-source-drift",
                   f"{review_id}: 场景空间确认稿绑定的 scene_map 签名已失效")
        map_version = (scene_map.get("user_review", {}) or {}).get("map_version", "v1")
        if review.get("map_version") != map_version:
            _add(findings, "ERROR", "spatial-review-version-drift",
                   f"{review_id}: map_version={review.get('map_version')}，scene_map={map_version}")

        state_ids = set((scene_map.get("blocking_states", {}) or {}).keys())
        covered = review.get("covered_state_ids")
        if not isinstance(covered, list) or set(covered) != state_ids:
            _add(findings, "ERROR", "spatial-review-state-coverage",
                   f"{review_id}: covered_state_ids 必须完整覆盖 {sorted(state_ids)}")
        scope = review.get("confirmed_scope")
        expected_scope = ({"layout", "routes", "boundaries", "end_states"}
                          if review_type == "layout"
                          else {"camera_positions", "camera_targets"})
        if not isinstance(scope, list) or set(scope) != expected_scope:
            _add(findings, "ERROR", "spatial-review-scope-incomplete",
                   f"{review_id}: confirmed_scope 必须等于 {sorted(expected_scope)}")

        text_map = review.get("text_map")
        if not isinstance(text_map, dict) or not text_map.get("path") or not text_map.get("sha256"):
            _add(findings, "ERROR", "spatial-review-text-map-incomplete",
                   f"{review_id}: text_map 必须包含 path 和 sha256")
        elif artifact_root is not None:
            try:
                path = resolve_artifact(artifact_root, text_map["path"])
            except (TypeError, ValueError) as exc:
                _add(findings, "ERROR", "spatial-review-text-map-path-invalid",
                     f"{review_id}: 场景空间确认稿路径非法: {exc}")
                continue
            if not path.is_file():
                _add(findings, "ERROR", "spatial-review-text-map-not-found",
                       f"{review_id}: 场景空间确认稿不存在: {path}")
            elif sha256(path) != text_map["sha256"]:
                _add(findings, "ERROR", "spatial-review-text-map-hash-drift",
                       f"{review_id}: 场景空间确认稿文件 hash 漂移")

        change_class = review.get("change_class")
        if change_class not in {"initial", "material", "technical"}:
            _add(findings, "ERROR", "spatial-review-change-class-invalid",
                   f"{review_id}: change_class 必须是 initial/material/technical")
        if status == "用户确认":
            if review.get("confirmed_by") != "user" or not review.get("confirmed_at"):
                _add(findings, "ERROR", "spatial-review-user-proof-missing",
                       f"{review_id}: 用户确认必须记录 confirmed_by=user 与 confirmed_at")
        if status == "继承确认":
            parent_id = review.get("inherited_from_review_id")
            parent = review_by_id.get(parent_id)
            if change_class != "technical" or not parent \
                    or parent.get("scene_id") != scene_id \
                    or parent.get("review_type") != review_type \
                    or parent.get("confirmation_status") != "用户确认":
                _add(findings, "ERROR", "spatial-review-inheritance-invalid",
                       f"{review_id}: 只有技术性调整可继承同场景上一份用户确认")
            elif parent.get("source_scene_map_signature") != review.get("source_scene_map_signature"):
                _add(findings, "ERROR", "spatial-review-visible-change-reconfirmation-required",
                       f"{review_id}: 用户可见的空间或机位事实已变化，必须重新确认")
        if change_class == "material" and status == "继承确认":
            _add(findings, "ERROR", "spatial-review-material-reconfirmation-required",
                   f"{review_id}: 布局、边界、路线或落点变化必须重新由用户确认")

    missing_layout = set(map_by_scene) - {scene_id for scene_id, kind in active_by_key if kind == "layout"}
    missing_camera = set(map_by_scene) - {scene_id for scene_id, kind in active_by_key if kind == "camera_plan"}
    if required and layout_approval and missing_layout:
        _add(findings, "ERROR", "spatial-review-scene-uncovered",
               f"以下连续空间没有当前布局与走位确认稿: {sorted(missing_layout)}")

    if required and camera_approval and missing_camera:
        _add(findings, "ERROR", "camera-review-scene-uncovered",
               f"进入 {workflow_state} 前以下连续空间没有覆盖机位确认稿: {sorted(missing_camera)}")
    for review_type, needed in (("layout", layout_approval), ("camera_plan", camera_approval)):
        if not required or not needed:
            continue
        pending = sorted(scene_id for (scene_id, kind), review in active_by_key.items()
                         if kind == review_type
                         and review.get("confirmation_status") not in SPATIAL_REVIEW_ACCEPTED)
        if pending:
            _add(findings, "ERROR", "spatial-review-not-approved",
                   f"进入 {workflow_state} 前以下空间必须完成 {review_type} 用户确认: {pending}")
    return findings
