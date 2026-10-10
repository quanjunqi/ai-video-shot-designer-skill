#!/usr/bin/env python3
"""Validate the reusable scene/object/camera spatial continuity contract.

两层校验：

1. 结构层（原有）：scene_map 必备字段、对象身份分类、剧情车辆专用字段、
   摄影机/对象引用的锚点必须先定义。
2. 空间因果层（新增）：当固定锚点带坐标、摄影机带坐标与朝向时，做确定性
   方位推导——计算每个“可见锚点”相对机位的方位角，判断它是否落在视锥内，
   以及在车内镜头里它应当从哪一扇车窗看到。车头朝向决定前挡/后挡/左右窗
   的方位扇区，因此“把侧后方的出口画进前挡风”这类场面调度因果错误会被
   直接判 ERROR，而不是靠人眼事后发现。

只依赖标准库；核心为可 import 的纯函数，便于单测。缺少坐标时空间因果层
跳过（不报错），保持对旧 scene_map 的向后兼容。
"""

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path


REQUIRED_OBJECT_FIELDS = ("object_id", "object_type", "position", "orientation", "state", "relations")
REQUIRED_CAMERA_FIELDS = ("position", "placement", "side", "orientation", "visible_anchors")
KNOWN_ROLES = {"story-object", "fixed-anchor-object", "incidental-object"}
VEHICLE_WINDOWS = ("windshield", "rear_window", "left_window", "right_window")
# 车内镜头默认水平视锥半角（总视场约 150°，覆盖驾驶员与侧窗）。
DEFAULT_INSIDE_FOV_HALF = 80.0
# 一扇车窗方位扇区的半角；前/后挡窄、侧窗宽。
WINDOW_HALF_WIDTH = {"windshield": 55.0, "rear_window": 55.0,
                     "left_window": 90.0, "right_window": 90.0}
SCREEN_SIDES = {"left", "center", "right"}
DEFAULT_SCREEN_CENTER_TOLERANCE = 5.0


def _camera_review_facts(scene_map):
    cameras = scene_map.get("camera", {})
    if isinstance(cameras, dict) and "orientation" not in cameras:
        items = sorted(cameras.items())
    else:
        items = [("camera", cameras)]
    fields = ("position", "side", "orientation", "blocking_state_id", "visible_anchors")
    return {
        camera_id: {field: camera.get(field) for field in fields if field in camera}
        for camera_id, camera in items
        if isinstance(camera, dict)
    }


def scene_review_signature(scene_map, review_type="layout"):
    """Hash one user-facing projection without mixing planning stages."""
    if review_type not in {"layout", "camera_plan"}:
        raise ValueError(f"unknown review_type: {review_type}")
    review = scene_map.get("user_review", {})
    state_sequence = review.get("state_sequence", []) if isinstance(review, dict) else []
    ordered_state_ids = []
    for entry in state_sequence if isinstance(state_sequence, list) else []:
        state_id = entry if isinstance(entry, str) else entry.get("state_id") if isinstance(entry, dict) else None
        if state_id:
            ordered_state_ids.append(state_id)
    blocking_states = scene_map.get("blocking_states", {})
    if not ordered_state_ids and isinstance(blocking_states, dict):
        ordered_state_ids = list(blocking_states)
    selected_states = {
        state_id: blocking_states[state_id]
        for state_id in ordered_state_ids
        if isinstance(blocking_states, dict) and state_id in blocking_states
    }
    payload = {
        "scene_id": scene_map.get("scene_id"),
        "primary_axis": scene_map.get("primary_axis"),
        "space_boundary": scene_map.get("space_boundary"),
        "fixed_anchors": scene_map.get("fixed_anchors", []),
        "walkable_zones": scene_map.get("walkable_zones", []),
        "occupancy_zones": scene_map.get("occupancy_zones", []),
        "movement_routes": scene_map.get("movement_routes", []),
        "objects": scene_map.get("objects", []),
        "state_sequence": ordered_state_ids,
        "blocking_states": selected_states,
        "user_visible_rules": review.get("user_visible_rules", []) if isinstance(review, dict) else [],
    }
    if review_type == "camera_plan":
        payload = {
            "scene_id": scene_map.get("scene_id"),
            "layout_signature": scene_review_signature(scene_map, "layout"),
            "camera_review_facts": _camera_review_facts(scene_map),
        }
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


# --------------------------------------------------------------------------- #
# 几何纯函数：坐标 x=东向+, y=北向+；方位角为自正北顺时针的罗盘角度(0=N,90=E)
# --------------------------------------------------------------------------- #
def compass_bearing(p, q):
    """从点 p 看向点 q 的罗盘方位角（度，0=北，顺时针）。"""
    dx = float(q["x"]) - float(p["x"])
    dy = float(q["y"]) - float(p["y"])
    return (math.degrees(math.atan2(dx, dy)) + 360.0) % 360.0


def angular_delta(a, b):
    """两个方位角之间的最小夹角，结果在 [0,180]。"""
    diff = (float(b) - float(a)) % 360.0
    if diff > 180.0:
        diff = 360.0 - diff
    return diff


def signed_angular_offset(facing, target_bearing):
    """Target offset in camera space: negative=screen left, positive=right."""
    return (float(target_bearing) - float(facing) + 180.0) % 360.0 - 180.0


def screen_side(facing, target_bearing, tolerance=DEFAULT_SCREEN_CENTER_TOLERANCE):
    offset = signed_angular_offset(facing, target_bearing)
    if abs(offset) <= float(tolerance):
        return "center"
    return "right" if offset > 0 else "left"


def vehicle_window_bearings(front_bearing):
    """由车头方位推导四扇车窗中心方位：左舵/右舵不改变前后窗，只交换左右。"""
    front = float(front_bearing) % 360.0
    return {
        "windshield": front,
        "rear_window": (front + 180.0) % 360.0,
        # 面朝车头方向时，车体左侧在 front-90，右侧在 front+90。
        "left_window": (front - 90.0) % 360.0,
        "right_window": (front + 90.0) % 360.0,
    }


def window_for_bearing(front_bearing, target_bearing):
    """判断某个相对车体的目标方位落在哪扇车窗；不在任何扇区返回 None。"""
    centers = vehicle_window_bearings(front_bearing)
    best, best_delta = None, 181.0
    for window, center in centers.items():
        delta = angular_delta(center, target_bearing)
        if delta <= WINDOW_HALF_WIDTH[window] and delta < best_delta:
            best, best_delta = window, delta
    return best


def _as_coords(value):
    # 统一坐标口径：接受 {x,y} 或 [x,y]；旧字段 pos 与新字段 position 都走这里。
    if isinstance(value, dict) and "x" in value and "y" in value:
        return {"x": float(value["x"]), "y": float(value["y"])}
    if isinstance(value, (list, tuple)) and len(value) == 2 \
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value):
        return {"x": float(value[0]), "y": float(value[1])}
    return None


def _entity_coords(entity):
    """取一个实体（锚点/对象/机位）的数值坐标；优先 position，兼容旧 pos。文字描述返回 None。"""
    if not isinstance(entity, dict):
        return None
    return _as_coords(entity.get("position")) or _as_coords(entity.get("pos"))


def _as_bearing(value):
    """把朝向解释为罗盘方位角（0-360 数值）；文字描述/None 返回 None。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) % 360.0


def _polygon_points(value):
    if not isinstance(value, list) or len(value) < 3:
        return None
    points = [_as_coords(point) for point in value]
    return points if all(point is not None for point in points) else None


def _point_on_segment(point, start, end, tolerance=1e-9):
    cross = ((point["y"] - start["y"]) * (end["x"] - start["x"])
             - (point["x"] - start["x"]) * (end["y"] - start["y"]))
    if abs(cross) > tolerance:
        return False
    return (min(start["x"], end["x"]) - tolerance <= point["x"]
            <= max(start["x"], end["x"]) + tolerance
            and min(start["y"], end["y"]) - tolerance <= point["y"]
            <= max(start["y"], end["y"]) + tolerance)


def point_in_polygon(point, polygon):
    """Return True for points inside or on the boundary of a simple polygon."""
    points = _polygon_points(polygon)
    coords = _as_coords(point)
    if points is None or coords is None:
        return False
    inside = False
    previous = points[-1]
    for current in points:
        if _point_on_segment(coords, previous, current):
            return True
        crosses = ((current["y"] > coords["y"]) != (previous["y"] > coords["y"]))
        if crosses:
            x_at_y = ((previous["x"] - current["x"])
                      * (coords["y"] - current["y"])
                      / (previous["y"] - current["y"]) + current["x"])
            if coords["x"] < x_at_y:
                inside = not inside
        previous = current
    return inside


def _inside_any(point, polygons):
    return any(point_in_polygon(point, polygon) for polygon in polygons)


def _segment_samples(start, end, steps=24):
    return [
        {
            "x": start["x"] + (end["x"] - start["x"]) * index / steps,
            "y": start["y"] + (end["y"] - start["y"]) * index / steps,
        }
        for index in range(steps + 1)
    ]


def _polyline_samples(points):
    samples = []
    for start, end in zip(points, points[1:]):
        samples.extend(_segment_samples(start, end))
    return samples


def _camera_bearing(camera):
    """机位朝向：优先数值 orientation（统一口径），兼容旧 orientation_bearing。"""
    return _as_bearing(camera.get("orientation")) if _as_bearing(camera.get("orientation")) is not None \
        else _as_bearing(camera.get("orientation_bearing"))


def _vehicle_front(obj):
    """车头方位：front_bearing / 数值 front_direction / 数值 orientation 任一即可。"""
    for key in ("front_bearing", "front_direction", "orientation"):
        bearing = _as_bearing(obj.get(key))
        if bearing is not None:
            return bearing
    return None


def _field_missing(entity, field):
    # 键缺失或显式 None 才算缺字段；允许空列表/空字典/空串表示“刻意为空”。
    return field not in entity or entity.get(field) is None


def _blocking_state(scene_map, state_id):
    states = scene_map.get("blocking_states", {})
    if not state_id or not isinstance(states, dict):
        return None
    state = states.get(state_id)
    return state if isinstance(state, dict) else None


def _anchor_positions(scene_map, state_id=None):
    positions = {}
    for anchor in scene_map.get("fixed_anchors", []):
        if isinstance(anchor, dict) and anchor.get("anchor_id"):
            coords = _entity_coords(anchor)
            if coords:
                positions[anchor["anchor_id"]] = coords
    for obj in scene_map.get("objects", []):
        if isinstance(obj, dict) and obj.get("object_id"):
            coords = _entity_coords(obj)
            if coords:
                positions[obj["object_id"]] = coords
    state = _blocking_state(scene_map, state_id)
    state_objects = state.get("objects", {}) if state else {}
    if isinstance(state_objects, dict):
        for object_id, override in state_objects.items():
            coords = _entity_coords(override)
            if coords:
                positions[object_id] = coords
    return positions


def _iter_visible_entries(visible_anchors):
    """visible_anchors 兼容纯字符串与 {anchor, through_window} 对象两种写法。"""
    for entry in visible_anchors or []:
        if isinstance(entry, str):
            yield entry, None
        elif isinstance(entry, dict) and entry.get("anchor"):
            yield entry["anchor"], entry.get("through_window")


def project_spatial_causality(scene_map):
    """空间因果推导。返回 (issues, notes)；坐标不全时 notes 记录跳过原因。"""
    issues = []
    notes = []
    base_positions = _anchor_positions(scene_map)
    camera_items = _camera_items(scene_map.get("camera"))

    vehicles = {o.get("object_id"): o for o in scene_map.get("objects", [])
                if isinstance(o, dict) and o.get("object_type") == "vehicle"}

    scene_has_geometry = bool(base_positions)
    any_camera_geometry = False
    for shot_id, camera in camera_items:
        if not isinstance(camera, dict):
            continue
        cam_pos = _entity_coords(camera)
        facing = _camera_bearing(camera)
        state_id = camera.get("blocking_state_id")
        positions = _anchor_positions(scene_map, state_id)
        references_anchor = bool(camera.get("visible_anchors") or camera.get("forbidden_anchors"))
        skipped = camera.get("spatial") == "skipped"
        if cam_pos is None or facing is None:
            # 场景已给坐标、该机位又要拍锚点，却缺数值坐标/朝向：不能静默跳过，
            # 否则会给出“结构通过但其实没做空间校验”的假安全感。
            if scene_has_geometry and references_anchor and not skipped:
                missing = []
                if cam_pos is None:
                    missing.append("数值坐标 position（{x,y} 或 [x,y]）")
                if facing is None:
                    missing.append("数值朝向 orientation（0-360 方位角）")
                issues.append(("ERROR", "spatial-camera-geometry-missing",
                               f"{shot_id}: 场景已提供坐标，但该机位缺少{'、'.join(missing)}，"
                               "无法做空间因果校验；请补齐，或在确实不需要时显式声明 \"spatial\": \"skipped\""))
            continue
        any_camera_geometry = True
        fov_half = float(camera.get("fov_half", DEFAULT_INSIDE_FOV_HALF))
        inside_id = camera.get("inside")
        vehicle = vehicles.get(inside_id) if inside_id else None
        front = _vehicle_front(vehicle) if vehicle else None
        if vehicle is not None and front is None:
            issues.append(("ERROR", "spatial-vehicle-heading-missing",
                           f"{shot_id}: 机位位于车辆 {inside_id} 内，但该车缺少数值车头方位，无法推导车窗方位"))

        # 1) 声明可见的锚点必须真的在视锥内，且穿窗方式与车头朝向一致。
        for anchor_id, through_window in _iter_visible(camera.get("visible_anchors")):
            target = positions.get(anchor_id)
            if target is None:
                continue  # 结构层已负责“未知锚点”报错
            bearing = compass_bearing(cam_pos, target)
            delta = angular_delta(facing, bearing)
            if delta > fov_half:
                issues.append(("ERROR", "spatial-anchor-out-of-view",
                               f"{shot_id}: 锚点 {anchor_id} 相对机位方位 {bearing:.0f}°，"
                               f"与镜头朝向 {facing:.0f}° 相差 {delta:.0f}°，超出视锥(±{fov_half:.0f}°)，"
                               "该锚点不可能出现在画面中"))
            if through_window:
                if through_window not in VEHICLE_WINDOWS:
                    issues.append(("ERROR", "spatial-window-unknown",
                                   f"{shot_id}: 未知车窗 {through_window}，可选 {VEHICLE_WINDOWS}"))
                elif front is not None:
                    actual = window_for_bearing(front, bearing)
                    if actual is None:
                        issues.append(("ERROR", "spatial-window-mismatch",
                                       f"{shot_id}: 锚点 {anchor_id} 方位 {bearing:.0f}° 不落在任何车窗扇区内，"
                                       f"却声明从 {through_window} 看到"))
                    elif actual != through_window:
                        issues.append(("ERROR", "spatial-window-mismatch",
                                       f"{shot_id}: 锚点 {anchor_id} 按车头朝向应从 {actual} 看到，"
                                       f"却声明从 {through_window} 看到（方位 {bearing:.0f}°，车头 {float(front):.0f}°）"))

        # 2) 显式声明“必须看不到”的锚点（如不该入镜的出口），若落入视锥即报错。
        for forbidden in camera.get("forbidden_anchors", []) or []:
            if isinstance(forbidden, dict):
                anchor_id = forbidden.get("anchor")
            else:
                anchor_id = forbidden
            target = positions.get(anchor_id)
            if target is None:
                continue
            bearing = compass_bearing(cam_pos, target)
            delta = angular_delta(facing, bearing)
            if delta <= fov_half:
                reason = forbidden.get("reason", "") if isinstance(forbidden, dict) else ""
                issues.append(("ERROR", "spatial-anchor-should-be-hidden",
                               f"{shot_id}: 锚点 {anchor_id} 按场面调度不应入镜（{reason}），"
                               f"但它位于机位方位 {bearing:.0f}°、视锥(±{fov_half:.0f}°)内"))

        # 3) Screen-space causality. Being inside the frustum does not prove
        # that two actors kept their declared left/right relationship.
        expectations = camera.get("screen_positions", {})
        if isinstance(expectations, dict):
            tolerance = float(camera.get("screen_center_tolerance", DEFAULT_SCREEN_CENTER_TOLERANCE))
            for anchor_id, expected in expectations.items():
                target = positions.get(anchor_id)
                if target is None or expected not in SCREEN_SIDES:
                    continue  # The structural layer reports malformed declarations.
                bearing = compass_bearing(cam_pos, target)
                actual = screen_side(facing, bearing, tolerance)
                if actual != expected:
                    issues.append(("ERROR", "spatial-screen-side-mismatch",
                                   f"{shot_id}: {anchor_id} 声明在画面 {expected}，"
                                   f"但按调度快照 {state_id or 'base'} 与机位投影应在 {actual} "
                                   f"（相对镜头 {signed_angular_offset(facing, bearing):.1f}°）"))

    if not scene_has_geometry:
        notes.append("全场景未提供任何坐标，空间因果推导跳过，仅做结构校验")
    elif not any_camera_geometry:
        notes.append("场景含坐标，但没有任何机位提供完整坐标+朝向，未产生空间因果结论")
    return issues, notes


def _iter_visible(visible_anchors):
    yield from _iter_visible_entries(visible_anchors)


def _camera_items(cameras):
    """camera 支持单对象或 {shot_id: spec} 分组两种写法。"""
    if isinstance(cameras, dict) and "orientation" not in cameras:
        return sorted(cameras.items())
    return [("camera", cameras)]


def derive_shot_constraints(scene_map: dict) -> dict:
    """从坐标确定性推导每个机位“能看到什么/哪扇窗/禁见什么”的约束文本。

    用途：scene_map 是几何事实源，但喂给图像模型的是文字 prompt；本函数把方位推导
    自动落成可直接抄进 prompt 的空间约束，避免人工翻译时把“机后禁见”写错。
    返回 {shot_id: {facing, visible:[...], forbidden:[...], lines:[...]}}。
    """
    vehicles = {o.get("object_id"): o for o in scene_map.get("objects", [])
                if isinstance(o, dict) and o.get("object_type") == "vehicle"}
    result = {}
    for shot_id, camera in _camera_items(scene_map.get("camera")):
        if not isinstance(camera, dict):
            continue
        cam_pos = _entity_coords(camera)
        facing = _camera_bearing(camera)
        state_id = camera.get("blocking_state_id")
        positions = _anchor_positions(scene_map, state_id)
        entry = {"facing": facing, "blocking_state_id": state_id, "visible": [],
                 "forbidden": [], "screen_positions": [], "lines": []}
        if cam_pos is None or facing is None:
            entry["lines"].append("（机位缺数值坐标/朝向，无法推导空间约束）")
            result[shot_id] = entry
            continue
        fov_half = float(camera.get("fov_half", DEFAULT_INSIDE_FOV_HALF))
        vehicle = vehicles.get(camera.get("inside")) if camera.get("inside") else None
        front = _vehicle_front(vehicle) if vehicle else None
        for anchor_id, declared_window in _iter_visible(camera.get("visible_anchors")):
            target = positions.get(anchor_id)
            if target is None:
                continue
            bearing = compass_bearing(cam_pos, target)
            delta = angular_delta(facing, bearing)
            # Interior characters, doors and window surfaces are not viewed
            # "through" a vehicle window. Derive a portal only when the scene
            # map explicitly marks an exterior anchor with through_window.
            window = window_for_bearing(front, bearing) if front is not None and declared_window else None
            in_view = delta <= fov_half
            entry["visible"].append({"anchor": anchor_id, "bearing": round(bearing, 1),
                                     "delta": round(delta, 1), "in_view": in_view, "window": window})
            via = f"，经由{window}" if window else ""
            if in_view:
                entry["lines"].append(f"画面可含「{anchor_id}」：相对机位 {bearing:.0f}°{via}，落在视锥内")
            else:
                entry["lines"].append(
                    f"「{anchor_id}」相对机位 {bearing:.0f}°、与朝向相差 {delta:.0f}° 超出视锥，不应入镜")
        for forbidden in camera.get("forbidden_anchors", []) or []:
            anchor_id = forbidden.get("anchor") if isinstance(forbidden, dict) else forbidden
            reason = forbidden.get("reason", "") if isinstance(forbidden, dict) else ""
            target = positions.get(anchor_id)
            if target is None:
                continue
            bearing = compass_bearing(cam_pos, target)
            delta = angular_delta(facing, bearing)
            entry["forbidden"].append({"anchor": anchor_id, "bearing": round(bearing, 1),
                                       "delta": round(delta, 1)})
            entry["lines"].append(f"画面禁见「{anchor_id}」（相对机位 {bearing:.0f}°，{reason}）")
        tolerance = float(camera.get("screen_center_tolerance", DEFAULT_SCREEN_CENTER_TOLERANCE))
        for anchor_id, expected in (camera.get("screen_positions", {}) or {}).items():
            target = positions.get(anchor_id)
            if target is None:
                continue
            bearing = compass_bearing(cam_pos, target)
            actual = screen_side(facing, bearing, tolerance)
            entry["screen_positions"].append({"anchor": anchor_id, "expected": expected,
                                               "actual": actual})
            entry["lines"].append(
                f"画面方位「{anchor_id}」：声明={expected}，坐标投影={actual}")
        result[shot_id] = entry
    return result


def inspect(scene_map: dict) -> dict:
    errors = []
    warnings = []
    if not isinstance(scene_map, dict):
        return {"status": "失败", "errors": ["scene_map 必须是 JSON 对象"], "warnings": []}
    review = scene_map.get("user_review") if isinstance(scene_map.get("user_review"), dict) else {}
    layout_phase = review.get("review_phase") == "layout"
    for field in ("scene_id", "space_boundary", "fixed_anchors", "primary_axis",
                  "walkable_zones", "objects"):
        if not scene_map.get(field):
            errors.append(f"缺少场景字段: {field}")
    if not layout_phase and not scene_map.get("camera"):
        errors.append("缺少场景字段: camera")
    elif layout_phase and not isinstance(scene_map.get("camera"), dict):
        errors.append("布局确认阶段 camera 必须是空对象或已登记机位对象")
    anchors = {a.get("anchor_id") for a in scene_map.get("fixed_anchors", []) if isinstance(a, dict)}
    object_by_id = {o.get("object_id"): o for o in scene_map.get("objects", [])
                    if isinstance(o, dict) and o.get("object_id")}
    object_ids = set(object_by_id)
    known_positions = anchors | object_ids

    boundary = scene_map.get("space_boundary")
    boundary_polygon = _polygon_points(boundary.get("polygon")) if isinstance(boundary, dict) else None
    if not isinstance(boundary, dict) or boundary_polygon is None:
        errors.append("space_boundary 必须包含至少3个数值坐标点的 polygon")
        boundary_polygon = []
    elif not isinstance(boundary.get("boundary_type"), str) or not boundary.get("boundary_type").strip():
        errors.append("space_boundary 缺少 boundary_type")

    walkable_zones = scene_map.get("walkable_zones", [])
    walkable_polygons = []
    if not isinstance(walkable_zones, list) or not walkable_zones:
        errors.append("walkable_zones 必须是非空数组")
        walkable_zones = []
    for index, zone in enumerate(walkable_zones, 1):
        if not isinstance(zone, dict):
            errors.append(f"可通行区 {index} 必须是对象")
            continue
        polygon = _polygon_points(zone.get("polygon"))
        if not zone.get("zone_id") or polygon is None:
            errors.append(f"可通行区 {zone.get('zone_id', index)} 必须包含 zone_id 和有效 polygon")
            continue
        walkable_polygons.append(zone["polygon"])
        if boundary_polygon and any(not point_in_polygon(point, boundary_polygon) for point in polygon):
            errors.append(f"可通行区 {zone['zone_id']} 超出 space_boundary")

    persistent = scene_map.get("persistent_landmarks", [])
    if persistent is not None and not isinstance(persistent, list):
        errors.append("persistent_landmarks 必须是数组")
        persistent = []
    for index, landmark in enumerate(persistent, 1):
        if not isinstance(landmark, dict):
            errors.append(f"持续地标 {index} 必须是对象")
            continue
        required = ("anchor_id", "dimensions", "traversability",
                    "visibility_policy", "environment_cover_limit")
        missing = [field for field in required if _field_missing(landmark, field)
                   or landmark.get(field) == ""]
        if missing:
            errors.append(f"持续地标 {landmark.get('anchor_id', index)} 缺少字段: {', '.join(missing)}")
        if landmark.get("anchor_id") not in known_positions:
            errors.append(f"持续地标引用未知锚点: {landmark.get('anchor_id')}")
        if landmark.get("traversability") not in {"solid", "surface", "passable"}:
            errors.append(f"持续地标 {landmark.get('anchor_id')} traversability 非法")
        if landmark.get("visibility_policy") not in {"persistent", "may_leave_frame"}:
            errors.append(f"持续地标 {landmark.get('anchor_id')} visibility_policy 非法")

    occupancy_zones = scene_map.get("occupancy_zones", [])
    if occupancy_zones is not None and not isinstance(occupancy_zones, list):
        errors.append("occupancy_zones 必须是数组")
        occupancy_zones = []
    zone_by_id = {}
    for index, zone in enumerate(occupancy_zones, 1):
        if not isinstance(zone, dict):
            errors.append(f"占用区 {index} 必须是对象")
            continue
        required = ("zone_id", "polygon", "access", "applies_to", "reason")
        missing = [field for field in required if _field_missing(zone, field)]
        if missing:
            errors.append(f"占用区 {zone.get('zone_id', index)} 缺少字段: {', '.join(missing)}")
        zone_id = zone.get("zone_id")
        if zone_id in zone_by_id:
            errors.append(f"占用区 zone_id 重复: {zone_id}")
        elif zone_id:
            zone_by_id[zone_id] = zone
        if _polygon_points(zone.get("polygon")) is None:
            errors.append(f"占用区 {zone_id or index} polygon 必须至少包含3个数值坐标点")
        if zone.get("access") not in {"allowed", "forbidden"}:
            errors.append(f"占用区 {zone_id or index} access 必须是 allowed 或 forbidden")
        applies_to = zone.get("applies_to")
        if not isinstance(applies_to, list) or not applies_to:
            errors.append(f"占用区 {zone_id or index} applies_to 必须是非空数组")
        else:
            unknown = sorted(set(applies_to) - object_ids)
            if unknown:
                errors.append(f"占用区 {zone_id or index} 引用未知对象: {', '.join(unknown)}")

    scale_anchors = scene_map.get("scale_anchors", [])
    if scale_anchors is not None and not isinstance(scale_anchors, list):
        errors.append("scale_anchors 必须是数组")
        scale_anchors = []
    for index, scale in enumerate(scale_anchors, 1):
        if not isinstance(scale, dict):
            errors.append(f"尺度锚点 {index} 必须是对象")
            continue
        anchor_id = scale.get("anchor_id")
        if anchor_id not in known_positions:
            errors.append(f"尺度锚点引用未知锚点: {anchor_id}")
        if not isinstance(scale.get("real_size_m"), (int, float)) \
                or isinstance(scale.get("real_size_m"), bool) or scale.get("real_size_m") <= 0:
            errors.append(f"尺度锚点 {anchor_id or index} real_size_m 必须是正数")
        if not isinstance(scale.get("comparison"), str) or not scale.get("comparison").strip():
            errors.append(f"尺度锚点 {anchor_id or index} 缺少 comparison")
    blocking_states = scene_map.get("blocking_states", {})
    if blocking_states and not isinstance(blocking_states, dict):
        errors.append("blocking_states 必须是以 state_id 为键的 JSON 对象")
        blocking_states = {}
    for state_id, state in blocking_states.items():
        if not isinstance(state, dict) or not isinstance(state.get("objects"), dict):
            errors.append(f"调度快照 {state_id} 必须包含 objects 对象")
            continue
        unknown_state_objects = sorted(set(state["objects"]) - object_ids)
        if unknown_state_objects:
            errors.append(f"调度快照 {state_id} 引用了未知对象: {', '.join(unknown_state_objects)}")
        for object_id, override in state["objects"].items():
            if not isinstance(override, dict) or _entity_coords(override) is None:
                errors.append(f"调度快照 {state_id} 的对象 {object_id} 缺少数值 position")
                continue
            position = _entity_coords(override)
            if boundary_polygon and not point_in_polygon(position, boundary_polygon):
                errors.append(f"spatial-object-outside-boundary: {state_id} 的 {object_id} 位于空间边界外")
            if walkable_polygons and object_by_id.get(object_id, {}).get("object_type") == "person" \
                    and not _inside_any(position, walkable_polygons):
                errors.append(f"spatial-object-outside-walkable: {state_id} 的 {object_id} 不在可通行区")
            for zone in occupancy_zones:
                if not isinstance(zone, dict) or zone.get("access") != "forbidden":
                    continue
                applies_to = zone.get("applies_to") if isinstance(zone.get("applies_to"), list) else []
                if object_id not in applies_to:
                    continue
                if point_in_polygon(position, zone.get("polygon")):
                    errors.append(
                        f"spatial-forbidden-zone-entry: {state_id} 的 {object_id} "
                        f"进入禁入区 {zone.get('zone_id')}（{zone.get('reason', '')}）")

    movement_routes = scene_map.get("movement_routes", [])
    if movement_routes is not None and not isinstance(movement_routes, list):
        errors.append("movement_routes 必须是数组")
        movement_routes = []
    route_by_transition = {}
    for index, route in enumerate(movement_routes, 1):
        if not isinstance(route, dict):
            errors.append(f"移动路线 {index} 必须是对象")
            continue
        required = ("route_id", "object_id", "from_state_id", "to_state_id", "points")
        missing = [field for field in required if _field_missing(route, field)]
        if missing:
            errors.append(f"移动路线 {route.get('route_id', index)} 缺少字段: {', '.join(missing)}")
            continue
        object_id = route.get("object_id")
        from_state = route.get("from_state_id")
        to_state = route.get("to_state_id")
        points = [_as_coords(point) for point in route.get("points", [])]
        if object_id not in object_ids or from_state not in blocking_states or to_state not in blocking_states:
            errors.append(f"移动路线 {route.get('route_id')} 引用了未知对象或状态")
            continue
        if len(points) < 2 or any(point is None for point in points):
            errors.append(f"移动路线 {route.get('route_id')} points 至少需要两个有效坐标点")
            continue
        key = (object_id, from_state, to_state)
        if key in route_by_transition:
            errors.append(f"移动路线重复覆盖 {object_id}: {from_state}->{to_state}")
        route_by_transition[key] = route
        start = _anchor_positions(scene_map, from_state).get(object_id)
        end = _anchor_positions(scene_map, to_state).get(object_id)
        if start and points[0] != start:
            errors.append(f"spatial-route-start-drift: {route.get('route_id')} 起点与 {from_state} 不一致")
        if end and points[-1] != end:
            errors.append(f"spatial-route-end-drift: {route.get('route_id')} 终点与 {to_state} 不一致")
        for sample in _polyline_samples(points):
            if boundary_polygon and not point_in_polygon(sample, boundary_polygon):
                errors.append(f"spatial-route-outside-boundary: {route.get('route_id')} 穿出空间边界")
                break
            if walkable_polygons and not _inside_any(sample, walkable_polygons):
                errors.append(f"spatial-route-outside-walkable: {route.get('route_id')} 穿过不可通行区域")
                break
            blocked = next((zone for zone in occupancy_zones
                            if isinstance(zone, dict) and zone.get("access") == "forbidden"
                            and object_id in (zone.get("applies_to") or [])
                            and point_in_polygon(sample, zone.get("polygon"))), None)
            if blocked:
                errors.append(f"spatial-route-forbidden-zone: {route.get('route_id')} 穿过禁入区 {blocked.get('zone_id')}")
                break

    sequence = []
    for entry in review.get("state_sequence", []) if isinstance(review.get("state_sequence"), list) else []:
        state_id = entry if isinstance(entry, str) else entry.get("state_id") if isinstance(entry, dict) else None
        if state_id in blocking_states:
            sequence.append(state_id)
    for from_state, to_state in zip(sequence, sequence[1:]):
        from_positions = _anchor_positions(scene_map, from_state)
        to_positions = _anchor_positions(scene_map, to_state)
        for object_id in object_ids:
            if from_positions.get(object_id) == to_positions.get(object_id):
                continue
            if (object_id, from_state, to_state) not in route_by_transition:
                errors.append(
                    f"spatial-route-missing: {object_id} 从 {from_state} 移至 {to_state}，但未登记 movement_route")
    for index, obj in enumerate(scene_map.get("objects", []), 1):
        if not isinstance(obj, dict):
            errors.append(f"对象 {index} 必须是 JSON 对象")
            continue
        for field in REQUIRED_OBJECT_FIELDS:
            if _field_missing(obj, field):
                errors.append(f"对象 {obj.get('object_id', index)} 缺少字段: {field}")
        position = _entity_coords(obj)
        if position and boundary_polygon and not point_in_polygon(position, boundary_polygon):
            errors.append(f"spatial-object-outside-boundary: {obj.get('object_id', index)} 位于空间边界外")
        if position and walkable_polygons and obj.get("object_type") == "person" \
                and not _inside_any(position, walkable_polygons):
            errors.append(f"spatial-object-outside-walkable: {obj.get('object_id', index)} 不在可通行区")
        role = obj.get("role")
        if role not in KNOWN_ROLES:
            errors.append(f"对象 {obj.get('object_id', index)} 未分类: role={role!r}")
        if obj.get("object_type") == "vehicle" and role == "story-object":
            for field in ("parking_slot", "front_direction", "driver_side", "seats"):
                # 0° is a valid north-facing heading; truthiness would treat it
                # as missing and block an otherwise fully specified vehicle.
                if field not in obj or obj.get(field) is None or obj.get(field) == "":
                    errors.append(f"剧情车辆 {obj.get('object_id')} 缺少字段: {field}")
        visible = obj.get("visible_anchors", [])
        unknown = sorted(set(visible) - known_positions)
        if unknown:
            errors.append(f"对象 {obj.get('object_id')} 引用了未知锚点: {', '.join(unknown)}")
    camera_list = list(_camera_items(scene_map.get("camera", {})))
    for shot_id, camera in camera_list:
        if not isinstance(camera, dict):
            continue
        for field in REQUIRED_CAMERA_FIELDS:
            if _field_missing(camera, field):
                errors.append(f"摄影机缺少字段: {field}")
        camera_position = _entity_coords(camera)
        placement = camera.get("placement")
        if placement not in {"inside", "outside", "attached"}:
            errors.append(f"{shot_id} 的 placement 必须是 inside、outside 或 attached")
        elif placement == "attached":
            attached_to = camera.get("attached_to")
            if not attached_to:
                errors.append(f"spatial-camera-attachment-missing: {shot_id} 的 attached 机位缺少 attached_to")
            elif attached_to not in known_positions:
                errors.append(f"spatial-camera-attachment-unknown: {shot_id} 依附未知对象 {attached_to}")
        elif camera_position and boundary_polygon:
            inside_boundary = point_in_polygon(camera_position, boundary_polygon)
            if placement == "outside" and inside_boundary:
                errors.append(f"spatial-camera-placement-drift: {shot_id} 声明 outside 但坐标在边界内")
            if placement == "inside" and not inside_boundary:
                errors.append(f"spatial-camera-placement-drift: {shot_id} 声明 inside 但坐标在边界外")
            if placement == "inside" and walkable_polygons \
                    and not _inside_any(camera_position, walkable_polygons):
                errors.append(f"spatial-camera-unreachable: {shot_id} 机位不在可通行区")
        declared, _ = zip(*list(_iter_visible_entries(camera.get("visible_anchors", [])))) if camera.get("visible_anchors") else ([], [])
        unknown_camera_anchors = sorted(set(declared) - known_positions)
        if unknown_camera_anchors:
            errors.append("摄影机引用了未知锚点: " + ", ".join(unknown_camera_anchors))
        state_id = camera.get("blocking_state_id")
        references_dynamic_object = bool(set(declared) & object_ids)
        if blocking_states and references_dynamic_object and not state_id:
            errors.append(f"spatial-blocking-state-missing: {shot_id} 引用了动态对象但未绑定 blocking_state_id")
        elif state_id and state_id not in blocking_states:
            errors.append(f"spatial-blocking-state-unknown: {shot_id} 引用了不存在的调度快照 {state_id}")
        screen_positions = camera.get("screen_positions", {})
        if screen_positions is not None and not isinstance(screen_positions, dict):
            errors.append(f"{shot_id} 的 screen_positions 必须是对象")
        elif isinstance(screen_positions, dict):
            unknown_screen = sorted(set(screen_positions) - known_positions)
            if unknown_screen:
                errors.append(f"{shot_id} 的 screen_positions 引用了未知锚点: {', '.join(unknown_screen)}")
            invalid_sides = sorted({str(value) for value in screen_positions.values()
                                    if value not in SCREEN_SIDES})
            if invalid_sides:
                errors.append(f"{shot_id} 的 screen_positions 存在非法值: {', '.join(invalid_sides)}")
    if not errors and not scene_map.get("shot_states"):
        warnings.append("未提供 shot_states，无法校验镜头前后状态推导")

    # 空间因果层（坐标齐全才生效）。
    spatial_issues, spatial_notes = project_spatial_causality(scene_map)
    for level, code, message in spatial_issues:
        if level == "ERROR":
            errors.append(f"{code}: {message}")
        else:
            warnings.append(f"{code}: {message}")
    warnings.extend(spatial_notes)

    status = "通过" if not errors else "失败"
    return {"status": status, "errors": errors, "warnings": warnings,
            "spatial_issue_count": sum(1 for lv, _, _ in spatial_issues if lv == "ERROR")}


def main():
    parser = argparse.ArgumentParser(description="校验通用空间连续性合同 JSON（结构 + 空间因果推导）")
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--constraints", action="store_true",
                        help="不做校验，改为输出每个机位由坐标推导出的空间约束文本（可抄进图像 prompt）")
    args = parser.parse_args()
    failed = False
    payload = {}
    for path in args.files:
        try:
            scene_map = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            report = {"status": "失败", "errors": [str(exc)], "warnings": []}
            payload[str(path)] = report
            failed = True
            continue
        if args.constraints:
            constraints = derive_shot_constraints(scene_map)
            if args.json:
                payload[str(path)] = constraints
            else:
                print(f"# {path}")
                for shot_id, entry in constraints.items():
                    print(f"[{shot_id}] 朝向={entry['facing']}")
                    for line in entry["lines"]:
                        print(f"  - {line}")
            continue
        report = inspect(scene_map)
        payload[str(path)] = report
        if not args.json:
            print(f"{path}: {report['status']}")
            for message in report["errors"]:
                print(f"ERROR: {message}")
            for message in report["warnings"]:
                print(f"WARNING: {message}")
        failed |= report["status"] == "失败"
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
