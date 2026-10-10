"""Index scene maps and camera declarations without validating geometry."""

from __future__ import annotations


def _as_list(value):
    return value if isinstance(value, list) else []


def scene_maps(value):
    if isinstance(value, dict):
        values = []
        for scene_id, scene_map in value.items():
            if isinstance(scene_map, dict):
                item = dict(scene_map)
                item.setdefault("scene_id", scene_id)
                values.append(item)
        return {item.get("scene_id"): item for item in values if item.get("scene_id")}
    return {item.get("scene_id"): item for item in _as_list(value)
            if isinstance(item, dict) and item.get("scene_id")}


def script_scenes(value):
    aliases = {}
    duplicates = set()
    for space_id, scene_map in scene_maps(value).items():
        scene_ids = scene_map.get("scene_ids")
        if not isinstance(scene_ids, list) or not scene_ids:
            scene_ids = [space_id]
        for scene_id in scene_ids:
            if not isinstance(scene_id, str) or not scene_id.strip():
                continue
            if scene_id in aliases and aliases[scene_id] is not scene_map:
                duplicates.add(scene_id)
            aliases[scene_id] = scene_map
    return aliases, duplicates


def cameras(scene_map):
    value = scene_map.get("camera", {}) if isinstance(scene_map, dict) else {}
    if isinstance(value, dict) and "orientation" not in value:
        return value
    return {"camera": value}


def camera_anchor_ids(camera, field):
    result = []
    for entry in _as_list(camera.get(field)):
        if isinstance(entry, dict):
            if entry.get("anchor"):
                result.append(entry["anchor"])
        elif entry:
            result.append(entry)
    return result
