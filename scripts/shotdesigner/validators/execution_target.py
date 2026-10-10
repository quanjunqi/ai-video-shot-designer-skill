"""Validate execution-target routing without depending on the workflow CLI."""

from __future__ import annotations

import adapter_config
from shotdesigner.findings import Finding


REQUIRED_FIELDS = (
    "delivery_method", "target_model", "prompt_contract", "confirmation",
    "contract_source", "contract_verified_at",
)


def _finding(code, message):
    return Finding(
        code=code,
        severity="ERROR",
        message=message,
        rule_source="config/adapters",
    )


def validate(workflow, state_at_least):
    state = workflow.get("workflow_state")
    if not state_at_least(state, "ASSETS_READY"):
        return [], None
    findings = []
    target = workflow.get("execution_target")
    if not isinstance(target, dict):
        return [_finding(
            "execution-target-missing",
            "进入 ASSETS_READY 前必须由用户确认交付方式、目标模型及 API 平台（如适用）",
        )], None
    missing = [
        field for field in REQUIRED_FIELDS
        if field not in target or target.get(field) in (None, "")
    ]
    if missing:
        findings.append(_finding(
            "execution-target-incomplete", f"execution_target 缺少字段: {missing}"))
    method = target.get("delivery_method")
    model = target.get("target_model")
    platform = target.get("api_platform")
    contract = target.get("prompt_contract")
    if method not in {"model", "api"}:
        findings.append(_finding(
            "execution-method-invalid", "execution_target.delivery_method 必须是 model 或 api"))
    if method == "model" and platform is not None:
        findings.append(_finding(
            "execution-platform-unexpected", "直接模型交付的 api_platform 必须为 null"))
    if method == "api" and not platform:
        findings.append(_finding(
            "execution-platform-missing", "API 交付必须确认 api_platform，不能默认使用 AutoDL"))
    confirmation = target.get("confirmation")
    if not isinstance(confirmation, dict) or confirmation.get("confirmed_by") != "user" or not all(
        confirmation.get(field) for field in ("statement", "confirmed_at")
    ):
        findings.append(_finding(
            "execution-target-unconfirmed",
            "execution_target.confirmation 必须保留用户原话、confirmed_by=user 和确认时间",
        ))
    config = adapter_config.resolve(method, model, platform)
    if config is None:
        if contract != "unresolved":
            findings.append(_finding(
                "execution-contract-invented",
                "尚未实现的模型或 API 平台只能登记 prompt_contract=unresolved",
            ))
        if state_at_least(state, "PROMPTS_VALIDATED"):
            findings.append(_finding(
                "execution-target-unsupported",
                "当前执行目标没有已实现且核实的提示词适配器，不能进入 PROMPTS_VALIDATED",
            ))
    else:
        expected = config["prompt_contract"]
        if contract != expected:
            findings.append(_finding(
                "execution-contract-mismatch",
                f"当前组合必须使用 prompt_contract={expected}，实际={contract!r}",
            ))
        if method == "api" and target.get("adapter_id") != config["adapter_id"]:
            findings.append(_finding(
                "execution-adapter-mismatch",
                f"{platform} / {model} 必须锁定 adapter_id={config['adapter_id']}",
            ))
    return findings, contract
