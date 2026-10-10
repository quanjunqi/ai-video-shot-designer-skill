"""Validate project duration budgets and generation-unit capacity."""

from __future__ import annotations

import re

from shotdesigner.findings import Finding


UNIT_PLANNING_FIELDS = (
    "beat_ids", "narrative_range", "generation_duration_seconds",
    "shooting_form", "boundary", "capacity",
)
UNIT_BOUNDARY_FIELDS = (
    "entry_reason", "exit_reason", "exit_state_recoverable", "unresolved_causality",
)
UNIT_CAPACITY_FIELDS = (
    "dialogue_seconds", "observable_beat_count", "beats_per_10_seconds",
    "max_simultaneous_action_lanes", "key_contact_count",
    "prop_state_change_count", "character_position_change_count", "cut_count",
    "precision_risks", "physical_action_density", "execution_risk", "rationale",
)


def _add(findings, severity, code, message):
    findings.append(Finding(code=code, severity=severity, message=message))


def _as_list(value):
    return value if isinstance(value, list) else []


def _ids(items, key="id"):
    return {item.get(key) for item in items if isinstance(item, dict) and item.get(key)}


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def duration_seconds(value):
    if is_number(value):
        return float(value)
    if isinstance(value, str):
        match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*s\s*", value)
        if match:
            return float(match.group(1))
    return None


def validate_duration_budget(script, strict):
    findings = []
    project = script.get("project") if isinstance(script, dict) else None
    if not isinstance(project, dict):
        if strict:
            _add(findings, "ERROR", "duration-budget-missing",
                   "v2 Script IR 缺少 project.duration_budget，无法证明目标时长足以忠实呈现剧本")
        return findings
    budget = project.get("duration_budget")
    if not isinstance(budget, dict):
        if strict:
            _add(findings, "ERROR", "duration-budget-missing",
                   "v2 Script IR 缺少 project.duration_budget，无法证明目标时长足以忠实呈现剧本")
        return findings

    required = (
        "target_seconds", "target_source", "faithful_min_seconds",
        "final_planned_seconds", "breakdown", "resolution", "authorized_change_ids",
    )
    missing = [field for field in required if field not in budget or budget.get(field) is None]
    if missing:
        _add(findings, "ERROR", "duration-budget-incomplete",
               f"project.duration_budget 缺少字段: {missing}")
        return findings

    target = budget.get("target_seconds")
    faithful = budget.get("faithful_min_seconds")
    final = budget.get("final_planned_seconds")
    for field, value in (
        ("target_seconds", target),
        ("faithful_min_seconds", faithful),
        ("final_planned_seconds", final),
    ):
        if not is_number(value) or value <= 0:
            _add(findings, "ERROR", "duration-budget-value-invalid",
                   f"project.duration_budget.{field} 必须是正数秒")
    if not all(is_number(value) and value > 0 for value in (target, faithful, final)):
        return findings

    if budget.get("target_source") not in {"user", "estimated"}:
        _add(findings, "ERROR", "duration-target-source-invalid",
               "project.duration_budget.target_source 必须是 user 或 estimated")
    resolution = budget.get("resolution")
    if resolution not in {"fits", "extended_to_faithful", "authorized_reduction"}:
        _add(findings, "ERROR", "duration-resolution-invalid",
               "project.duration_budget.resolution 非法")

    breakdown = budget.get("breakdown")
    breakdown_fields = ("dialogue", "action", "pause_reaction", "movement_camera")
    if not isinstance(breakdown, dict):
        _add(findings, "ERROR", "duration-breakdown-invalid",
               "project.duration_budget.breakdown 必须是结构化对象")
    else:
        values = []
        for field in breakdown_fields:
            value = breakdown.get(field)
            if not is_number(value) or value < 0:
                _add(findings, "ERROR", "duration-breakdown-invalid",
                       f"project.duration_budget.breakdown.{field} 必须是非负数秒")
            else:
                values.append(float(value))
        if len(values) == len(breakdown_fields) and abs(sum(values) - float(faithful)) > 0.25:
            _add(findings, "ERROR", "duration-breakdown-drift",
                   f"忠实呈现分项合计 {sum(values):.3g}s 与 faithful_min_seconds={faithful}s 不一致")

    change_ids = budget.get("authorized_change_ids")
    if not isinstance(change_ids, list):
        _add(findings, "ERROR", "duration-authorized-changes-invalid",
               "project.duration_budget.authorized_change_ids 必须是数组")
        change_ids = []
    known_change_ids = _ids(_as_list(script.get("script_manifest", {}).get("authorized_changes")), "change_id")
    unknown_changes = set(change_ids) - known_change_ids
    if unknown_changes:
        _add(findings, "ERROR", "duration-authorized-change-unknown",
               f"时长预算引用未知 authorized_changes: {sorted(unknown_changes)}")

    if final + 0.001 < faithful:
        if resolution != "authorized_reduction" or not change_ids:
            _add(findings, "ERROR", "duration-fidelity-underfunded",
                   "最终计划时长低于忠实呈现下限，且没有明确授权删改")
    elif target + 0.001 < faithful and resolution != "extended_to_faithful":
        _add(findings, "ERROR", "duration-gap-unresolved",
               "用户/估算目标低于忠实呈现下限时，resolution 必须为 extended_to_faithful")
    elif target + 0.001 >= faithful and resolution == "authorized_reduction":
        _add(findings, "WARNING", "duration-reduction-unnecessary",
               "目标时长已容纳忠实呈现，却声明 authorized_reduction；请复核是否真的需要删改")
    return findings


def validate_unit(unit, shot_by_id, strict, max_duration_seconds=15):
    findings = []
    unit_id = unit.get("unit_id", "<unknown>")
    if not strict:
        return findings
    missing = [field for field in UNIT_PLANNING_FIELDS
               if field not in unit or unit.get(field) is None]
    if missing:
        _add(findings, "ERROR", "unit-planning-field-missing",
               f"{unit_id}: 缺少剧情容量字段 {missing}")
        return findings

    beat_ids = unit.get("beat_ids")
    if not isinstance(beat_ids, list) or not beat_ids or len(beat_ids) != len(set(beat_ids)):
        _add(findings, "ERROR", "unit-beat-ids-invalid",
               f"{unit_id}: beat_ids 必须是非空且不重复的数组")
        beat_ids = []
    shot_beats = []
    for shot_id in _as_list(unit.get("shot_ids")):
        shot = shot_by_id.get(shot_id)
        if not isinstance(shot, dict):
            continue
        for beat_id in _as_list(shot.get("beat_ids")):
            if beat_id not in shot_beats:
                shot_beats.append(beat_id)
    if beat_ids and beat_ids != shot_beats:
        _add(findings, "ERROR", "unit-beat-coverage-drift",
               f"{unit_id}: unit beat 顺序 {beat_ids} 与镜头实际覆盖 {shot_beats} 不一致")

    narrative = unit.get("narrative_range")
    if not isinstance(narrative, dict):
        _add(findings, "ERROR", "unit-narrative-range-invalid",
               f"{unit_id}: narrative_range 必须是对象")
    else:
        required = ("start_beat_id", "end_beat_id", "summary")
        missing_narrative = [field for field in required
                             if field not in narrative or narrative.get(field) in (None, "")]
        if missing_narrative:
            _add(findings, "ERROR", "unit-narrative-range-incomplete",
                   f"{unit_id}: narrative_range 缺少 {missing_narrative}")
        elif beat_ids and (narrative["start_beat_id"] != beat_ids[0]
                           or narrative["end_beat_id"] != beat_ids[-1]):
            _add(findings, "ERROR", "unit-narrative-range-drift",
                   f"{unit_id}: narrative_range 首尾与 beat_ids 不一致")

    duration = unit.get("generation_duration_seconds")
    if not isinstance(duration, int) or isinstance(duration, bool) or duration <= 0 or duration > max_duration_seconds:
        _add(findings, "ERROR", "unit-duration-invalid",
               f"{unit_id}: generation_duration_seconds 必须是 1-{max_duration_seconds:g} 的整数")
    else:
        shot_seconds = []
        for shot_id in _as_list(unit.get("shot_ids")):
            shot = shot_by_id.get(shot_id, {})
            value = duration_seconds(shot.get("shot_card", {}).get("timing", {}).get("duration"))
            if value is None:
                _add(findings, "ERROR", "shot-duration-unparseable",
                       f"{shot_id}: timing.duration 必须是数值秒或形如 3.0s")
            else:
                shot_seconds.append(value)
        if shot_seconds and sum(shot_seconds) > float(duration) + 0.001:
            _add(findings, "ERROR", "unit-shot-duration-overflow",
                   f"{unit_id}: 镜头时长合计 {sum(shot_seconds):.3g}s 超过单元 {duration}s")

    if unit.get("shooting_form") not in {"multi_shot", "one_take"}:
        _add(findings, "ERROR", "unit-shooting-form-invalid",
               f"{unit_id}: shooting_form 必须是 multi_shot 或 one_take")

    boundary = unit.get("boundary")
    if not isinstance(boundary, dict):
        _add(findings, "ERROR", "unit-boundary-invalid", f"{unit_id}: boundary 必须是对象")
    else:
        missing_boundary = [field for field in UNIT_BOUNDARY_FIELDS
                            if field not in boundary or boundary.get(field) is None]
        if missing_boundary:
            _add(findings, "ERROR", "unit-boundary-incomplete",
                   f"{unit_id}: boundary 缺少 {missing_boundary}")
        if boundary.get("exit_state_recoverable") is not True:
            _add(findings, "ERROR", "unit-exit-not-recoverable",
                   f"{unit_id}: 单元必须结束在可恢复、可验证状态")
        unresolved = boundary.get("unresolved_causality")
        if not isinstance(unresolved, list):
            _add(findings, "ERROR", "unit-unresolved-causality-invalid",
                   f"{unit_id}: unresolved_causality 必须是数组")
        elif unresolved:
            invalid = [item for item in unresolved if not isinstance(item, dict)
                       or not item.get("event_id") or not item.get("handoff")]
            if invalid:
                _add(findings, "ERROR", "unit-unresolved-causality-incomplete",
                       f"{unit_id}: 跨单元未完成因果必须登记 event_id 与 handoff")

    capacity = unit.get("capacity")
    if not isinstance(capacity, dict):
        _add(findings, "ERROR", "unit-capacity-invalid", f"{unit_id}: capacity 必须是对象")
    else:
        missing_capacity = [field for field in UNIT_CAPACITY_FIELDS
                            if field not in capacity or capacity.get(field) is None]
        if missing_capacity:
            _add(findings, "ERROR", "unit-capacity-incomplete",
                   f"{unit_id}: capacity 缺少 {missing_capacity}")
        dialogue_seconds = capacity.get("dialogue_seconds")
        if not is_number(dialogue_seconds) or dialogue_seconds < 0:
            _add(findings, "ERROR", "unit-dialogue-duration-invalid",
                   f"{unit_id}: capacity.dialogue_seconds 必须是非负数")
        elif is_number(duration) and dialogue_seconds > duration:
            _add(findings, "ERROR", "unit-dialogue-duration-overflow",
                   f"{unit_id}: 对白时长超过生成时长")
        integer_fields = (
            "observable_beat_count", "max_simultaneous_action_lanes",
            "key_contact_count", "prop_state_change_count",
            "character_position_change_count", "cut_count",
        )
        for field in integer_fields:
            value = capacity.get(field)
            minimum = 1 if field == "max_simultaneous_action_lanes" else 0
            if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
                _add(findings, "ERROR", "unit-capacity-count-invalid",
                       f"{unit_id}: capacity.{field} 必须是 >= {minimum} 的整数")
        expected_beats = len(beat_ids)
        if capacity.get("observable_beat_count") != expected_beats:
            _add(findings, "ERROR", "unit-capacity-beat-count-drift",
                   f"{unit_id}: observable_beat_count 应等于 beat_ids 数量 {expected_beats}")
        if isinstance(duration, int) and duration > 0:
            expected_rate = expected_beats * 10.0 / duration
            rate = capacity.get("beats_per_10_seconds")
            if not is_number(rate) or abs(float(rate) - expected_rate) > 0.01:
                _add(findings, "ERROR", "unit-capacity-beat-rate-drift",
                       f"{unit_id}: beats_per_10_seconds 应为 {expected_rate:.2f}")
            action_total = sum(
                capacity.get(field, 0) if isinstance(capacity.get(field), int) else 0
                for field in ("key_contact_count", "prop_state_change_count", "character_position_change_count")
            )
            expected_density = action_total * 10.0 / duration
            density = capacity.get("physical_action_density")
            if not is_number(density) or abs(float(density) - expected_density) > 0.01:
                _add(findings, "ERROR", "unit-capacity-action-density-drift",
                       f"{unit_id}: physical_action_density 应为 {expected_density:.2f} 次/10秒")
        expected_cuts = max(0, len(_as_list(unit.get("shot_ids"))) - 1)
        if capacity.get("cut_count") != expected_cuts:
            _add(findings, "ERROR", "unit-capacity-cut-count-drift",
                   f"{unit_id}: cut_count 应等于镜头切换数 {expected_cuts}")
        unit_cards = [
            shot_by_id[shot_id].get("shot_card", {}) for shot_id in _as_list(unit.get("shot_ids"))
            if shot_id in shot_by_id and isinstance(shot_by_id[shot_id].get("shot_card"), dict)
        ]
        minimum_contacts = sum(len(_as_list(card.get("key_contacts"))) for card in unit_cards)
        if isinstance(capacity.get("key_contact_count"), int) \
                and capacity.get("key_contact_count") < minimum_contacts:
            _add(findings, "ERROR", "unit-capacity-contact-undercount",
                   f"{unit_id}: key_contact_count 至少应为镜头卡可见接触数 {minimum_contacts}")
        minimum_position_changes = sum(
            1 for card in unit_cards if len(_as_list(card.get("spatial_route"))) >= 2
        )
        if isinstance(capacity.get("character_position_change_count"), int) \
                and capacity.get("character_position_change_count") < minimum_position_changes:
            _add(findings, "ERROR", "unit-capacity-position-undercount",
                   f"{unit_id}: character_position_change_count 至少应为 {minimum_position_changes}")
        minimum_prop_changes = 0
        for card in unit_cards:
            for prop_state in (card.get("prop_states") or {}).values():
                if not isinstance(prop_state, dict):
                    continue
                before = prop_state.get("start", prop_state.get("before"))
                after = prop_state.get("end", prop_state.get("after"))
                if before is not None and after is not None and before != after:
                    minimum_prop_changes += 1
        if isinstance(capacity.get("prop_state_change_count"), int) \
                and capacity.get("prop_state_change_count") < minimum_prop_changes:
            _add(findings, "ERROR", "unit-capacity-prop-change-undercount",
                   f"{unit_id}: prop_state_change_count 至少应为镜头卡可推导变化数 {minimum_prop_changes}")
        declared_lanes = [
            len(card.get("action_lanes")) for card in unit_cards
            if isinstance(card.get("action_lanes"), list) and card.get("action_lanes")
        ]
        minimum_lanes = max(declared_lanes, default=1)
        if isinstance(capacity.get("max_simultaneous_action_lanes"), int) \
                and capacity.get("max_simultaneous_action_lanes") < minimum_lanes:
            _add(findings, "ERROR", "unit-capacity-lanes-undercount",
                   f"{unit_id}: max_simultaneous_action_lanes 至少应为镜头卡声明值 {minimum_lanes}")
        risks = capacity.get("precision_risks")
        if not isinstance(risks, list) or any(not isinstance(item, str) or not item.strip() for item in risks):
            _add(findings, "ERROR", "unit-capacity-precision-risks-invalid",
                   f"{unit_id}: precision_risks 必须是字符串数组")
        if capacity.get("execution_risk") not in {"low", "medium", "high"}:
            _add(findings, "ERROR", "unit-capacity-execution-risk-invalid",
                   f"{unit_id}: execution_risk 必须是 low、medium 或 high")
    return findings
