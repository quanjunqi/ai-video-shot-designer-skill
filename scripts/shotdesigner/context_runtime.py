"""Runtime reuse for approved workflow contexts.

This module is deliberately a thin adapter. The project ledger remains the
authority for approvals; this layer only reads or writes derived context
packets and returns a cache index update for the caller to persist.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from .context import (
    ContextError,
    build_context,
    cache_context,
    content_hash,
    resolve_artifact_keys,
)


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _relative(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError as exc:
        raise ContextError(f"context path must stay inside project root: {path}") from exc


def _scope_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._")
    return slug or "scope"


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _fingerprints(ledger: dict[str, Any], keys: list[str]) -> list[dict[str, Any]] | None:
    artifacts = ledger.get("artifacts", {})
    result = []
    for key in keys:
        artifact = artifacts.get(key)
        if not isinstance(artifact, dict) or artifact.get("status") != "USER_APPROVED":
            return None
        result.append({
            "key": key,
            "artifact_id": artifact.get("artifact_id"),
            "version": artifact.get("version"),
            "sha256": artifact.get("sha256"),
        })
    return result


def _load_valid_cached_packet(
    ledger: dict[str, Any], context_type: str, scope_id: str, root: Path,
    request_sha256: str | None, artifact_keys: list[str],
    expected_output_path: str,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    key = f"context:{context_type}:{scope_id}"
    entry = ledger.get("derived_cache", {}).get(key)
    if not isinstance(entry, dict) or entry.get("status") != "VALID":
        return None
    fingerprints = entry.get("input_fingerprints")
    if not isinstance(fingerprints, list):
        return None
    keys = [item.get("key") for item in fingerprints if isinstance(item, dict)]
    if len(keys) != len(fingerprints) or _fingerprints(ledger, keys) != fingerprints:
        return None
    if entry.get("artifact_keys", keys) != sorted(artifact_keys):
        return None
    if entry.get("request_sha256") != request_sha256:
        return None
    raw_path = entry.get("output_path")
    if not isinstance(raw_path, str) or raw_path != expected_output_path:
        return None
    path = root / raw_path
    try:
        _relative(root, path)
    except ContextError:
        return None
    if not path.is_file() or _sha256(path) != entry.get("output_sha256"):
        return None
    try:
        packet = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(packet, dict) or packet.get("context_hash") != entry.get("context_hash"):
        return None
    if packet.get("context_type") != context_type or packet.get("scope_id") != scope_id:
        return None
    return packet, entry


def prepare_context(
    ledger: dict[str, Any], context_type: str, scope_id: str, project_root: str | Path,
    *, artifact_keys: list[str] | None = None, request_path: str | Path | None = None,
    variables: dict[str, str] | None = None, verify_files: bool = True,
    output_path: str | Path | None = None, inspect_only: bool = False,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Return ``(packet, ledger_with_cache, reference)`` for a workflow node.

    A cache hit only reuses the already compiled packet. The caller still
    performs its normal approved-file checks and still creates a user-reviewable
    batch. A request file hash is included because node specs can change even
    when the upstream approved artifacts do not.
    """
    root = Path(project_root).resolve()
    resolved_keys = resolve_artifact_keys(
        context_type, scope_id, variables=variables, artifact_keys=artifact_keys)
    if output_path is None:
        relative_output = Path("derived/contexts") / context_type / f"{_scope_slug(scope_id)}.json"
    else:
        relative_output = Path(output_path)
        if relative_output.is_absolute():
            raise ContextError("context output must be relative to project_root")
    output = root / relative_output
    expected_output_path = _relative(root, output)
    request_sha256 = None
    request_ref = None
    if request_path is not None:
        request = Path(request_path).resolve()
        request_ref = _relative(root, request)
        if not request.is_file():
            raise ContextError(f"context request file is missing: {request_ref}")
        request_sha256 = _sha256(request)

    cached = _load_valid_cached_packet(
        ledger, context_type, scope_id, root, request_sha256, resolved_keys,
        expected_output_path)
    if cached is not None:
        packet, entry = cached
        reference = {
            "context_type": context_type,
            "scope_id": scope_id,
            "context_hash": packet["context_hash"],
            "path": entry["output_path"],
            "cache_hit": True,
            "artifact_keys": resolved_keys,
            "request_sha256": request_sha256,
        }
        return packet, ledger, reference

    packet = build_context(
        ledger, context_type, scope_id, root, variables=variables,
        artifact_keys=resolved_keys, verify_files=verify_files,
    )
    if request_ref is not None:
        packet["request"] = {"path": request_ref, "sha256": request_sha256}
        packet["context_hash"] = content_hash(packet)
    if inspect_only:
        return packet, ledger, {
            "context_type": context_type,
            "scope_id": scope_id,
            "context_hash": packet["context_hash"],
            "path": expected_output_path,
            "cache_hit": False,
            "artifact_keys": resolved_keys,
            "request_sha256": request_sha256,
        }
    _write_json(output, packet)
    output_sha256 = _sha256(output)
    indexed = deepcopy(packet)
    if request_sha256 is not None:
        indexed["request_sha256"] = request_sha256
    updated_ledger = cache_context(
        ledger, indexed, expected_output_path, output_sha256,
    )
    # The request hash is a cache discriminator, not project content.
    cache_entry = updated_ledger["derived_cache"][f"context:{context_type}:{scope_id}"]
    cache_entry["artifact_keys"] = sorted(resolved_keys)
    if request_sha256 is not None:
        cache_entry["request_sha256"] = request_sha256
    reference = {
        "context_type": context_type,
        "scope_id": scope_id,
        "context_hash": packet["context_hash"],
        "path": expected_output_path,
        "cache_hit": False,
        "artifact_keys": resolved_keys,
        "request_sha256": request_sha256,
    }
    return packet, updated_ledger, reference
