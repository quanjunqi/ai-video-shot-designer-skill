#!/usr/bin/env python3
"""Render a user-facing blocking and movement map from one scene_map JSON."""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
import unicodedata
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPATIAL_SCRIPT = ROOT / "scripts" / "check_spatial_contract.py"
_spec = importlib.util.spec_from_file_location("check_spatial_contract", SPATIAL_SCRIPT)
if _spec is None or _spec.loader is None:  # pragma: no cover
    raise ImportError(f"cannot load {SPATIAL_SCRIPT}")
spatial = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(spatial)


def scene_signature(scene_map, review_type="layout"):
    return spatial.scene_review_signature(scene_map, review_type)


def _review(scene_map):
    value = scene_map.get("user_review")
    return value if isinstance(value, dict) else {}


def _labels(scene_map):
    configured = _review(scene_map).get("entity_labels", {})
    labels = dict(configured) if isinstance(configured, dict) else {}
    for anchor in scene_map.get("fixed_anchors", []):
        if not isinstance(anchor, dict) or not anchor.get("anchor_id"):
            continue
        features = str(anchor.get("features", "")).strip()
        if features:
            labels.setdefault(anchor["anchor_id"], features.split("，", 1)[0].split("；", 1)[0])
    return labels


def _name(entity_id, labels):
    return labels.get(entity_id, entity_id)


def _tracked_objects(scene_map):
    objects = {
        item.get("object_id"): item
        for item in scene_map.get("objects", [])
        if isinstance(item, dict) and item.get("object_id")
    }
    requested = _review(scene_map).get("tracked_entities")
    if isinstance(requested, list) and requested:
        return {key: objects[key] for key in requested if key in objects}
    return {
        key: item for key, item in objects.items()
        if item.get("role") == "story-object"
    }


def _state_sequence(scene_map):
    states = scene_map.get("blocking_states", {})
    if not isinstance(states, dict):
        return []
    requested = _review(scene_map).get("state_sequence")
    if isinstance(requested, list) and requested:
        result = []
        for entry in requested:
            if isinstance(entry, str) and entry in states:
                result.append({"state_id": entry, "label": entry})
            elif isinstance(entry, dict) and entry.get("state_id") in states:
                result.append({
                    "state_id": entry["state_id"],
                    "label": entry.get("label", entry["state_id"]),
                    "unit_ids": entry.get("unit_ids", []),
                    "shot_ids": entry.get("shot_ids", []),
                })
        return result
    return [{"state_id": key, "label": key} for key in states]


def _all_points(scene_map):
    points = []
    for collection in ("fixed_anchors", "objects"):
        for item in scene_map.get(collection, []):
            point = spatial._entity_coords(item)
            if point:
                points.append(point)
    for state in (scene_map.get("blocking_states", {}) or {}).values():
        if not isinstance(state, dict):
            continue
        for item in (state.get("objects", {}) or {}).values():
            point = spatial._entity_coords(item)
            if point:
                points.append(point)
    return points or [{"x": -1.0, "y": -1.0}, {"x": 1.0, "y": 1.0}]


def _bounds(scene_map):
    points = _all_points(scene_map)
    return (
        min(point["x"] for point in points), max(point["x"] for point in points),
        min(point["y"] for point in points), max(point["y"] for point in points),
    )


def _region(point, bounds):
    if not point:
        return "位置未登记"
    min_x, max_x, min_y, max_y = bounds
    x_span = max(max_x - min_x, 1.0)
    y_span = max(max_y - min_y, 1.0)
    x_ratio = (point["x"] - min_x) / x_span
    y_ratio = (point["y"] - min_y) / y_span
    horizontal = "西侧" if x_ratio < 1 / 3 else "东侧" if x_ratio > 2 / 3 else "中央"
    vertical = "南侧" if y_ratio < 1 / 3 else "北侧" if y_ratio > 2 / 3 else "中部"
    if horizontal == "中央" and vertical == "中部":
        return "中央"
    if horizontal == "中央":
        return vertical
    if vertical == "中部":
        return horizontal
    return vertical[0] + horizontal


def _state_positions(scene_map, state_id, tracked):
    positions = {
        object_id: spatial._entity_coords(item)
        for object_id, item in tracked.items()
    }
    states = scene_map.get("blocking_states", {})
    state = states.get(state_id, {}) if isinstance(states, dict) else {}
    overrides = state.get("objects", {}) if isinstance(state, dict) else {}
    if isinstance(overrides, dict):
        for object_id, item in overrides.items():
            if object_id in positions:
                positions[object_id] = spatial._entity_coords(item) or positions[object_id]
    return positions


def _humanize(value, labels):
    text = str(value).strip()
    for entity_id in sorted(labels, key=len, reverse=True):
        text = text.replace(entity_id, str(labels[entity_id]))
    return text


def _relative_to_anchor(point, scene_map, labels, bounds):
    candidates = []
    for anchor in scene_map.get("fixed_anchors", []):
        if not isinstance(anchor, dict) or not anchor.get("anchor_id"):
            continue
        anchor_point = spatial._entity_coords(anchor)
        if anchor_point:
            distance = math.hypot(point["x"] - anchor_point["x"], point["y"] - anchor_point["y"])
            candidates.append((distance, anchor, anchor_point))
    if not candidates:
        return _region(point, bounds)

    _, anchor, anchor_point = min(candidates, key=lambda item: item[0])
    anchor_name = _name(anchor["anchor_id"], labels)
    dx = float(point["x"]) - float(anchor_point["x"])
    dy = float(point["y"]) - float(anchor_point["y"])
    if math.isclose(dx, 0.0) and math.isclose(dy, 0.0):
        return str(anchor_name)
    if abs(dx) > abs(dy):
        side = "东侧" if dx > 0 else "西侧"
    else:
        side = "北侧" if dy > 0 else "南侧"
    return f"{anchor_name}{side}"


def _initial_description(item, scene_map, labels, bounds):
    state = _humanize(item.get("state", ""), labels)
    if state and state not in {"未说明", "起始状态"}:
        return state
    point = spatial._entity_coords(item)
    return _relative_to_anchor(point, scene_map, labels, bounds) if point else "位置待确认"


def _cardinal_direction(value):
    if not isinstance(value, (int, float)):
        return "目标区域"
    bearing = float(value) % 360
    names = ("北", "东北", "东", "东南", "南", "西南", "西", "西北")
    return names[int((bearing + 22.5) // 45) % 8]


def _axis_lines(scene_map, labels, bounds):
    grouped = {}
    for anchor in scene_map.get("fixed_anchors", []):
        if not isinstance(anchor, dict) or not anchor.get("anchor_id"):
            continue
        point = spatial._entity_coords(anchor)
        region = _region(point, bounds) if point else "位置待确认"
        name = str(_name(anchor["anchor_id"], labels))
        features = _humanize(anchor.get("features", ""), labels)
        description = features if features and name in features else (
            f"{name}（{features}）" if features else name
        )
        grouped.setdefault(region, []).append(description)
    if not grouped:
        return ["- 方位关系待确认。"]
    order = ("北侧", "南侧", "西侧", "东侧", "中央", "西北", "东北", "西南", "东南")
    return [f"- {region.replace('侧', '')}：{'；'.join(grouped[region])}" for region in order if region in grouped]


def _entity_lines(scene_map, tracked, labels, bounds):
    lines = []
    for object_id, item in tracked.items():
        details = [_initial_description(item, scene_map, labels, bounds).rstrip("。")]
        relations = item.get("relations", [])
        if isinstance(relations, list):
            details.extend(
                _humanize(relation, labels).rstrip("。")
                for relation in relations
                if isinstance(relation, str) and relation.strip() and "=" not in relation
            )
        lines.append(f"- {_name(object_id, labels)}：{'；'.join(details)}。")
    return lines


def _visible_anchor_ids(camera):
    result = []
    for entry in camera.get("visible_anchors", []) or []:
        anchor_id = entry.get("anchor") if isinstance(entry, dict) else entry
        if anchor_id:
            result.append(anchor_id)
    return result


def _camera_specs(scene_map, labels):
    lines = []
    for index, (shot_id, camera) in enumerate(spatial._camera_items(scene_map.get("camera", {})), 1):
        if not isinstance(camera, dict):
            continue
        location = _humanize(camera.get("side", "位置待确认"), labels).replace("安全侧", "").strip()
        direction = _cardinal_direction(camera.get("orientation"))
        target_ids = _visible_anchor_ids(camera)
        target_names = [str(_name(item, labels)) for item in target_ids]
        target = camera.get("user_target") or (
            "场景整体" if len(target_names) > 4 else "、".join(target_names) or "目标区域"
        )
        lines.append({
            "label": camera.get("station_label") or f"C{index}",
            "shot_id": shot_id,
            "camera": camera,
            "location": location,
            "direction": direction,
            "view_angle": camera.get("view_angle", ""),
            "target": target,
        })
    return lines


def _camera_arrow(orientation):
    if not isinstance(orientation, (int, float)):
        return "?"
    arrows = ("↑", "↗", "→", "↘", "↓", "↙", "←", "↖")
    return arrows[int((float(orientation) % 360 + 22.5) // 45) % 8]


def _display_width(value):
    return sum(2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1 for char in str(value))


def _fit(value, width, align="center"):
    value = str(value)
    while value and _display_width(value) > width:
        value = value[:-1]
    padding = max(0, width - _display_width(value))
    if align == "left":
        return value + " " * padding
    if align == "right":
        return " " * padding + value
    left = padding // 2
    return " " * left + value + " " * (padding - left)


def _room_bounds(scene_map, fallback):
    boundary = scene_map.get("space_boundary")
    points = spatial._polygon_points(boundary.get("polygon")) if isinstance(boundary, dict) else None
    if not points:
        raise ValueError("scene_map 缺少可验证的 space_boundary，禁止推测房间外框")
    unique = {(point["x"], point["y"]) for point in points}
    xs = {point["x"] for point in points}
    ys = {point["y"] for point in points}
    if len(unique) != 4 or len(xs) != 2 or len(ys) != 2:
        raise ValueError("当前简洁文字俯视图只支持矩形 space_boundary；复杂边界必须先拆成可确认的连续空间")
    return (
        min(point["x"] for point in points), max(point["x"] for point in points),
        min(point["y"] for point in points), max(point["y"] for point in points),
    )


def _floorplan_cell(point, room_bounds):
    if not point:
        return 1, 1
    min_x, max_x, min_y, max_y = room_bounds
    x_ratio = (float(point["x"]) - min_x) / max(max_x - min_x, 1.0)
    y_ratio = (float(point["y"]) - min_y) / max(max_y - min_y, 1.0)
    column = 0 if x_ratio < 1 / 3 else 2 if x_ratio > 2 / 3 else 1
    row = 0 if y_ratio > 2 / 3 else 2 if y_ratio < 1 / 3 else 1
    return row, column


def _outside_side(point, room_bounds):
    if not point:
        return None
    min_x, max_x, min_y, max_y = room_bounds
    distances = {
        "north": float(point["y"]) - max_y,
        "south": min_y - float(point["y"]),
        "east": float(point["x"]) - max_x,
        "west": min_x - float(point["x"]),
    }
    positive = {side: distance for side, distance in distances.items() if distance > 1e-9}
    return max(positive, key=positive.get) if positive else None


def _border_label(scene_map, labels, room_bounds, side):
    min_x, max_x, min_y, max_y = room_bounds
    names = []
    for anchor in scene_map.get("fixed_anchors", []):
        if not isinstance(anchor, dict) or not anchor.get("anchor_id"):
            continue
        point = spatial._entity_coords(anchor)
        if not point:
            continue
        on_side = (
            side == "north" and math.isclose(point["y"], max_y)
            or side == "south" and math.isclose(point["y"], min_y)
            or side == "west" and math.isclose(point["x"], min_x)
            or side == "east" and math.isclose(point["x"], max_x)
        )
        if on_side:
            names.append(str(_name(anchor["anchor_id"], labels)))
    return "、".join(names)


def _border(width, left, right, label=""):
    if not label:
        return left + "─" * width + right
    label = f" {label} "
    remaining = max(0, width - _display_width(label))
    before = remaining // 2
    return left + "─" * before + label + "─" * (remaining - before) + right


def _position_floorplan(scene_map, tracked, labels, bounds, cameras):
    room_bounds = _room_bounds(scene_map, bounds)
    cells = [[{"entities": [], "cameras": []} for _ in range(3)] for _ in range(3)]
    min_x, max_x, min_y, max_y = room_bounds
    for anchor in scene_map.get("fixed_anchors", []):
        if not isinstance(anchor, dict) or not anchor.get("anchor_id"):
            continue
        point = spatial._entity_coords(anchor)
        if point and (
            math.isclose(point["x"], min_x) or math.isclose(point["x"], max_x)
            or math.isclose(point["y"], min_y) or math.isclose(point["y"], max_y)
        ):
            continue
        row, column = _floorplan_cell(point, room_bounds)
        cells[row][column]["entities"].append(str(_name(anchor["anchor_id"], labels)))
    for object_id, item in tracked.items():
        row, column = _floorplan_cell(spatial._entity_coords(item), room_bounds)
        cells[row][column]["entities"].append(str(_name(object_id, labels)))

    outside = {side: [[], [], []] for side in ("north", "south", "west", "east")}
    for spec in cameras:
        point = spatial._entity_coords(spec["camera"])
        row, column = _floorplan_cell(point, room_bounds)
        marker = f"{spec['label']}{_camera_arrow(spec['camera'].get('orientation'))}"
        side = _outside_side(point, room_bounds)
        if side in {"north", "south"}:
            if marker not in outside[side][column]:
                outside[side][column].append(marker)
        elif side in {"west", "east"}:
            if marker not in outside[side][row]:
                outside[side][row].append(marker)
        else:
            if marker not in cells[row][column]["cameras"]:
                cells[row][column]["cameras"].append(marker)

    visible_labels = []
    for row in cells:
        for cell in row:
            visible_labels.extend(cell["entities"])
            visible_labels.extend(cell["cameras"])
    cell_width = max(18, max((_display_width(label) + 2 for label in visible_labels), default=18))
    room_width = cell_width * 3
    indent = " " * 12

    def triplet(groups):
        return "".join(_fit(group, cell_width) for group in groups)

    def inside_line(groups, left="", right=""):
        return _fit(left, 11, "right") + " │" + triplet(groups) + "│ " + _fit(right, 10, "left")

    lines = [indent + _fit("北", room_width + 2)]
    if any(outside["north"]):
        lines.append(indent + " " + triplet([" ".join(group) for group in outside["north"]]) + " ")
    lines.append(indent + _border(room_width, "┌", "┐", _border_label(scene_map, labels, room_bounds, "north")))
    for row in range(3):
        groups = [
            cells[row][column]["entities"] + cells[row][column]["cameras"]
            for column in range(3)
        ]
        left = " ".join(outside["west"][row])
        right = " ".join(outside["east"][row])
        line_count = max((len(group) for group in groups), default=0)
        if line_count:
            for index in range(line_count):
                values = [group[index] if index < len(group) else "" for group in groups]
                lines.append(inside_line(values, left if index == 0 else "", right if index == 0 else ""))
        elif left or right:
            lines.append(inside_line(["", "", ""], left, right))
        if row < 2:
            lines.append(inside_line(["", "", ""]))
    lines.append(indent + _border(room_width, "└", "┘", _border_label(scene_map, labels, room_bounds, "south")))
    if any(outside["south"]):
        lines.append(indent + " " + triplet([" ".join(group) for group in outside["south"]]) + " ")
    lines.append(indent + _fit("南", room_width + 2))
    return "\n".join(line.rstrip() for line in lines)


def render_text_map(scene_map, review_type="layout"):
    if review_type not in {"layout", "camera_plan"}:
        raise ValueError(f"unknown review_type: {review_type}")
    review = _review(scene_map)
    labels = _labels(scene_map)
    tracked = _tracked_objects(scene_map)
    sequence = _state_sequence(scene_map)
    bounds = _bounds(scene_map)
    scene_id = scene_map.get("scene_id", "unknown")
    title = review.get("space_name", scene_id)
    heading = "场景布局与走位确认" if review_type == "layout" else "覆盖机位确认"
    lines = [f"# {heading}：{title}", "", "**空间骨架**", ""]
    lines.extend(_axis_lines(scene_map, labels, bounds))
    lines.extend(["", "**人物与关键物件**", ""])
    lines.extend(_entity_lines(scene_map, tracked, labels, bounds))

    movement_steps = sequence[1:] if len(sequence) > 1 else sequence
    if movement_steps:
        lines.extend(["", "**走位变化**", ""])
        for index, entry in enumerate(movement_steps, 1):
            lines.append(f"{index}. {_humanize(entry['label'], labels)}。")

    cameras = _camera_specs(scene_map, labels) if review_type == "camera_plan" else []
    lines.extend(["", "**俯视位置图**", ""])
    lines.extend(["```text", _position_floorplan(scene_map, tracked, labels, bounds, cameras), "```"])
    if cameras:
        lines.extend(["", "**镜头站位**", ""])
        grouped_cameras = {}
        for spec in cameras:
            group = grouped_cameras.setdefault(spec["label"], dict(spec, targets=[]))
            if spec["target"] not in group["targets"]:
                group["targets"].append(spec["target"])
        for spec in grouped_cameras.values():
            angle = f"，{spec['view_angle']}" if spec.get("view_angle") else ""
            lines.append(
                f"- {spec['label']}：{spec['location']}，朝{spec['direction']}{angle}；"
                f"主要拍摄{'；'.join(spec['targets'])}。"
            )

    extra_rules = review.get("user_visible_rules", [])
    rules = [
        _humanize(item, labels)
        for item in extra_rules
        if isinstance(item, str) and item.strip()
    ] if isinstance(extra_rules, list) else []
    if not rules:
        for zone in scene_map.get("occupancy_zones", []):
            if not isinstance(zone, dict) or zone.get("access") != "forbidden":
                continue
            subjects = "、".join(_name(item, labels) for item in zone.get("applies_to", []))
            reason = _humanize(zone.get("reason", "不得进入该区域"), labels)
            rules.append(f"{subjects or '相关人物'}不能进入该区域：{reason}")
    if not rules:
        rules.append("不得改变上述起点、走位顺序和最终位置。")

    lines.extend(["", "**必须保持**", ""])
    lines.extend(f"- {rule.rstrip('。')}。" for rule in rules)
    lines.extend([
        "", ("这个空间和走位是否正确？" if review_type == "layout" else "这些机位与拍摄方向是否正确？"), "",
        "回复“确认”，或直接告诉我哪里需要修改。", "",
    ])
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="从 scene_map 生成用户可读的场景空间确认稿")
    parser.add_argument("scene_map", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--review-type", choices=("layout", "camera_plan"), default="layout")
    args = parser.parse_args(argv)
    try:
        scene_map = json.loads(args.scene_map.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    report = spatial.inspect(scene_map)
    if report["status"] != "通过":
        for error in report["errors"]:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_text_map(scene_map, args.review_type), encoding="utf-8")
    print(f"rendered: {args.output}")
    print(f"scene_map_signature: {scene_signature(scene_map, args.review_type)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
