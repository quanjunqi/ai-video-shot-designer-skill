"""Validate scene direction, coverage, and edit continuity contracts."""

from __future__ import annotations

from shotdesigner import catalogs
from shotdesigner.findings import Finding


COVERAGE_MODES = {
    "single-shot", "long-take", "multi-camera-coverage", "action-montage",
}
CAMERA_ROLES = {
    "scale", "relationship", "viewpoint", "immersive-follow", "reaction",
    "action-proof", "prop-proof", "reveal", "transition", "result",
}
SCENE_DIRECTION_BRIEF_FIELDS = (
    "scene_id", "dramatic_objective", "viewpoint_character", "opening_state",
    "turning_point", "information_release", "performance_arc", "spatial_arc",
    "camera_principle", "coverage_principle", "cutting_principle", "closing_image",
)
COVERAGE_PLAN_FIELDS = (
    "scene_id", "coverage_mode", "selection_reason", "visual_beats",
    "camera_assignments", "shot_order", "coverage_strategies", "cut_contracts",
)
CAMERA_ASSIGNMENT_FIELDS = (
    "camera_id", "primary_role", "position", "direction", "shot_size",
    "main_subject", "visible_anchors", "forbidden_content", "entry_cut_trigger",
    "exit_cut_trigger", "received_action_state", "output_action_state",
)
CUT_CONTRACT_FIELDS = (
    "from_shot_id", "to_shot_id", "cut_trigger", "outgoing_motion",
    "incoming_motion", "screen_direction", "prop_state_before",
    "prop_state_after", "cut_reason",
)
LONG_TAKE_GATE_FIELDS = (
    "continuous_space", "clear_narrative_task", "traversable_camera_route",
    "principal_action_chain", "major_turn_count", "focus_handoff_count",
    "controlled_principal_characters", "staged_compositions", "stable_end_state",
)
COVERAGE_STRATEGIES = catalogs.coverage_strategies()


def _add(findings, code, message):
    findings.append(Finding(code=code, severity="ERROR", message=message))


def _nonempty_string(value):
    return isinstance(value, str) and bool(value.strip())


def _as_list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def validate(workflow, scene_ids, map_by_scene, shot_list, camera_map, camera_anchor_ids):
    """Validate scene intent, coverage design, and edit continuity for v2.2."""
    findings = []
    briefs = workflow.get("scene_direction_briefs")
    plans = workflow.get("coverage_plans")
    if not isinstance(briefs, list):
        _add(findings, "scene-direction-briefs-missing",
               "v2.2 必须包含 scene_direction_briefs 数组")
        briefs = []
    if not isinstance(plans, list):
        _add(findings, "coverage-plans-missing",
               "v2.2 必须包含 coverage_plans 数组")
        plans = []

    brief_by_scene = {}
    for index, brief in enumerate(briefs, 1):
        if not isinstance(brief, dict):
            _add(findings, "scene-direction-brief-type",
                   f"scene_direction_briefs[{index}] 必须是对象")
            continue
        scene_id = brief.get("scene_id")
        missing = [field for field in SCENE_DIRECTION_BRIEF_FIELDS
                   if not _nonempty_string(brief.get(field))]
        if missing:
            _add(findings, "scene-direction-brief-incomplete",
                   f"{scene_id or index}: 场景导演意图缺少非空字段 {missing}")
        if scene_id in brief_by_scene:
            _add(findings, "scene-direction-brief-duplicate",
                   f"{scene_id}: 场景导演意图重复")
        elif scene_id:
            brief_by_scene[scene_id] = brief

    plan_by_scene = {}
    for index, plan in enumerate(plans, 1):
        if not isinstance(plan, dict):
            _add(findings, "coverage-plan-type",
                   f"coverage_plans[{index}] 必须是对象")
            continue
        scene_id = plan.get("scene_id")
        missing = [field for field in COVERAGE_PLAN_FIELDS if field not in plan]
        if missing:
            _add(findings, "coverage-plan-incomplete",
                   f"{scene_id or index}: coverage plan 缺少 {missing}")
        if scene_id in plan_by_scene:
            _add(findings, "coverage-plan-duplicate",
                   f"{scene_id}: coverage plan 重复")
        elif scene_id:
            plan_by_scene[scene_id] = plan

        mode = plan.get("coverage_mode")
        if mode not in COVERAGE_MODES:
            _add(findings, "coverage-mode-invalid",
                   f"{scene_id or index}: 未知 coverage_mode={mode}")
        if not _nonempty_string(plan.get("selection_reason")):
            _add(findings, "coverage-selection-reason-missing",
                   f"{scene_id or index}: coverage mode 必须有具体选择理由")
        visual_beats = plan.get("visual_beats")
        if not isinstance(visual_beats, list) or not visual_beats or not all(
                _nonempty_string(item) for item in visual_beats):
            _add(findings, "coverage-visual-beats-invalid",
                   f"{scene_id or index}: visual_beats 必须是非空字符串数组")

        scene_map = map_by_scene.get(scene_id, {})
        cameras = camera_map(scene_map) if scene_map else {}
        assignments = plan.get("camera_assignments")
        assignment_by_camera = {}
        if not isinstance(assignments, list) or not assignments:
            _add(findings, "coverage-camera-assignments-invalid",
                   f"{scene_id or index}: camera_assignments 必须是非空数组")
            assignments = []
        for assignment_index, assignment in enumerate(assignments, 1):
            if not isinstance(assignment, dict):
                _add(findings, "coverage-camera-assignment-type",
                       f"{scene_id}: camera_assignments[{assignment_index}] 必须是对象")
                continue
            camera_id = assignment.get("camera_id")
            absent = [field for field in CAMERA_ASSIGNMENT_FIELDS
                      if field not in assignment or assignment.get(field) in (None, "")]
            if absent:
                _add(findings, "coverage-camera-assignment-incomplete",
                       f"{scene_id}/{camera_id or assignment_index}: 缺少 {absent}")
            if camera_id in assignment_by_camera:
                _add(findings, "coverage-camera-assignment-duplicate",
                       f"{scene_id}/{camera_id}: 机位任务重复")
            elif camera_id:
                assignment_by_camera[camera_id] = assignment
            roles = [assignment.get("primary_role")]
            if assignment.get("secondary_role") is not None:
                roles.append(assignment.get("secondary_role"))
            if any(role not in CAMERA_ROLES for role in roles):
                _add(findings, "coverage-camera-role-invalid",
                       f"{scene_id}/{camera_id}: 未知机位职责 {roles}")
            if len(roles) != len(set(roles)):
                _add(findings, "coverage-camera-role-duplicate",
                       f"{scene_id}/{camera_id}: 主辅职责不能相同")
            camera = cameras.get(camera_id)
            if not camera:
                _add(findings, "coverage-camera-unknown",
                       f"{scene_id}/{camera_id}: 机位不在同场 scene map 中")
            else:
                if assignment.get("position") != camera.get("position"):
                    _add(findings, "coverage-camera-position-drift",
                           f"{scene_id}/{camera_id}: coverage 机位坐标与 scene map 不一致")
                if assignment.get("direction") != camera.get("orientation"):
                    _add(findings, "coverage-camera-direction-drift",
                           f"{scene_id}/{camera_id}: coverage 朝向与 scene map 不一致")
                actual_visible = set(_as_list(assignment.get("visible_anchors")))
                expected_visible = set(camera_anchor_ids(camera, "visible_anchors"))
                if actual_visible != expected_visible:
                    _add(findings, "coverage-camera-anchor-drift",
                           f"{scene_id}/{camera_id}: coverage 可见锚点与 scene map 不一致")

        scene_shots = [shot for shot in shot_list
                       if isinstance(shot, dict) and shot.get("scene_id") == scene_id]
        expected_order = [shot.get("shot_id") for shot in scene_shots]
        shot_order = plan.get("shot_order")
        if shot_order != expected_order:
            _add(findings, "coverage-shot-order-drift",
                   f"{scene_id}: shot_order={shot_order} 与最终镜头顺序={expected_order} 不一致")
        for shot in scene_shots:
            camera_id = shot.get("camera_id")
            if not camera_id:
                _add(findings, "coverage-shot-camera-missing",
                       f"{shot.get('shot_id')}: v2.2 镜头必须显式绑定 camera_id")
            elif camera_id not in assignment_by_camera:
                _add(findings, "coverage-shot-camera-unassigned",
                       f"{shot.get('shot_id')}: camera_id={camera_id} 未获本场 coverage plan 批准")
            else:
                assignment = assignment_by_camera[camera_id]
                card_size = shot.get("shot_card", {}).get("camera", {}).get("shot_size")
                if card_size and assignment.get("shot_size") != card_size:
                    _add(findings, "coverage-camera-shot-size-drift",
                           f"{shot.get('shot_id')}: coverage 景别与 shot card 不一致")

        strategy_ids = plan.get("coverage_strategies")
        if not isinstance(strategy_ids, list) or len(strategy_ids) != len(set(strategy_ids)):
            _add(findings, "coverage-strategies-invalid",
                   f"{scene_id}: coverage_strategies 必须是不重复数组")
            strategy_ids = []
        for strategy_id in strategy_ids:
            if strategy_id not in COVERAGE_STRATEGIES:
                _add(findings, "coverage-strategy-unknown",
                       f"{scene_id}: 未知 coverage strategy={strategy_id}")

        cuts = plan.get("cut_contracts")
        if not isinstance(cuts, list):
            _add(findings, "coverage-cut-contracts-invalid",
                   f"{scene_id}: cut_contracts 必须是数组")
            cuts = []
        expected_pairs = list(zip(expected_order, expected_order[1:]))
        actual_pairs = []
        shot_index = {shot.get("shot_id"): shot for shot in scene_shots}
        for cut_index, cut in enumerate(cuts, 1):
            if not isinstance(cut, dict):
                _add(findings, "coverage-cut-contract-type",
                       f"{scene_id}: cut_contracts[{cut_index}] 必须是对象")
                continue
            absent = [field for field in CUT_CONTRACT_FIELDS
                      if field not in cut or cut.get(field) in (None, "")]
            if absent:
                _add(findings, "coverage-cut-contract-incomplete",
                       f"{scene_id}/cut-{cut_index}: 缺少 {absent}")
            pair = (cut.get("from_shot_id"), cut.get("to_shot_id"))
            actual_pairs.append(pair)
            before = shot_index.get(pair[0], {}).get("shot_card", {})
            after = shot_index.get(pair[1], {}).get("shot_card", {})
            if before and cut.get("outgoing_motion") != before.get("action_states", {}).get("end"):
                _add(findings, "coverage-cut-outgoing-state-drift",
                       f"{scene_id}/{pair}: outgoing_motion 与前镜尾态不一致")
            if after and cut.get("incoming_motion") != after.get("action_states", {}).get("start"):
                _add(findings, "coverage-cut-incoming-state-drift",
                       f"{scene_id}/{pair}: incoming_motion 与后镜起态不一致")
            if before and cut.get("prop_state_before") != before.get("prop_states", {}):
                _add(findings, "coverage-cut-prop-before-drift",
                       f"{scene_id}/{pair}: prop_state_before 与前镜道具后态不一致")
            if cut.get("prop_state_after") != cut.get("prop_state_before"):
                _add(findings, "coverage-cut-prop-state-jump",
                       f"{scene_id}/{pair}: 切镜瞬间不得重置持有者、手别、数量或道具状态")
        if actual_pairs != expected_pairs:
            _add(findings, "coverage-cut-pairs-drift",
                   f"{scene_id}: 每对相邻镜头必须且只能有一个顺序一致的 cut contract")

        if mode in {"single-shot", "long-take"} and len(expected_order) != 1:
            _add(findings, "coverage-single-view-shot-count",
                   f"{scene_id}: {mode} 必须只有一个最终镜头")
        if mode == "long-take":
            gate = plan.get("long_take_gate")
            if not isinstance(gate, dict):
                _add(findings, "long-take-gate-missing",
                       f"{scene_id}: long-take 缺少 long_take_gate")
            else:
                missing_gate = [field for field in LONG_TAKE_GATE_FIELDS if field not in gate]
                if missing_gate:
                    _add(findings, "long-take-gate-incomplete",
                           f"{scene_id}: long_take_gate 缺少 {missing_gate}")
                boolean_fields = set(LONG_TAKE_GATE_FIELDS) - {"major_turn_count", "focus_handoff_count"}
                if any(gate.get(field) is not True for field in boolean_fields):
                    _add(findings, "long-take-gate-failed",
                           f"{scene_id}: long-take 的空间、任务、路线、动作链、人数、构图或尾态条件未通过")
                for field in ("major_turn_count", "focus_handoff_count"):
                    value = gate.get(field)
                    if not isinstance(value, int) or isinstance(value, bool) or value < 0 or value > 1:
                        _add(findings, "long-take-complexity-exceeded",
                               f"{scene_id}: long_take_gate.{field} 必须为 0 或 1")
            if "CAM-LONG-TAKE-BLOCKING" not in {
                    strategy.get("strategy_id")
                    for shot in scene_shots
                    for strategy in _as_list(shot.get("shot_card", {}).get("strategy_selection"))
                    if isinstance(strategy, dict)}:
                _add(findings, "long-take-strategy-missing",
                       f"{scene_id}: long-take 必须由 CAM-LONG-TAKE-BLOCKING 具体化")
        if mode == "action-montage":
            if len(expected_order) < 3:
                _add(findings, "action-montage-shot-count-low",
                       f"{scene_id}: action-montage 至少需要三个承担不同信息任务的镜头")
            if "COV-RESULT-HOLD" not in strategy_ids:
                _add(findings, "action-montage-result-hold-missing",
                       f"{scene_id}: action-montage 必须保留结果镜头，不能只堆动作")

    expected_scenes = set(scene_ids)
    if set(brief_by_scene) != expected_scenes:
        _add(findings, "scene-direction-brief-coverage-drift",
               f"scene_direction_briefs 必须逐场覆盖 Script IR: expected={sorted(expected_scenes)}, actual={sorted(brief_by_scene)}")
    if set(plan_by_scene) != expected_scenes:
        _add(findings, "coverage-plan-scene-coverage-drift",
               f"coverage_plans 必须逐场覆盖 Script IR: expected={sorted(expected_scenes)}, actual={sorted(plan_by_scene)}")
    return findings

