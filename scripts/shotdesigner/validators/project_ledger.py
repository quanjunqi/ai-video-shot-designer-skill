"""Validate the compact v3 project ledger and review bindings."""

from __future__ import annotations

from pathlib import Path

from ..ledgers.config import dependency_config, review_policy
from ..ledgers.project import SCHEMA_VERSION, WORKFLOW_MODE
from ..ledgers.stages import config as stage_config


def validate_project_ledger(ledger: object, reviews: list[dict] | None = None) -> list[str]:
    errors: list[str] = []
    if not isinstance(ledger, dict):
        return ["project ledger must be an object"]
    if ledger.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    if ledger.get("workflow_mode") != WORKFLOW_MODE:
        errors.append(f"workflow_mode must be {WORKFLOW_MODE}")
    if not ledger.get("project_id"):
        errors.append("project_id is required")
    if ledger.get("current_stage") not in stage_config()["stages"]:
        errors.append("current_stage is not a known co-direct stage")
    registry = ledger.get("scope_registry")
    if not isinstance(registry, dict) or any(not isinstance(registry.get(key), list)
                                             for key in ("characters", "look_states", "scenes", "units")):
        errors.append("scope_registry must define character, look-state, scene, and unit arrays")
    elif any(len(values) != len(set(values)) or any(not item for item in values)
             for values in registry.values()):
        errors.append("scope_registry values must be unique non-empty IDs")
    elif any(look_state.count(":") != 1 or look_state.split(":", 1)[0] not in registry["characters"]
             for look_state in registry["look_states"]):
        errors.append("look-state scopes must use <character_id>:<look_state_id> for a registered character")
    artifacts = ledger.get("artifacts")
    if not isinstance(artifacts, dict):
        return errors + ["artifacts must be an object"]
    derived_cache = ledger.get("derived_cache", {})
    if not isinstance(derived_cache, dict):
        errors.append("derived_cache must be an object")
    else:
        for cache_key, entry in derived_cache.items():
            if not isinstance(cache_key, str) or not isinstance(entry, dict):
                errors.append(f"{cache_key}: cache entry must be an object")
                continue
            if entry.get("kind") != "context":
                errors.append(f"{cache_key}: unsupported cache kind")
            if entry.get("status") != "VALID":
                errors.append(f"{cache_key}: cache status must be VALID")
            for field in ("context_hash", "output_sha256"):
                if not str(entry.get(field, "")).startswith("sha256:"):
                    errors.append(f"{cache_key}: invalid {field}")
            if not isinstance(entry.get("input_keys"), list) or not all(
                    isinstance(item, str) and item for item in entry.get("input_keys", [])):
                errors.append(f"{cache_key}: input_keys must be a list of non-empty strings")
            artifact_keys = entry.get("artifact_keys", entry.get("input_keys"))
            if not isinstance(artifact_keys, list) or artifact_keys != sorted(artifact_keys) or not all(
                    isinstance(item, str) and item for item in artifact_keys):
                errors.append(f"{cache_key}: artifact_keys must be a sorted list of non-empty strings")
            if not isinstance(entry.get("output_path"), str) or not entry.get("output_path"):
                errors.append(f"{cache_key}: output_path is required")
            elif Path(entry["output_path"]).is_absolute():
                errors.append(f"{cache_key}: output_path must be relative")
    policy = review_policy()
    known_types = set(dependency_config()["artifact_types"])
    statuses = set(policy["artifact_statuses"])
    review_by_id = {
        item.get("review_id"): item for item in (reviews or [])
        if isinstance(item, dict) and item.get("review_id")
    }
    for key, artifact in artifacts.items():
        if not isinstance(artifact, dict):
            errors.append(f"{key}: artifact must be an object")
            continue
        expected_key = f"{artifact.get('artifact_type')}:{artifact.get('scope_id')}"
        if key != expected_key:
            errors.append(f"{key}: key does not match type and scope")
        if artifact.get("artifact_type") not in known_types:
            errors.append(f"{key}: unknown artifact_type")
        if not artifact.get("artifact_id") or not artifact.get("path"):
            errors.append(f"{key}: artifact_id and path are required")
        if not isinstance(artifact.get("version"), int) or artifact.get("version", 0) < 1:
            errors.append(f"{key}: version must be a positive integer")
        if artifact.get("status") not in statuses:
            errors.append(f"{key}: invalid status")
        if not str(artifact.get("sha256", "")).startswith("sha256:"):
            errors.append(f"{key}: invalid sha256 binding")
        if artifact.get("status") == "USER_APPROVED":
            review = review_by_id.get(artifact.get("review_id"))
            if review is None:
                errors.append(f"{key}: approved artifact lacks immutable review event")
            elif (review.get("artifact_id"), review.get("artifact_version"),
                  review.get("artifact_sha256")) != (
                      artifact.get("artifact_id"), artifact.get("version"), artifact.get("sha256")):
                errors.append(f"{key}: review does not bind current artifact version")
        snapshots = artifact.get("dependency_versions", {})
        if set(snapshots) != set(artifact.get("depends_on", [])):
            errors.append(f"{key}: dependency version snapshots are incomplete")
        if artifact.get("status") in {"STALE", "SUPERSEDED", "USER_REJECTED"}:
            continue
        for dependency_key, snapshot in snapshots.items():
            current = artifacts.get(dependency_key)
            if current is None:
                errors.append(f"{key}: dependency is missing: {dependency_key}")
            elif current.get("status") != "USER_APPROVED":
                errors.append(f"{key}: dependency is not user-approved: {dependency_key}")
            elif (snapshot.get("artifact_id"), snapshot.get("version"), snapshot.get("sha256")) != (
                    current.get("artifact_id"), current.get("version"), current.get("sha256")):
                errors.append(f"{key}: dependency version is stale: {dependency_key}")
    pending = ledger.get("pending_reviews")
    expected_pending = sorted(
        key for key, artifact in artifacts.items()
        if isinstance(artifact, dict) and artifact.get("status") == "AWAITING_USER"
    )
    if not isinstance(pending, list) or sorted(pending) != expected_pending:
        errors.append("pending_reviews does not match AWAITING_USER artifacts")
    expected_versions = {
        key: artifact.get("artifact_id") for key, artifact in artifacts.items()
        if isinstance(artifact, dict)
    }
    if ledger.get("current_versions") != expected_versions:
        errors.append("current_versions does not match current artifacts")
    return errors
