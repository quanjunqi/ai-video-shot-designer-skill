"""Validate workflow and unit production state evidence."""

from __future__ import annotations

from shotdesigner.findings import Finding


def _add(findings, code, message):
    findings.append(Finding(
        code=code,
        severity="ERROR",
        message=message,
        rule_source="config/workflow/states.json",
    ))


def validate_workflow(workflow, unit_by_id):
    findings = []
    state = workflow.get("workflow_state")
    active_id = workflow.get("active_unit_id")
    delivery = workflow.get("delivery") if isinstance(workflow.get("delivery"), dict) else {}
    mode = delivery.get("mode")
    evidence_states = {
        "PROMPTS_VALIDATED", "IN_PRODUCTION", "USER_REVIEW_PENDING",
        "USER_ACCEPTED", "USER_REJECTED", "DELIVERED",
    }
    if state in evidence_states:
        if active_id not in unit_by_id:
            _add(findings, "active-unit-invalid",
                 f"workflow_state={state} 必须绑定存在的 active_unit_id")
            return findings
    elif active_id is not None and active_id not in unit_by_id:
        _add(findings, "active-unit-invalid", f"active_unit_id={active_id} 不存在")
        return findings
    if mode not in {"prompt-only", "generated-video"}:
        _add(findings, "delivery-mode-invalid", "delivery.mode 必须是 prompt-only 或 generated-video")
        return findings
    if active_id not in unit_by_id:
        return findings
    unit_status = unit_by_id[active_id].get("production_status")
    expected = {
        "PROMPTS_VALIDATED": {"PROMPT_READY"},
        "IN_PRODUCTION": {"PROMPT_READY"},
        "USER_REVIEW_PENDING": {"GENERATED_AWAITING_USER"},
        "USER_ACCEPTED": {"USER_ACCEPTED"},
        "USER_REJECTED": {"USER_REJECTED"},
    }.get(state)
    if state == "DELIVERED":
        expected = {"PROMPT_READY"} if mode == "prompt-only" else {"USER_ACCEPTED"}
    if expected and unit_status not in expected:
        _add(findings, "workflow-state-evidence-drift",
             f"workflow_state={state}, delivery.mode={mode} 要求活动单元状态为 "
             f"{sorted(expected)}，当前={unit_status}")
    return findings


def validate_unit(unit, asset_by_id, allowed_states, video_asset_kinds):
    findings = []
    unit_id = unit.get("unit_id", "<unknown>")
    status = unit.get("production_status")
    if status not in allowed_states:
        _add(findings, "unit-production-status-invalid",
             f"{unit_id}: production_status 必须是受控状态，当前={status!r}")
        return findings, status
    video_asset_id = unit.get("video_asset_id")
    acceptance = unit.get("user_acceptance")
    if status in {"GENERATED_AWAITING_USER", "USER_ACCEPTED", "USER_REJECTED"} and not video_asset_id:
        _add(findings, "unit-video-asset-missing", f"{unit_id}: {status} 必须绑定当前结果的 video_asset_id")
    video_asset = asset_by_id.get(video_asset_id) if video_asset_id else None
    if video_asset_id and (not isinstance(video_asset, dict)
                           or video_asset.get("kind") not in video_asset_kinds):
        _add(findings, "unit-video-asset-invalid",
             f"{unit_id}: video_asset_id={video_asset_id} 未指向生成视频资产")
    elif video_asset and video_asset.get("unit_id") != unit_id:
        _add(findings, "unit-video-asset-unit-drift",
             f"{unit_id}: 视频资产登记给 {video_asset.get('unit_id')}")
    if status in {"USER_ACCEPTED", "USER_REJECTED"}:
        if not isinstance(acceptance, dict):
            _add(findings, "unit-user-acceptance-missing", f"{unit_id}: {status} 必须有 user_acceptance 记录")
        else:
            expected = "accepted" if status == "USER_ACCEPTED" else "rejected"
            if acceptance.get("decision") != expected:
                _add(findings, "unit-user-decision-drift",
                     f"{unit_id}: production_status 与 user_acceptance.decision 不一致")
            for field in ("statement", "decided_at", "video_asset_id", "video_asset_sha256"):
                if not acceptance.get(field):
                    _add(findings, "unit-user-acceptance-incomplete",
                         f"{unit_id}: user_acceptance 缺少 {field}")
            if acceptance.get("decided_by") != "user":
                _add(findings, "unit-user-acceptance-not-user",
                     f"{unit_id}: 视频接受或拒绝只能由 user 决定")
            if acceptance.get("video_asset_id") != video_asset_id:
                _add(findings, "unit-user-acceptance-video-drift",
                     f"{unit_id}: 用户决定未绑定当前 video_asset_id")
            if video_asset and acceptance.get("video_asset_sha256") != video_asset.get("sha256"):
                _add(findings, "unit-user-acceptance-version-drift",
                     f"{unit_id}: 用户决定未绑定当前视频不可变 sha256 版本")
    elif acceptance:
        _add(findings, "unit-user-acceptance-premature",
             f"{unit_id}: {status} 不得提前登记 user_acceptance")
    return findings, status
