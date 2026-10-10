"""Pure operations for the compact v3 project ledger snapshot."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any


SCHEMA_VERSION = "3.1"
WORKFLOW_MODE = "co-direct"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_project(project_id: str, title: str, now: str | None = None) -> dict[str, Any]:
    if not project_id or not title:
        raise ValueError("project_id and title are required")
    timestamp = now or utc_now()
    return {
        "schema_version": SCHEMA_VERSION,
        "project_id": project_id,
        "title": title,
        "workflow_mode": WORKFLOW_MODE,
        "current_stage": "SOURCE_READY",
        "scope_registry": {"characters": [], "look_states": [], "scenes": [], "units": []},
        "current_versions": {},
        "artifacts": {},
        "derived_cache": {},
        "pending_reviews": [],
        "blocked_by": [],
        "created_at": timestamp,
        "updated_at": timestamp,
    }


def artifact_key(artifact_type: str, scope_id: str) -> str:
    if not artifact_type or not scope_id:
        raise ValueError("artifact_type and scope_id are required")
    return f"{artifact_type}:{scope_id}"


def register_artifact(
    ledger: dict[str, Any], *, artifact_id: str, artifact_type: str,
    scope_id: str, version: int, sha256: str, path: str,
    depends_on: list[str] | None = None, status: str = "AWAITING_USER",
    now: str | None = None,
) -> dict[str, Any]:
    from .config import dependency_config, review_policy

    if not isinstance(version, int) or version < 1:
        raise ValueError("artifact version must be a positive integer")
    if artifact_type not in dependency_config()["artifact_types"]:
        raise ValueError(f"unsupported artifact_type: {artifact_type}")
    if status not in review_policy()["artifact_statuses"]:
        raise ValueError(f"unsupported artifact status: {status}")
    if status not in {"DRAFT", "AWAITING_USER"}:
        raise ValueError("new artifacts must start as DRAFT or AWAITING_USER")
    if not sha256.startswith("sha256:"):
        raise ValueError("artifact sha256 must use the sha256:<hex> form")
    result = deepcopy(ledger)
    key = artifact_key(artifact_type, scope_id)
    previous = result.setdefault("artifacts", {}).get(key)
    if previous and version <= previous.get("version", 0):
        raise ValueError(f"artifact version must increase for {key}")
    if previous:
        from .dependencies import mark_stale
        result, _ = mark_stale(result, artifact_type, scope_id)
    dependency_keys = list(dict.fromkeys(depends_on or []))
    dependency_versions = {}
    for dependency_key in dependency_keys:
        dependency = result["artifacts"].get(dependency_key)
        if dependency is None:
            raise ValueError(f"unknown dependency artifact: {dependency_key}")
        if dependency.get("status") != "USER_APPROVED":
            raise ValueError(f"dependency artifact is not user-approved: {dependency_key}")
        dependency_versions[dependency_key] = {
            "artifact_id": dependency["artifact_id"], "version": dependency["version"],
            "sha256": dependency["sha256"],
        }
    result["artifacts"][key] = {
        "artifact_id": artifact_id,
        "artifact_type": artifact_type,
        "scope_id": scope_id,
        "version": version,
        "sha256": sha256,
        "path": path,
        "status": status,
        "depends_on": dependency_keys,
        "dependency_versions": dependency_versions,
        "review_id": None,
    }
    pending = [item for item in result.get("pending_reviews", []) if item != key]
    if status == "AWAITING_USER":
        pending.append(key)
    result["pending_reviews"] = pending
    result.setdefault("current_versions", {})[key] = artifact_id
    result["updated_at"] = now or utc_now()
    return result


def apply_review(ledger: dict[str, Any], review: dict[str, Any], now: str | None = None) -> dict[str, Any]:
    result = deepcopy(ledger)
    key = artifact_key(review["artifact_type"], review["scope_id"])
    artifact = result.get("artifacts", {}).get(key)
    if artifact is None:
        raise ValueError(f"review references unknown current artifact: {key}")
    expected = (artifact["artifact_id"], artifact["version"], artifact["sha256"])
    actual = (review["artifact_id"], review["artifact_version"], review["artifact_sha256"])
    if actual != expected:
        raise ValueError(f"review does not bind the current immutable version of {key}")
    artifact["status"] = review["resulting_status"]
    artifact["review_id"] = review["review_id"]
    result["pending_reviews"] = [
        item for item in result.get("pending_reviews", []) if item != key
    ]
    if review["resulting_status"] == "AWAITING_USER":
        result["pending_reviews"].append(key)
    if review["resulting_status"] != "USER_APPROVED":
        from .dependencies import mark_stale
        result, _ = mark_stale(result, review["artifact_type"], review["scope_id"])
    result["updated_at"] = now or utc_now()
    return result
