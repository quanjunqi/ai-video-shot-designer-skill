"""Validate immutable script-to-unit coverage and render user shooting manuscripts."""

from __future__ import annotations

import hashlib
from pathlib import Path


STATE_LABELS = {
    "location": "地点",
    "wangli": "王力",
    "wangli_character": "王力操控角色",
    "computer": "电脑",
    "phone": "手机",
    "props": "道具",
    "caption": "字幕",
    "screen": "屏幕",
    "chat": "聊天",
    "selection": "英雄选择",
    "game_result": "游戏结果",
    "match_history": "比赛前情",
    "voice": "声音",
    "group": "群聊",
    "group_messages": "群消息",
    "hands": "手部",
    "input": "输入框",
    "desk": "桌面",
    "sound": "声音环境",
    "closing_image": "结尾画面",
}


def _entries(manifest: dict) -> dict[str, dict]:
    result = {}
    for kind, id_field in (("event", "event_id"), ("dialogue", "dialogue_id")):
        for item in manifest.get(f"{kind}s", []):
            if isinstance(item, dict) and item.get(id_field):
                result[item[id_field]] = {**item, "entry_type": kind}
    return result


def validate_script_sequence(manifest: object) -> list[str]:
    if not isinstance(manifest, dict):
        return ["script_manifest must be an object"]
    entries = _entries(manifest)
    sequence = manifest.get("sequence")
    if not isinstance(sequence, list):
        return ["script_manifest.sequence must be an array"]
    errors = []
    changes = manifest.get("authorized_changes")
    if changes:
        errors.append("v3 locked script forbids authorized_changes; submit a new user script version")
    if any(not isinstance(item, str) or not item for item in sequence):
        errors.append("script_manifest.sequence may contain only non-empty IDs")
    if len(sequence) != len(set(sequence)):
        errors.append("script_manifest.sequence contains duplicate IDs")
    unknown = [item for item in sequence if item not in entries]
    missing = sorted(set(entries) - set(sequence))
    if unknown:
        errors.append(f"script_manifest.sequence contains unknown IDs: {unknown}")
    if missing:
        errors.append(f"script_manifest.sequence omits locked entries: {missing}")
    return errors


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def validate_source_script(source: object, root: Path) -> list[str]:
    if not isinstance(source, dict):
        return ["source_script must bind the immutable user script file"]
    relative = source.get("path")
    expected = source.get("sha256")
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
        return ["source_script.path must be case-relative"]
    path = root / relative
    if not path.is_file():
        return [f"source script file not found: {relative}"]
    actual = sha256_file(path)
    if expected != actual:
        return ["source script sha256 mismatch; create a new script version instead of overwriting"]
    return []


def validate_unit_coverage(manifest: object, units: object) -> list[str]:
    errors = validate_script_sequence(manifest)
    if errors:
        return errors
    if not isinstance(units, list) or not units:
        return errors + ["units must be a non-empty array"]
    sequence = manifest["sequence"]
    ordered = []
    for index, unit in enumerate(units, 1):
        if not isinstance(unit, dict):
            errors.append(f"units[{index - 1}] must be an object")
            continue
        if unit.get("unit_order") != index:
            errors.append(f"{unit.get('unit_id', index)}: unit_order must be contiguous from 1")
        refs = unit.get("script_refs")
        if not isinstance(refs, list) or not refs:
            errors.append(f"{unit.get('unit_id', index)}: script_refs must be non-empty")
            continue
        ordered.extend(refs)
    if ordered != sequence:
        missing = [item for item in sequence if item not in ordered]
        duplicates = sorted({item for item in ordered if ordered.count(item) > 1})
        unknown = [item for item in ordered if item not in sequence]
        if missing:
            errors.append(f"unit coverage omits script entries: {missing}")
        if duplicates:
            errors.append(f"unit coverage duplicates script entries: {duplicates}")
        if unknown:
            errors.append(f"unit coverage contains unknown entries: {unknown}")
        if not (missing or duplicates or unknown):
            errors.append("unit coverage changes the original script order")
    return errors


def _state_text(value: object) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, dict) and value:
        return "；".join(
            f"{STATE_LABELS.get(key, key)}：{value[key]}" for key in sorted(value)
        )
    return "未登记"


def render_unit_manuscript(manifest: dict, unit: dict) -> str:
    entries = _entries(manifest)
    refs = unit.get("script_refs", [])
    continuity = unit.get("continuity") or {}
    entry_state = unit.get("entry_state") or continuity.get("in")
    exit_state = unit.get("exit_state") or continuity.get("out")
    lines = [
        f"# 生成单元 {unit.get('unit_id', '<unknown>')}",
        "",
        f"预计时长：{unit.get('generation_duration_seconds', '未定')} 秒",
        f"原剧本范围：{refs[0] if refs else '未登记'} 至 {refs[-1] if refs else '未登记'}",
        "",
        "## 开始状态",
        "",
        _state_text(entry_state),
        "",
        "## 本单元拍摄内容",
        "",
    ]
    for number, ref_id in enumerate(refs, 1):
        entry = entries.get(ref_id, {})
        if entry.get("entry_type") == "dialogue":
            modality = entry.get("modality")
            speaker = entry.get("speaker_id")
            label = f"{speaker}（{modality}）" if modality else speaker
            lines.append(f"{number}. [{ref_id}] {label}：{entry.get('text')}")
        else:
            lines.append(f"{number}. [{ref_id}] {entry.get('fact', '未登记事件')}")
    lines.extend([
        "",
        "## 结束状态",
        "",
        _state_text(exit_state),
    ])
    if unit.get("boundary_reason"):
        lines.extend(["", "## 切分理由", "", str(unit["boundary_reason"])])
    handoff = unit.get("handoff")
    if isinstance(handoff, dict) and handoff.get("to_next"):
        lines.extend(["", "## 详细承接", "", str(handoff["to_next"])])
    lines.extend([
        "",
        "## 单元承接",
        "",
        f"上一单元：{unit.get('previous_unit_id') or '无'}",
        f"下一单元：{unit.get('next_unit_id') or '无'}",
        "",
        "> 本稿直接引用锁定剧本条目，仅用于展示技术拆分，不构成删减、改写或补写。",
        "",
    ])
    return "\n".join(lines)


def sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def validate_manuscript_files(manifest: dict, units: list[dict], root: Path) -> list[str]:
    errors = []
    for unit in units:
        unit_id = unit.get("unit_id", "<unknown>")
        evidence = unit.get("shooting_manuscript")
        if not isinstance(evidence, dict):
            errors.append(f"{unit_id}: shooting_manuscript evidence is required")
            continue
        relative = evidence.get("path")
        if not isinstance(relative, str) or not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
            errors.append(f"{unit_id}: shooting_manuscript.path must be case-relative")
            continue
        path = root / relative
        if not path.is_file():
            errors.append(f"{unit_id}: shooting manuscript file not found: {relative}")
            continue
        actual = path.read_text(encoding="utf-8")
        expected = render_unit_manuscript(manifest, unit)
        if actual != expected:
            errors.append(f"{unit_id}: shooting manuscript differs from locked script projection")
        digest = sha256_text(actual)
        if evidence.get("sha256") != digest:
            errors.append(f"{unit_id}: shooting manuscript sha256 mismatch")
    return errors
