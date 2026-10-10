"""Validate Script IR event, dialogue, lock, and change manifests."""

from __future__ import annotations

from shotdesigner.findings import Finding


def _add(findings, severity, code, message):
    findings.append(Finding(code=code, severity=severity, message=message))


def _as_list(value):
    return value if isinstance(value, list) else []


def validate(script, beat_by_id, strict):
    findings = []
    manifest = script.get("script_manifest")
    if not isinstance(manifest, dict):
        level = "ERROR" if strict else "WARNING"
        code = "script-manifest-missing" if strict else "script-manifest-missing-legacy"
        _add(findings, level, code, "Script IR 缺少 EV/DLG/LOCK script_manifest")
        return findings

    required = ("events", "dialogues", "locks", "authorized_changes")
    missing = [field for field in required if not isinstance(manifest.get(field), list)]
    if missing:
        _add(findings, "ERROR", "script-manifest-field-missing",
               f"script_manifest 必须包含数组字段: {missing}")
        return findings

    specs = (
        ("events", "event_id", ("beat_id", "fact")),
        ("dialogues", "dialogue_id", ("beat_id", "speaker_id", "text", "language")),
        ("locks", "lock_id", ("target", "rule")),
        ("authorized_changes", "change_id", ("targets", "change", "reason", "approved_by")),
    )
    for collection, id_field, required_fields in specs:
        items = manifest[collection]
        ids = []
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                _add(findings, "ERROR", "script-manifest-entry-type",
                       f"script_manifest.{collection}[{index}] 必须是对象")
                continue
            item_id = item.get(id_field)
            if not item_id:
                _add(findings, "ERROR", "script-manifest-id-missing",
                       f"script_manifest.{collection}[{index}] 缺少 {id_field}")
            else:
                ids.append(item_id)
            absent = [field for field in required_fields
                      if field not in item or item.get(field) in (None, "")]
            if absent:
                _add(findings, "ERROR", "script-manifest-entry-incomplete",
                       f"{item_id or collection}: 缺少 {absent}")
            beat_id = item.get("beat_id")
            if beat_id and beat_id not in beat_by_id:
                _add(findings, "ERROR", "script-manifest-beat-unknown",
                       f"{item_id or collection}: beat_id 不存在: {beat_id}")
        if len(ids) != len(set(ids)):
            _add(findings, "ERROR", "script-manifest-id-duplicate",
                   f"script_manifest.{collection} 存在重复 {id_field}")

    if strict:
        event_beats = {
            item.get("beat_id") for item in manifest["events"] if isinstance(item, dict)
        }
        dialogue_locks = {
            (item.get("beat_id"), item.get("text"))
            for item in manifest["dialogues"] if isinstance(item, dict)
        }
        for beat_id, beat in beat_by_id.items():
            if beat.get("action") and beat_id not in event_beats:
                _add(findings, "ERROR", "script-event-coverage-missing",
                       f"{beat_id}: 有动作但未建立 EV 事件锁")
            for dialogue in _as_list(beat.get("dialogue")):
                text = dialogue.get("text") if isinstance(dialogue, dict) else dialogue
                if text and (beat_id, text) not in dialogue_locks:
                    _add(findings, "ERROR", "script-dialogue-lock-missing",
                           f"{beat_id}: 台词未在 DLG 中逐字锁定: {text}")
    return findings
