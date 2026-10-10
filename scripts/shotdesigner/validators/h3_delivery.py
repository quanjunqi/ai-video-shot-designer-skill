"""Validate H3 delivery envelope and return unit/block contexts."""

from __future__ import annotations

import re
from dataclasses import dataclass

from shotdesigner.findings import Finding


@dataclass
class H3Context:
    unit: dict
    block: str
    shot_sections: dict[int, str]


@dataclass
class H3Result:
    findings: list[Finding]
    contexts: list[H3Context]


def blocks(text):
    return [
        match.group(1)
        for match in re.finditer(r"```[A-Za-z0-9_-]*\r?\n(.*?)```", text, re.S)
        if re.search(r"(?m)^subject_definitions\s*:", match.group(1))
    ]


def field(block, name):
    match = re.search(rf"(?ms)^{re.escape(name)}\s*:\s*(.*?)(?=^[a-z_]+\s*:|\Z)", block)
    return match.group(1).strip() if match else ""


def shot_sections(block):
    detail = field(block, "detailed_description")
    matches = list(re.finditer(r"\[Shot\s+(\d+)\]", detail))
    return {
        int(match.group(1)): detail[match.start(): matches[index + 1].start() if index + 1 < len(matches) else len(detail)]
        for index, match in enumerate(matches)
    }


def validate(workflow, draft_spec, text):
    findings = []

    def add(code, message):
        findings.append(Finding(
            code=code,
            severity="ERROR",
            message=message,
            rule_source="references/adapters/minimax-h3.md",
        ))

    prompt_contract = (workflow.get("execution_target") or {}).get("prompt_contract")
    prompt_blocks = blocks(text)
    ordered_units = sorted(
        [unit for unit in workflow.get("units", [])
         if isinstance(unit, dict) and isinstance(unit.get("unit_order"), int)],
        key=lambda item: item["unit_order"],
    )
    requested = draft_spec.get("unit_ids") if isinstance(draft_spec, dict) else None
    if requested is not None:
        if not isinstance(requested, list) or not requested or not all(
            isinstance(unit_id, str) and unit_id for unit_id in requested
        ):
            add("delivery-artifact-unit-ids-invalid",
                "delivery_draft.unit_ids 必须是非空字符串数组")
            return H3Result(findings, [])
        if len(set(requested)) != len(requested):
            add("delivery-artifact-unit-ids-duplicate", "delivery_draft.unit_ids 不得重复")
            return H3Result(findings, [])
        unit_by_id = {unit.get("unit_id"): unit for unit in ordered_units}
        unknown = [unit_id for unit_id in requested if unit_id not in unit_by_id]
        if unknown:
            add("delivery-artifact-unit-ids-unknown",
                f"delivery_draft.unit_ids 含未知单元: {unknown}")
            return H3Result(findings, [])
        selected = [unit for unit in ordered_units if unit.get("unit_id") in set(requested)]
        selected_ids = [unit.get("unit_id") for unit in selected]
        if selected_ids != requested:
            add("delivery-artifact-unit-order-drift",
                f"delivery_draft.unit_ids 必须按 unit_order 排列，应为 {selected_ids}")
            return H3Result(findings, [])
        ordered_units = selected
    if len(prompt_blocks) != len(ordered_units):
        add("delivery-h3-unit-count-drift",
            f"交付稿 H3 块数={len(prompt_blocks)}，manifest 单元数={len(ordered_units)}")
        return H3Result(findings, [])

    style_lock = workflow.get("project_style_lock")
    if str(workflow.get("schema_version")) == "2.2" and (
        not isinstance(style_lock, str) or not style_lock.strip()
    ):
        add("project-style-lock-missing", "v2 manifest 必须登记完整 project_style_lock，不得只写 STYLE ID")
    contexts = []
    for unit, block in zip(ordered_units, prompt_blocks):
        image_index = 0
        audio_index = 0
        for binding in unit.get("input_bindings", []):
            if not isinstance(binding, dict):
                continue
            media_type = binding.get("media_type")
            if media_type == "image":
                api_field = f"ref_image_{image_index}"
                image_index += 1
            elif media_type == "audio":
                api_field = f"ref_audio_{audio_index}"
                audio_index += 1
            else:
                continue
            if prompt_contract == "autodl-minimax-h3-v1":
                count = len(re.findall(rf"\b{re.escape(api_field)}\b", block))
                if count != 1:
                    add("autodl-binding-count-drift",
                        f"{unit.get('unit_id')}: {api_field} 必须在对应 H3 块中恰好出现一次，当前={count}")
                slot = binding.get("slot")
                definition = field(block, "subject_definitions")
                if slot and not re.search(
                    rf"(?m)^\s*{re.escape(slot)}[^\n]*\b{re.escape(api_field)}\b", definition
                ):
                    add("autodl-binding-slot-drift",
                        f"{unit.get('unit_id')}: {api_field} 未在 {slot} 的定义行绑定")
        if style_lock and style_lock not in field(block, "summary"):
            add("delivery-style-lock-drift",
                f"{unit.get('unit_id')}: H3 summary 未逐字包含 project_style_lock")
        sections = shot_sections(block)
        actual_numbers = list(sections)
        expected_numbers = unit.get("h3_shot_numbers", [])
        if actual_numbers != expected_numbers:
            add("delivery-h3-shot-drift",
                f"{unit.get('unit_id')}: 真实 H3 镜号 {actual_numbers} 与 manifest {expected_numbers} 不一致")
        contexts.append(H3Context(unit, block, sections))
    return H3Result(findings, contexts)
