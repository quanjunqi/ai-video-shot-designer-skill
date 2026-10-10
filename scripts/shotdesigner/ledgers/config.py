"""Load and validate v3 co-direct ledger configuration."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
CONFIG_DIR = ROOT / "config" / "workflow"


def _load(name: str) -> dict:
    path = CONFIG_DIR / name
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid ledger config {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"ledger config {path} must be an object")
    return value


@lru_cache(maxsize=1)
def review_policy() -> dict:
    policy = _load("review-policy.json")
    statuses = policy.get("artifact_statuses")
    decisions = policy.get("decisions")
    approvals = policy.get("approval_decisions")
    if not isinstance(statuses, list) or len(statuses) != len(set(statuses)):
        raise RuntimeError("artifact_statuses must be a unique list")
    if not isinstance(decisions, list) or len(decisions) != len(set(decisions)):
        raise RuntimeError("decisions must be a unique list")
    if not isinstance(approvals, list) or not set(approvals) <= set(decisions):
        raise RuntimeError("approval_decisions must be a subset of decisions")
    required_reviews = policy.get("required_reviews")
    if not isinstance(required_reviews, list) or len(required_reviews) != len(set(required_reviews)):
        raise RuntimeError("required_reviews must be a unique list")
    compatibility = policy.get("compatibility_only_artifact_types", {})
    if not isinstance(compatibility, dict) or any(
            not isinstance(key, str) or not isinstance(value, str) or not value.strip()
            for key, value in compatibility.items()):
        raise RuntimeError("compatibility_only_artifact_types must map types to explanations")
    if not set(compatibility) <= set(dependency_config()["artifact_types"]):
        raise RuntimeError("compatibility-only artifact type is absent from dependency graph")
    if set(compatibility) & set(required_reviews):
        raise RuntimeError("compatibility-only artifact types cannot be regular required reviews")
    return policy


@lru_cache(maxsize=1)
def dependency_config() -> dict:
    config = _load("dependencies.json")
    edges = config.get("edges")
    if not isinstance(edges, dict) or not all(
            isinstance(key, str) and isinstance(value, list)
            for key, value in edges.items()):
        raise RuntimeError("dependency edges must map artifact types to lists")
    nodes = set(edges)
    nodes.update(target for targets in edges.values() for target in targets)
    for key, targets in edges.items():
        if key in targets:
            raise RuntimeError(f"dependency graph contains a self edge: {key}")
        if len(targets) != len(set(targets)):
            raise RuntimeError(f"dependency graph contains duplicate edges from: {key}")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            raise RuntimeError(f"dependency graph contains a cycle at: {node}")
        if node in visited:
            return
        visiting.add(node)
        for target in edges.get(node, []):
            visit(target)
        visiting.remove(node)
        visited.add(node)

    for node in nodes:
        visit(node)
    config["artifact_types"] = sorted(nodes)
    return config


@lru_cache(maxsize=1)
def context_config() -> dict:
    """Load the node-to-context contract used by the cache compiler."""
    config = _load("context-packets.json")
    packets = config.get("packets")
    if not isinstance(packets, dict) or not packets:
        raise RuntimeError("context packets must be a non-empty object")
    known_types = set(dependency_config()["artifact_types"])
    for context_type, keys in packets.items():
        if not isinstance(context_type, str) or not context_type:
            raise RuntimeError("context packet names must be non-empty strings")
        if not isinstance(keys, list) or not keys:
            raise RuntimeError(f"context packet must be a non-empty list: {context_type}")
        for template in keys:
            if not isinstance(template, str) or ":" not in template:
                raise RuntimeError(f"invalid context artifact template: {context_type}")
            artifact_type = template.split(":", 1)[0]
            if artifact_type not in known_types:
                raise RuntimeError(f"context packet uses unknown artifact type: {artifact_type}")
    dynamic_contexts = config.get("dynamic_contexts", [])
    if not isinstance(dynamic_contexts, list) or any(
            not isinstance(context_type, str) or not context_type.strip()
            for context_type in dynamic_contexts):
        raise RuntimeError("dynamic_contexts must be a list of non-empty strings")
    if len(dynamic_contexts) != len(set(dynamic_contexts)):
        raise RuntimeError("dynamic_contexts must be unique")
    if not set(dynamic_contexts) <= set(packets):
        raise RuntimeError("dynamic context is absent from context packets")
    return config
