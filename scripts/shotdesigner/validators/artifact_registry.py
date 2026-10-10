"""Validate artifact paths, hashes, and external scene-map evidence."""

from __future__ import annotations

import json
from dataclasses import dataclass

from shotdesigner.findings import Finding


@dataclass
class ArtifactResult:
    findings: list[Finding]
    draft_spec: dict | None = None
    loaded_draft: str | None = None


def validate(workflow, artifact_root, *, state_at_least, resolve_artifact, sha256, scene_map_index):
    findings = []

    def add(severity, code, message, path=None):
        findings.append(Finding(
            code=code,
            severity=severity,
            message=message,
            path=path,
            rule_source="config/workflow/states.json",
        ))

    state = workflow.get("workflow_state")
    maps_required = state_at_least(state, "SPACE_READY")
    draft_required = state_at_least(state, "PROMPTS_VALIDATED")
    artifacts = workflow.get("artifacts")
    if not isinstance(artifacts, dict):
        severity = "ERROR" if maps_required or draft_required else "WARNING"
        add(severity, "artifact-registry-missing",
            "当前 Gate 缺少 artifacts，无法证明真实交付稿或 scene_map 文件未漂移")
        return ArtifactResult(findings)

    draft_spec = artifacts.get("delivery_draft")
    map_specs = artifacts.get("scene_maps")
    map_specs = map_specs if isinstance(map_specs, list) else []
    if draft_required and not isinstance(draft_spec, dict):
        add("ERROR", "delivery-artifact-missing", "artifacts.delivery_draft 必须登记 path 和 sha256")
    if maps_required and not map_specs:
        add("ERROR", "scene-map-artifacts-missing", "artifacts.scene_maps 必须登记外部空间图")
    if artifact_root is None:
        return ArtifactResult(findings, draft_spec if isinstance(draft_spec, dict) else None)

    loaded_draft = None
    if isinstance(draft_spec, dict):
        raw_path = draft_spec.get("path")
        expected_hash = draft_spec.get("sha256")
        if not raw_path or not expected_hash:
            add("ERROR", "delivery-artifact-incomplete", "delivery_draft 缺少 path 或 sha256")
        else:
            try:
                path = resolve_artifact(artifact_root, raw_path)
            except ValueError as exc:
                add("ERROR", "delivery-artifact-path-invalid", f"交付稿路径非法: {exc}", str(raw_path))
                return ArtifactResult(findings, draft_spec)
            if not path.is_file():
                add("ERROR", "delivery-artifact-not-found", f"交付稿不存在: {path}", str(raw_path))
            else:
                actual_hash = sha256(path)
                if actual_hash != expected_hash:
                    add("ERROR", "delivery-artifact-hash-drift",
                        f"交付稿 hash 漂移: manifest={expected_hash}, actual={actual_hash}", str(raw_path))
                loaded_draft = path.read_text(encoding="utf-8")

    embedded_maps = scene_map_index(workflow.get("scene_maps"))
    declared_scene_ids = set()
    for spec in map_specs:
        if not isinstance(spec, dict):
            add("ERROR", "scene-map-artifact-type", "scene_map artifact 必须是对象")
            continue
        scene_id = spec.get("scene_id")
        raw_path = spec.get("path")
        expected_hash = spec.get("sha256")
        if not scene_id or not raw_path or not expected_hash:
            add("ERROR", "scene-map-artifact-incomplete", "scene_map artifact 缺少 scene_id/path/sha256")
            continue
        declared_scene_ids.add(scene_id)
        try:
            path = resolve_artifact(artifact_root, raw_path)
        except ValueError as exc:
            add("ERROR", "scene-map-artifact-path-invalid",
                f"{scene_id}: scene_map 路径非法: {exc}", str(raw_path))
            continue
        if not path.is_file():
            add("ERROR", "scene-map-artifact-not-found",
                f"{scene_id}: 外部 scene_map 不存在: {path}", str(raw_path))
            continue
        actual_hash = sha256(path)
        if actual_hash != expected_hash:
            add("ERROR", "scene-map-artifact-hash-drift",
                f"{scene_id}: scene_map hash 漂移: manifest={expected_hash}, actual={actual_hash}", str(raw_path))
        try:
            external_map = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            add("ERROR", "scene-map-artifact-json",
                f"{scene_id}: 外部 scene_map JSON 非法: {exc}", str(raw_path))
            continue
        if scene_id not in embedded_maps:
            add("ERROR", "scene-map-artifact-unknown", f"{scene_id}: 外部 scene_map 未嵌入 manifest")
        elif external_map != embedded_maps[scene_id]:
            add("ERROR", "scene-map-artifact-drift", f"{scene_id}: 外部 scene_map 与 manifest 内嵌版本不一致")
    missing = set(embedded_maps) - declared_scene_ids
    if missing:
        add("ERROR", "scene-map-artifact-unbound", f"以下内嵌 scene_map 没有文件/hash 绑定: {sorted(missing)}")

    return ArtifactResult(findings, draft_spec if isinstance(draft_spec, dict) else None, loaded_draft)
