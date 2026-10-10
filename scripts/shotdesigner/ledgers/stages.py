"""Validate and advance coarse co-direct stages from approved artifact scopes."""
from __future__ import annotations
import json
from functools import lru_cache
from .config import ROOT, dependency_config, review_policy

@lru_cache(maxsize=1)
def config():
    value = json.loads((ROOT / "config/workflow/co-direct-stages.json").read_text(encoding="utf-8"))
    stages = value.get("stages")
    requirements = value.get("requirements")
    if not isinstance(stages, list) or not stages or len(stages) != len(set(stages)):
        raise RuntimeError("co-direct stages must be a non-empty unique list")
    if not isinstance(requirements, dict) or set(requirements) - set(stages):
        raise RuntimeError("co-direct stage requirements contain unknown stages")
    known_types = set(dependency_config()["artifact_types"])
    unknown_review_types = set(review_policy()["required_reviews"]) - known_types
    if unknown_review_types:
        raise RuntimeError(f"review policy uses unknown artifact types: {sorted(unknown_review_types)}")
    for stage, rules in requirements.items():
        if not isinstance(rules, list):
            raise RuntimeError(f"stage requirements must be a list: {stage}")
        for rule in rules:
            if not isinstance(rule, dict) or rule.get("type") not in known_types:
                raise RuntimeError(f"stage requirement uses unknown artifact type: {stage}")
            if ("scope" in rule) == ("scope_set" in rule):
                raise RuntimeError(f"stage requirement needs exactly one scope selector: {stage}")
    return value

def required_keys(ledger: dict, stage: str) -> list[str]:
    result = []
    for rule in config()["requirements"].get(stage, []):
        scopes = [rule["scope"]] if "scope" in rule else ledger.get("scope_registry", {}).get(rule["scope_set"], [])
        result.extend(f"{rule['type']}:{scope}" for scope in scopes)
    return result

def validate_advance(ledger: dict, target: str) -> list[str]:
    stages = config()["stages"]
    current = ledger.get("current_stage")
    if current not in stages or target not in stages:
        return ["unknown co-direct stage"]
    if stages.index(target) != stages.index(current) + 1:
        return [f"stage advance must be sequential: {current} -> {target}"]
    errors = []
    for key in required_keys(ledger, target):
        artifact = ledger.get("artifacts", {}).get(key)
        if not artifact or artifact.get("status") != "USER_APPROVED":
            errors.append(f"stage {target} requires approved {key}")
    for set_name in ("characters", "look_states", "scenes", "units"):
        if target in {"CAST_READY","LOOKS_READY"} and set_name == "characters" and not ledger.get("scope_registry", {}).get(set_name):
            errors.append("character scope registry is empty")
        if target == "LOOKS_READY" and set_name == "look_states" and not ledger.get("scope_registry", {}).get(set_name):
            errors.append("look-state scope registry is empty")
        if target in {"SCENES_READY","SPACE_READY","BLOCKING_READY"} and set_name == "scenes" and not ledger.get("scope_registry", {}).get(set_name):
            errors.append("scene scope registry is empty")
        if target in {"SHOTS_READY","UNITS_READY","PROMPTS_READY","DELIVERED"} and set_name == "units" and not ledger.get("scope_registry", {}).get(set_name):
            errors.append("unit scope registry is empty")
    return errors
