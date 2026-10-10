"""Validate per-shot H3 execution facts against delivered text."""

from __future__ import annotations

import json

from shotdesigner.findings import Finding


KNOWN_FACT_KEYS = {
    "hand", "holder", "unique_count", "screen_direction", "start_state",
    "end_state", "prop_orientation",
}


def _add(findings, code, message):
    findings.append(Finding(code=code, severity="ERROR", message=message))


def validate(shot, section, strict):
    findings = []
    shot_id = shot.get("shot_id", "<unknown>")
    facts = shot.get("h3_execution_facts")
    if strict and not isinstance(facts, dict):
        _add(findings, "h3-execution-facts-missing",
               f"{shot_id}: v2.2 每镜必须提供非空 h3_execution_facts，至少登记 start_state/end_state")
        return findings
    if not isinstance(facts, dict):
        return findings
    card = shot.get("shot_card") if isinstance(shot.get("shot_card"), dict) else {}
    serialized = json.dumps(card, ensure_ascii=False).lower()
    required_fact_keys = {"start_state", "end_state"}
    if (card.get("spatial_route") or (shot.get("spatial_constraints") or {}).get("screen_positions")):
        required_fact_keys.add("screen_direction")
    contact_text = json.dumps(card.get("key_contacts", []), ensure_ascii=False).lower()
    prop_text = json.dumps(card.get("prop_states", {}), ensure_ascii=False).lower()
    if any(token in contact_text + prop_text for token in
           ("hand", "left", "right", "手", "握", "抓", "签", "压住", "递", "接过")):
        required_fact_keys.add("hand")
    if card.get("prop_states") and any(token in serialized for token in
                                        ("holder", "held", "持有", "手持", "握住", "拿起", "交给")):
        required_fact_keys.add("holder")
    if any(token in serialized for token in ("unique", "only one", "唯一", "仅一", "数量")):
        required_fact_keys.add("unique_count")
    if card.get("prop_states") and any(token in serialized for token in
                                        ("orientation", "facing", "正面", "背面", "朝向", "旋转", "倒置")):
        required_fact_keys.add("prop_orientation")
    missing_required = sorted(required_fact_keys - set(facts))
    if strict and missing_required:
        _add(findings, "h3-execution-facts-incomplete",
               f"{shot_id}: 镜头卡要求登记执行事实 {missing_required}")
    unknown = set(facts) - KNOWN_FACT_KEYS
    if unknown:
        _add(findings, "h3-execution-facts-unknown",
               f"{shot_id}: 未知执行事实字段 {sorted(unknown)}")
    for fact_name, fact in facts.items():
        if not isinstance(fact, dict) or "value" not in fact:
            _add(findings, "h3-execution-fact-invalid",
                   f"{shot_id}/{fact_name}: 必须包含 value、required_literals、forbidden_literals")
            continue
        required = fact.get("required_literals")
        forbidden = fact.get("forbidden_literals")
        if not isinstance(required, list) or not required or not all(
                isinstance(item, str) and item.strip() for item in required):
            _add(findings, "h3-execution-required-invalid",
                   f"{shot_id}/{fact_name}: required_literals 必须是非空字符串数组")
            continue
        if not isinstance(forbidden, list) or not all(
                isinstance(item, str) and item.strip() for item in forbidden):
            _add(findings, "h3-execution-forbidden-invalid",
                   f"{shot_id}/{fact_name}: forbidden_literals 必须是字符串数组")
            continue
        for literal in required:
            if literal not in section:
                _add(findings, "h3-execution-fact-missing",
                       f"{shot_id}/{fact_name}: H3 缺少正向执行证据 {literal!r}")
        for literal in forbidden:
            if literal in section:
                _add(findings, "h3-execution-fact-contradiction",
                       f"{shot_id}/{fact_name}: H3 出现冲突描述 {literal!r}")
    return findings
