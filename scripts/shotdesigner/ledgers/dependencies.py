"""Compute scope-aware downstream invalidation without mutating ledgers."""

from __future__ import annotations

from collections import deque

from .config import dependency_config


def _invalidate_cached_contexts(ledger: dict, invalidated_keys: set[str]) -> None:
    cache = ledger.get("derived_cache")
    if not isinstance(cache, dict):
        return
    for key, entry in list(cache.items()):
        if not isinstance(entry, dict):
            continue
        if set(entry.get("input_keys", [])).intersection(invalidated_keys):
            del cache[key]


def downstream_types(artifact_type: str) -> set[str]:
    edges = dependency_config()["edges"]
    seen: set[str] = set()
    queue = deque(edges.get(artifact_type, []))
    while queue:
        current = queue.popleft()
        if current in seen:
            continue
        seen.add(current)
        queue.extend(edges.get(current, []))
    return seen


def affected_artifact_keys(ledger: dict, artifact_type: str, scope_id: str) -> list[str]:
    config = dependency_config()
    types = downstream_types(artifact_type)
    scope_rule = config.get("scope_rules", {}).get(artifact_type, "same_scope")
    affected = set()
    for key, artifact in ledger.get("artifacts", {}).items():
        if artifact.get("artifact_type") not in types:
            continue
        if scope_rule == "project" or artifact.get("scope_id") == scope_id:
            affected.add(key)
        elif scope_rule == "next_unit" and artifact.get("scope_id") != scope_id:
            affected.add(key)

    # Explicit artifact dependencies are authoritative when scopes differ, for
    # example a character look used by a unit-level prompt. Walk them
    # transitively so one upstream replacement invalidates the complete chain.
    frontier = {f"{artifact_type}:{scope_id}"}
    while frontier:
        next_frontier = set()
        for key, artifact in ledger.get("artifacts", {}).items():
            if key in affected:
                continue
            if frontier.intersection(artifact.get("depends_on", [])):
                affected.add(key)
                next_frontier.add(key)
        frontier = next_frontier
    return sorted(affected)


def mark_stale(ledger: dict, artifact_type: str, scope_id: str) -> tuple[dict, list[str]]:
    from copy import deepcopy

    result = deepcopy(ledger)
    affected = affected_artifact_keys(result, artifact_type, scope_id)
    invalidated_keys = set(affected)
    invalidated_keys.add(f"{artifact_type}:{scope_id}")
    for key in affected:
        artifact = result["artifacts"][key]
        if artifact.get("status") != "SUPERSEDED":
            artifact["status"] = "STALE"
            artifact["review_id"] = None
        result["pending_reviews"] = [
            item for item in result.get("pending_reviews", []) if item != key
        ]
    _invalidate_cached_contexts(result, invalidated_keys)
    return result, affected
