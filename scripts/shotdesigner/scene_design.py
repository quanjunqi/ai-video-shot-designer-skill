"""Validate scene masters, coherent view sets, and their spatial handoff."""

from __future__ import annotations

from .provenance import validate_component_basis, validate_provenance


REQUIRED_VIEWS = {"master", "reverse", "left_or_right"}


def validate_scene_functional_brief(value: object, *, allow_legacy: bool = False) -> list[str]:
    if not isinstance(value, dict):
        return ["scene functional brief must be an object"]
    required = ("scene_id", "script_refs", "narrative_functions", "required_actions",
                "blocking_needs", "continuity_anchors", "practical_constraints",
                "visual_implications", "unknowns")
    missing = [field for field in required if field not in value]
    if missing:
        return [f"scene functional brief missing fields: {missing}"]
    errors = [] if all(isinstance(value.get(field), list) for field in required[1:]) else [
        "scene functional brief collections must be arrays"]
    provenance = value.get("provenance")
    if provenance is None and not allow_legacy:
        errors.append("scene.provenance is required for new scene functional briefs")
    elif provenance is not None:
        errors.extend(validate_provenance(provenance, "scene.provenance"))
    implications = value.get("visual_implications")
    if not isinstance(implications, list):
        return errors
    if allow_legacy and all(isinstance(item, str) for item in implications):
        return errors
    for index, item in enumerate(implications, 1):
        label = f"scene.visual_implications[{index}]"
        if not isinstance(item, dict) or not item.get("requirement") or not item.get("rationale"):
            errors.append(f"{label} must contain requirement, basis, basis_ref, and rationale")
            continue
        errors.extend(validate_component_basis(
            item, label, provenance, required_script_domain="scene_appearance"))
        if item.get("basis") == "unresolved":
            errors.append(f"{label}: unresolved scene appearance cannot enter a production Prompt")
    return errors


def validate_scene_requirement(value: object) -> list[str]:
    """Backward-compatible function name for the v3.1 functional brief."""
    return validate_scene_functional_brief(value)


def validate_view_set(value: object, ledger: dict) -> list[str]:
    if not isinstance(value, dict):
        return ["scene view set must be an object"]
    scene_id, views = value.get("scene_id"), value.get("views")
    if not scene_id or not isinstance(views, list):
        return ["scene view set requires scene_id and views"]
    errors = []
    kinds = [item.get("view_type") for item in views if isinstance(item, dict)]
    duplicates = sorted({kind for kind in kinds if kinds.count(kind) > 1 and kind})
    if duplicates:
        errors.append(f"scene view set contains duplicate view types: {duplicates}")
    missing = REQUIRED_VIEWS - set(kinds)
    if missing:
        errors.append(f"scene view set missing required views: {sorted(missing)}")
    master = ledger.get("artifacts", {}).get(f"scene_master:{scene_id}")
    if not master or master.get("status") != "USER_APPROVED":
        errors.append("approved scene_master is required")
    for item in views:
        if not isinstance(item, dict) or not item.get("asset_id") or not item.get("sha256"):
            errors.append("each scene view must bind asset_id and sha256")
            continue
        view_type = item.get("view_type")
        if not master:
            continue
        if item.get("derived_from") != master.get("artifact_id"):
            errors.append(f"{view_type}: view must derive from approved scene master")
        expected = master if view_type == "master" else ledger.get("artifacts", {}).get(
            f"scene_view:{scene_id}:{view_type}")
        if not expected or expected.get("status") != "USER_APPROVED":
            errors.append(f"{view_type}: approved scene view artifact is required")
            continue
        if (item.get("asset_id"), item.get("sha256")) != (
                expected.get("artifact_id"), expected.get("sha256")):
            errors.append(f"{view_type}: view set does not bind the approved artifact version")
    return errors


def validate_scene_map_binding(scene_map: object, view_set: dict) -> list[str]:
    if not isinstance(scene_map, dict):
        return ["scene_map must be an object"]
    errors = []
    if scene_map.get("scene_id") != view_set.get("scene_id"):
        errors.append("scene_map and view set scene_id differ")
    if scene_map.get("source_view_set_id") != view_set.get("view_set_id"):
        errors.append("scene_map must bind the approved source_view_set_id")
    for field in ("space_boundary", "fixed_anchors", "walkable_zones", "objects"):
        if field not in scene_map:
            errors.append(f"scene_map missing {field}")
    return errors
