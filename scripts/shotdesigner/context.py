"""Compile and cache the minimum approved context required by each node.

The project ledger remains the source of truth for approvals. Context packets
are derived snapshots: they can be reused when their input hash is unchanged,
but they never grant approval and never replace artifact review bindings.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .ledgers.config import context_config


CONTEXT_SCHEMA_VERSION = "1.0"


class ContextError(ValueError):
    """Raised when a context packet cannot be compiled safely."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def context_cache_key(context_type: str, scope_id: str) -> str:
    if not context_type or not scope_id:
        raise ContextError("context_type and scope_id are required")
    return f"context:{context_type}:{scope_id}"


def _resolve_template(template: str, scope_id: str, variables: dict[str, str]) -> str:
    values = {"scope_id": scope_id, **variables}
    try:
        return template.format(**values)
    except KeyError as exc:
        raise ContextError(
            f"context scope is missing template variable: {exc.args[0]}"
        ) from exc


def resolve_artifact_keys(
    context_type: str,
    scope_id: str,
    *,
    variables: dict[str, str] | None = None,
    artifact_keys: list[str] | None = None,
) -> list[str]:
    """Resolve the configured inputs, with an explicit list as an override.

    Most nodes use the configured packet. A small number of nodes, notably
    video generation, have data-dependent inputs (multiple characters or
    looks), so callers may provide the complete resolved list explicitly.
    """
    packets = context_config()["packets"]
    if context_type not in packets:
        raise ContextError(f"unknown context type: {context_type}")
    if artifact_keys is None and context_type in context_config().get("dynamic_contexts", []):
        raise ContextError(
            f"context type requires explicit artifact_keys: {context_type}"
        )
    if artifact_keys is not None:
        templates = list(artifact_keys)
    else:
        templates = [
            _resolve_template(template, scope_id, variables or {})
            for template in packets[context_type]
        ]
    if not templates:
        raise ContextError("context artifact list must not be empty")
    if any(not isinstance(key, str) or not key for key in templates):
        raise ContextError("context artifact list must contain non-empty strings")
    if len(templates) != len(set(templates)):
        raise ContextError("context artifact list contains duplicate keys")
    return templates


def _safe_path(project_root: Path, raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        raise ContextError("artifact paths must be relative to project_root")
    resolved_root = project_root.resolve()
    resolved = (resolved_root / path).resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ContextError("artifact path escapes project_root") from exc
    return resolved


def _file_payload(artifact: dict[str, Any], project_root: Path, verify_files: bool) -> Any:
    path = _safe_path(project_root, artifact["path"])
    if not path.is_file():
        if verify_files:
            raise ContextError(f"artifact file is missing: {artifact['path']}")
        return {"path": artifact["path"], "sha256": artifact["sha256"]}

    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    actual = f"sha256:{digest}"
    if verify_files and actual != artifact["sha256"]:
        raise ContextError(f"artifact file hash mismatch: {artifact['path']}")
    suffix = path.suffix.lower()
    if suffix == ".json":
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            # The ledger binds an approved file by hash; an extension alone is
            # not a reliable schema declaration. Older workflows used .json
            # for user-supplied text or binary placeholders, so preserve those
            # artifacts instead of breaking prompt export.
            try:
                return path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                return {
                    "path": artifact["path"],
                    "media_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                    "sha256": actual,
                }
        except (OSError, UnicodeDecodeError):
            return {
                "path": artifact["path"],
                "media_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                "sha256": actual,
            }
    if suffix in {".md", ".txt", ".yaml", ".yml", ".csv"}:
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return {
                "path": artifact["path"],
                "media_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                "sha256": actual,
            }
    return {
        "path": artifact["path"],
        "media_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        "sha256": actual,
    }


def _input_record(key: str, artifact: dict[str, Any], payload: Any) -> dict[str, Any]:
    return {
        "key": key,
        "artifact_id": artifact["artifact_id"],
        "version": artifact["version"],
        "sha256": artifact["sha256"],
        "path": artifact["path"],
        "payload": payload,
    }


def build_context(
    ledger: dict[str, Any],
    context_type: str,
    scope_id: str,
    project_root: str | Path,
    *,
    variables: dict[str, str] | None = None,
    artifact_keys: list[str] | None = None,
    verify_files: bool = True,
) -> dict[str, Any]:
    """Build a deterministic packet from approved artifacts only."""
    artifacts = ledger.get("artifacts", {})
    root = Path(project_root)
    variables = variables or {}
    records = []
    templates = resolve_artifact_keys(
        context_type, scope_id, variables=variables, artifact_keys=artifact_keys)
    for key in templates:
        artifact = artifacts.get(key)
        if artifact is None:
            raise ContextError(f"required context artifact is missing: {key}")
        if artifact.get("status") != "USER_APPROVED":
            raise ContextError(f"required context artifact is not approved: {key}")
        payload = _file_payload(artifact, root, verify_files)
        records.append(_input_record(key, artifact, payload))

    records.sort(key=lambda item: item["key"])
    context = {
        "schema_version": CONTEXT_SCHEMA_VERSION,
        "context_type": context_type,
        "scope_id": scope_id,
        "inputs": records,
        "facts": {
            "project_id": ledger.get("project_id"),
            "title": ledger.get("title"),
        },
        "decisions": {
            record["key"]: {
                "artifact_id": record["artifact_id"],
                "version": record["version"],
                "sha256": record["sha256"],
            }
            for record in records
        },
        "derived": {"cache_key": context_cache_key(context_type, scope_id)},
    }
    context["context_hash"] = content_hash(context)
    return context


def cache_context(
    ledger: dict[str, Any],
    context: dict[str, Any],
    output_path: str,
    output_sha256: str,
    *,
    now: str | None = None,
) -> dict[str, Any]:
    """Index a compiled packet without copying it into the project ledger."""
    if not output_path or Path(output_path).is_absolute():
        raise ContextError("context cache output_path must be relative")
    if not output_sha256.startswith("sha256:"):
        raise ContextError("context cache output_sha256 must use sha256:<hex>")
    result = deepcopy(ledger)
    key = context_cache_key(context["context_type"], context["scope_id"])
    result.setdefault("derived_cache", {})[key] = {
        "kind": "context",
        "context_type": context["context_type"],
        "scope_id": context["scope_id"],
        "context_hash": context["context_hash"],
        "input_keys": [record["key"] for record in context["inputs"]],
        "input_fingerprints": [
            {
                "key": record["key"],
                "artifact_id": record["artifact_id"],
                "version": record["version"],
                "sha256": record["sha256"],
            }
            for record in context["inputs"]
        ],
        "artifact_keys": sorted(record["key"] for record in context["inputs"]),
        "output_path": output_path,
        "output_sha256": output_sha256,
        "status": "VALID",
        "created_at": now or utc_now(),
    }
    result["updated_at"] = now or utc_now()
    return result


def cached_context_entry(ledger: dict[str, Any], context: dict[str, Any]) -> dict[str, Any] | None:
    """Return a valid index entry only when the current packet hash matches."""
    key = context_cache_key(context["context_type"], context["scope_id"])
    entry = ledger.get("derived_cache", {}).get(key)
    if not isinstance(entry, dict) or entry.get("status") != "VALID":
        return None
    if entry.get("context_hash") != context.get("context_hash"):
        return None
    return entry
