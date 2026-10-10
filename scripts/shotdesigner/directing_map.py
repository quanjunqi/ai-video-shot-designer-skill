"""Deterministically render movement routes and camera paths from scene_map facts."""

from __future__ import annotations

import xml.etree.ElementTree as ET


def _point(value):
    if isinstance(value, dict) and isinstance(value.get("x"), (int, float)) and isinstance(value.get("y"), (int, float)):
        return float(value["x"]), float(value["y"])
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return float(value[0]), float(value[1])
    return None


def render(scene_map: dict) -> str:
    points = []
    routes = []
    boundary = [_point(item) for item in scene_map.get("space_boundary", {}).get("polygon", [])]
    boundary = [item for item in boundary if item]
    points.extend(boundary)
    for route in scene_map.get("movement_routes", []):
        path = [_point(item) for item in route.get("points", [])]
        path = [item for item in path if item]
        if path: routes.append(("actor", route.get("object_id", "人物"), path)); points.extend(path)
    for route in scene_map.get("camera_paths", []):
        path = [_point(item) for item in route.get("points", [])]
        path = [item for item in path if item]
        if path: routes.append(("camera", route.get("camera_id", "机位"), path)); points.extend(path)
    for item in scene_map.get("fixed_anchors", []) + scene_map.get("objects", []):
        point = _point(item.get("position"))
        if point: points.append(point)
    cameras = scene_map.get("camera", {})
    if isinstance(cameras, dict):
        for item in cameras.values():
            point = _point(item.get("position")) if isinstance(item, dict) else None
            if point:
                points.append(point)
    points = points or [(-1, -1), (1, 1)]
    min_x, max_x = min(x for x, _ in points) - 1, max(x for x, _ in points) + 1
    min_y, max_y = min(y for _, y in points) - 1, max(y for _, y in points) + 1
    def project(p): return (60 + (p[0] - min_x) / max(max_x-min_x, 1) * 780,
                            60 + (max_y - p[1]) / max(max_y-min_y, 1) * 620)
    root = ET.Element("svg", {"xmlns": "http://www.w3.org/2000/svg", "viewBox": "0 0 1000 740"})
    ET.SubElement(root, "rect", {"width":"1000", "height":"740", "fill":"#f7f8f6"})
    ET.SubElement(root, "text", {"x":"60", "y":"35", "font-size":"22"}).text = f"导演调度图 · {scene_map.get('scene_id')}"
    defs = ET.SubElement(root, "defs")
    for ident, color in (("actor-arrow", "#26734d"), ("camera-arrow", "#b33b32")):
        marker = ET.SubElement(defs, "marker", {"id":ident,"markerWidth":"8","markerHeight":"8","refX":"7","refY":"4","orient":"auto"})
        ET.SubElement(marker, "path", {"d":"M0,0 L8,4 L0,8 z", "fill":color})
    if len(boundary) >= 3:
        projected = [project(item) for item in boundary]
        ET.SubElement(root, "polygon", {
            "points": " ".join(f"{x:.1f},{y:.1f}" for x, y in projected),
            "fill": "#ffffff", "stroke": "#4d5552", "stroke-width": "4",
        })
    for collection, id_field, color, radius in (
            ("fixed_anchors", "anchor_id", "#315b7d", "7"),
            ("objects", "object_id", "#6b5a2d", "9")):
        for item in scene_map.get(collection, []):
            point = _point(item.get("position")) if isinstance(item, dict) else None
            if not point:
                continue
            x, y = project(point)
            ET.SubElement(root, "circle", {"cx":f"{x:.1f}", "cy":f"{y:.1f}",
                "r":radius, "fill":color, "stroke":"#ffffff", "stroke-width":"2"})
            ET.SubElement(root, "text", {"x":f"{x+11:.1f}", "y":f"{y+5:.1f}",
                "font-size":"13", "fill":color}).text = str(item.get(id_field, "未命名"))
    if isinstance(cameras, dict):
        for camera_id, item in cameras.items():
            point = _point(item.get("position")) if isinstance(item, dict) else None
            if not point:
                continue
            x, y = project(point)
            ET.SubElement(root, "rect", {"x":f"{x-7:.1f}", "y":f"{y-7:.1f}",
                "width":"14", "height":"14", "fill":"#b33b32", "stroke":"#ffffff"})
            ET.SubElement(root, "text", {"x":f"{x+11:.1f}", "y":f"{y+5:.1f}",
                "font-size":"13", "fill":"#b33b32"}).text = str(camera_id)
    for kind, label, path in routes:
        color = "#26734d" if kind == "actor" else "#b33b32"
        projected = [project(item) for item in path]
        ET.SubElement(root, "polyline", {"points":" ".join(f"{x:.1f},{y:.1f}" for x,y in projected),
            "fill":"none", "stroke":color, "stroke-width":"4", "stroke-dasharray":"8 5" if kind=="camera" else "none",
            "marker-end":f"url(#{kind}-arrow)"})
        x, y = projected[0]
        ET.SubElement(root, "text", {"x":str(x+8),"y":str(y-8),"font-size":"14","fill":color}).text = label
    ET.SubElement(root, "text", {"x":"870","y":"90","font-size":"14","fill":"#26734d"}).text = "实线：人物走位"
    ET.SubElement(root, "text", {"x":"870","y":"118","font-size":"14","fill":"#b33b32"}).text = "虚线：摄影机运动"
    ET.SubElement(root, "text", {"x":"870","y":"146","font-size":"14","fill":"#315b7d"}).text = "蓝点：固定锚点"
    ET.SubElement(root, "text", {"x":"870","y":"174","font-size":"14","fill":"#6b5a2d"}).text = "棕点：人物/物件"
    ET.SubElement(root, "text", {"x":"870","y":"690","font-size":"12"}).text = "由 scene_map 确定性生成"
    return ET.tostring(root, encoding="unicode")


def validate_routes(scene_map: dict) -> list[str]:
    errors = []
    state_positions = {}
    for state in (scene_map.get("blocking_states") or {}).values():
        for object_id, item in (state.get("objects", {}) if isinstance(state, dict) else {}).items():
            point = _point(item.get("position") if isinstance(item, dict) else None)
            if point:
                state_positions.setdefault(object_id, set()).add(point)
    moved_objects = {object_id for object_id, positions in state_positions.items() if len(positions) > 1}
    routed_objects = {item.get("object_id") for item in scene_map.get("movement_routes", [])
                      if isinstance(item, dict)}
    if moved_objects - routed_objects:
        errors.append(f"moved objects require movement_routes: {sorted(moved_objects - routed_objects)}")
    cameras = scene_map.get("camera", {})
    moving_ids = {camera_id for camera_id, item in (cameras.items() if isinstance(cameras, dict) else [])
                  if isinstance(item, dict) and item.get("movement") not in (None, "static", "locked")}
    routed_cameras = {item.get("camera_id") for item in scene_map.get("camera_paths", [])
                      if isinstance(item, dict)}
    if moving_ids - routed_cameras:
        errors.append(f"moving cameras require camera_paths: {sorted(moving_ids - routed_cameras)}")
    for collection in ("movement_routes", "camera_paths"):
        for item in scene_map.get(collection, []):
            if not isinstance(item, dict) or len([p for p in item.get("points", []) if _point(p)]) < 2:
                errors.append(f"{collection} route requires at least two points")
    return errors
