"""Orchestrate delivery artifact, Prompt routing, and evidence validation."""

from __future__ import annotations

import re

from shotdesigner.findings import Finding
from shotdesigner.validators import artifact_registry
from shotdesigner.validators import execution_facts
from shotdesigner.validators import h3_delivery
from shotdesigner.validators import prompt_routing


def _add(findings, code, message):
    findings.append(Finding(code=code, severity="ERROR", message=message))


def _as_list(value):
    return value if isinstance(value, list) else []


def validate(
        workflow, artifact_root, state_at_least, resolve_artifact, sha256,
        scene_map_index):
    findings = []
    """Bind real files and inspect evidence under the confirmed prompt contract."""
    state = workflow.get("workflow_state")
    draft_required = state_at_least(state, "PROMPTS_VALIDATED")
    registry = artifact_registry.validate(
        workflow,
        artifact_root,
        state_at_least=state_at_least,
        resolve_artifact=resolve_artifact,
        sha256=sha256,
        scene_map_index=scene_map_index,
    )
    findings.extend(registry.findings)
    draft_spec = registry.draft_spec
    loaded_draft = registry.loaded_draft
    if loaded_draft is None:
        return findings
    routing = prompt_routing.validate(
        workflow, draft_spec, loaded_draft, draft_required=draft_required)
    findings.extend(routing.findings)
    if routing.stop:
        return findings
    h3_result = h3_delivery.validate(workflow, draft_spec, loaded_draft)
    findings.extend(h3_result.findings)
    if not h3_result.contexts:
        return findings

    shot_by_id = {shot.get("shot_id"): shot for shot in _as_list(workflow.get("shots"))
                  if isinstance(shot, dict) and shot.get("shot_id")}
    beat_by_id = {beat.get("beat_id", beat.get("id")): beat
                  for beat in _as_list(workflow.get("script_ir", {}).get("beats"))
                  if isinstance(beat, dict) and beat.get("beat_id", beat.get("id"))}
    events_by_beat = {}
    script_manifest = workflow.get("script_ir", {}).get("script_manifest", {})
    for event in _as_list(script_manifest.get("events")):
        if not isinstance(event, dict) or not event.get("event_id") or not event.get("beat_id"):
            continue
        events_by_beat.setdefault(event["beat_id"], []).append(event["event_id"])
    strict_v2 = str(workflow.get("schema_version") or "1.0").startswith("2.")
    strict_v22 = str(workflow.get("schema_version")) == "2.2"
    for context in h3_result.contexts:
        unit = context.unit
        sections = context.shot_sections
        for shot_id in _as_list(unit.get("shot_ids")):
            shot = shot_by_id.get(shot_id, {})
            shot_number = shot.get("h3_shot_number")
            section = sections.get(shot_number, "")
            findings.extend(execution_facts.validate(shot, section, strict_v22))
            action_event_ids = []
            for beat_id in _as_list(shot.get("beat_ids")):
                beat = beat_by_id.get(beat_id, {})
                for dialogue in _as_list(beat.get("dialogue")):
                    pattern = rf"<d>\s*\[[^\]]+\]\s*{re.escape(dialogue)}\s*</d>"
                    if not re.search(pattern, section):
                        _add(findings, "delivery-dialogue-missing",
                               f"{shot_id}: H3 未逐字覆盖 {beat_id} 台词: {dialogue}")
                if beat.get("action"):
                    action_event_ids.extend(events_by_beat.get(beat_id, []))

            evidence_map = shot.get("h3_evidence_by_event")
            expected_events = set(action_event_ids)
            if expected_events and strict_v2:
                if not isinstance(evidence_map, dict):
                    _add(findings, "delivery-event-evidence-map-missing",
                           f"{shot_id}: v2 真实交付必须用 h3_evidence_by_event 逐 EV 绑定 H3 动作证据")
                else:
                    declared_events = set(evidence_map)
                    missing_events = expected_events - declared_events
                    unknown_events = declared_events - expected_events
                    if missing_events:
                        _add(findings, "delivery-event-evidence-missing",
                               f"{shot_id}: 以下动作事件没有独立 H3 证据: {sorted(missing_events)}")
                    if unknown_events:
                        _add(findings, "delivery-event-evidence-unknown",
                               f"{shot_id}: h3_evidence_by_event 含未绑定到本镜的事件: {sorted(unknown_events)}")
                    for event_id in sorted(expected_events & declared_events):
                        evidence_items = evidence_map.get(event_id)
                        if not isinstance(evidence_items, list) or not evidence_items or not all(
                            isinstance(item, str) and item.strip() for item in evidence_items
                        ):
                            _add(findings, "delivery-event-evidence-invalid",
                                   f"{shot_id}/{event_id}: 证据必须是非空字符串数组")
                            continue
                        for evidence in evidence_items:
                            if evidence not in section:
                                _add(findings, "delivery-event-evidence-not-found",
                                       f"{shot_id}/{event_id}: 真实 H3 镜头段落缺少动作证据: {evidence!r}")
            elif expected_events:
                legacy_evidence = _as_list(shot.get("h3_evidence"))
                if not legacy_evidence:
                    _add(findings, "delivery-action-evidence-missing",
                           f"{shot_id}: 动作 beat 未声明可在真实 H3 中核对的 h3_evidence")
                for evidence in legacy_evidence:
                    if evidence not in section:
                        _add(findings, "delivery-action-evidence-not-found",
                               f"{shot_id}: 真实 H3 镜头段落缺少动作证据: {evidence!r}")

    for text_item in _as_list(workflow.get("script_ir", {}).get("on_screen_text")):
        if not isinstance(text_item, dict):
            continue
        literal = text_item.get("text")
        category = text_item.get("category")
        if literal and category != "non_narrative_unreadable" and literal not in loaded_draft:
            _add(findings, "delivery-screen-text-missing", f"交付稿漏掉画面文字: {literal}")
        if literal and any(literal in body for body in re.findall(r"<d>(.*?)</d>", loaded_draft, re.S)):
            _add(findings, "delivery-screen-text-as-dialogue", f"画面文字被误写成对白: {literal}")
        evidence = text_item.get("h3_treatment_evidence")
        if not evidence:
            _add(findings, "delivery-screen-text-treatment-missing",
                   f"画面文字 {literal or text_item.get('text_id')} 未声明 H3 处理证据")
        elif evidence not in loaded_draft:
            _add(findings, "delivery-screen-text-treatment-not-found",
                   f"画面文字 {literal} 的后期处理证据未出现在交付稿: {evidence!r}")
    return findings
