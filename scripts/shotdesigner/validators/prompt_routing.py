"""Route delivery drafts to contract-specific prompt validation."""

from __future__ import annotations

import re
from dataclasses import dataclass

import adapter_config
import validate_seedance_prompt
from shotdesigner.findings import Finding


@dataclass
class RoutingResult:
    findings: list[Finding]
    stop: bool


def validate(workflow, draft_spec, text, *, draft_required):
    findings = []

    def add(severity, code, message):
        findings.append(Finding(
            code=code,
            severity=severity,
            message=message,
            rule_source="config/adapters",
        ))

    prompt_contract = (workflow.get("execution_target") or {}).get("prompt_contract")
    config = adapter_config.by_contract(prompt_contract)
    if config is None:
        if draft_required:
            add("ERROR", "delivery-contract-unresolved",
                "真实交付稿没有已实现的 prompt_contract，不能按可提交稿校验")
        return RoutingResult(findings, stop=True)

    if prompt_contract == "seedance-2.5-direct-v1":
        for item in validate_seedance_prompt.validate_text(text):
            add(item["level"], f"seedance-{item['code']}", item["message"])
        requested_unit_ids = draft_spec.get("unit_ids") if isinstance(draft_spec, dict) else None
        if not isinstance(requested_unit_ids, list) or len(requested_unit_ids) != 1:
            add("ERROR", "seedance-delivery-unit-count",
                "一份 Seedance 2.5 直接模型 Prompt 必须绑定且只绑定一个 unit_id")
            selected_units = []
        else:
            selected_units = [
                unit for unit in workflow.get("units", [])
                if isinstance(unit, dict) and unit.get("unit_id") == requested_unit_ids[0]
            ]
            if not selected_units:
                add("ERROR", "seedance-delivery-unit-unknown",
                    f"Seedance 交付稿绑定未知单元: {requested_unit_ids[0]}")
        image_bindings = sum(
            1 for unit in selected_units
            for binding in unit.get("input_bindings", [])
            if isinstance(binding, dict) and binding.get("media_type") == "image"
        )
        section = re.search(
            r"(?ms)^【素材说明】[ \t]*(.*?)(?=^【[^】]+】|\Z)", text
        )
        declared_images = len(re.findall(
            r"(?m)^\s*@图片\d+\s*[：:]", section.group(1) if section else ""
        ))
        if declared_images != image_bindings:
            add("ERROR", "seedance-binding-count-drift",
                f"Seedance 素材说明图片数={declared_images}，manifest 图片 input_bindings={image_bindings}")
        if re.search(
            r"\bref_(?:image|audio)_\d+\b|<\s*(?:Subject|Picture|Video|Audio)\s+\d+\s*>",
            text,
            re.I,
        ):
            add("ERROR", "seedance-foreign-binding-leak",
                "Seedance 直接模型稿不得包含 H3 标签或 API ref_image/ref_audio 字段")
        return RoutingResult(findings, stop=True)

    if prompt_contract == "minimax-h3-direct-v1" and re.search(
        r"\bref_(?:image|audio)_\d+\b|minimax_h3_zm_u24|autodl", text, re.I
    ):
        add("ERROR", "direct-prompt-api-leak",
            "直接模型交付稿不得包含 AutoDL 参数名、平台名或工作流 ID")
    return RoutingResult(findings, stop=False)
