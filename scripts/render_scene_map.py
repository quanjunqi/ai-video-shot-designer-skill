#!/usr/bin/env python3
"""Render a read-only SVG review projection from a scene_map JSON file."""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
import textwrap
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPATIAL_SCRIPT = ROOT / "scripts" / "check_spatial_contract.py"
_spec = importlib.util.spec_from_file_location("check_spatial_contract", SPATIAL_SCRIPT)
if _spec is None or _spec.loader is None:  # pragma: no cover
    raise ImportError(f"cannot load {SPATIAL_SCRIPT}")
spatial = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(spatial)

SVG_NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG_NS)


def _tag(name):
    return f"{{{SVG_NS}}}{name}"


def _add(parent, name, attrs=None, text=None):
    node = ET.SubElement(parent, _tag(name), attrs or {})
    if text is not None:
        node.text = str(text)
    return node


def _points_from_scene(scene_map):
    points = []
    for collection in ("fixed_anchors", "objects"):
        for item in scene_map.get(collection, []):
            point = spatial._entity_coords(item)
            if point:
                points.append(point)
    for collection in ("walkable_zones", "occupancy_zones"):
        for zone in scene_map.get(collection, []):
            polygon = spatial._polygon_points(zone.get("polygon")) if isinstance(zone, dict) else None
            if polygon:
                points.extend(polygon)
    for _, camera in spatial._camera_items(scene_map.get("camera", {})):
        point = spatial._entity_coords(camera)
        if point:
            points.append(point)
    return points or [{"x": -5.0, "y": -5.0}, {"x": 5.0, "y": 5.0}]


def render_scene_map(scene_map, shot_id=None):
    width, height = 1100, 760
    left, top, plot_width, plot_height = 70, 80, 780, 620
    points = _points_from_scene(scene_map)
    min_x = min(point["x"] for point in points) - 1.0
    max_x = max(point["x"] for point in points) + 1.0
    min_y = min(point["y"] for point in points) - 1.0
    max_y = max(point["y"] for point in points) + 1.0
    x_span = max(max_x - min_x, 1.0)
    y_span = max(max_y - min_y, 1.0)

    def project(point):
        return (
            left + (point["x"] - min_x) / x_span * plot_width,
            top + (max_y - point["y"]) / y_span * plot_height,
        )

    root = ET.Element(_tag("svg"), {
        "viewBox": f"0 0 {width} {height}", "width": str(width), "height": str(height),
        "role": "img", "aria-label": f"Scene map review for {scene_map.get('scene_id', 'unknown')}",
    })
    _add(root, "rect", {"width": "100%", "height": "100%", "fill": "#f7f8f6"})
    _add(root, "text", {"x": "70", "y": "42", "font-size": "24", "font-family": "sans-serif",
                        "font-weight": "700", "fill": "#17211b"},
         f"空间审阅投影 · {scene_map.get('scene_id', 'unknown')}")
    subtitle = f"主轴：{scene_map.get('primary_axis', '未定义')}"
    if shot_id:
        subtitle += f" · 镜头：{shot_id}"
    _add(root, "text", {"x": "70", "y": "66", "font-size": "14", "font-family": "sans-serif",
                        "fill": "#4b5750"}, subtitle)
    _add(root, "rect", {"x": str(left), "y": str(top), "width": str(plot_width), "height": str(plot_height),
                        "fill": "#ffffff", "stroke": "#aeb8b1", "stroke-width": "1"})

    for zone in scene_map.get("walkable_zones", []):
        polygon = spatial._polygon_points(zone.get("polygon")) if isinstance(zone, dict) else None
        if polygon:
            rendered = " ".join(f"{project(point)[0]:.1f},{project(point)[1]:.1f}" for point in polygon)
            _add(root, "polygon", {"points": rendered, "fill": "#dcefe4", "stroke": "#4e8a65", "stroke-width": "2"})

    for zone in scene_map.get("occupancy_zones", []):
        if not isinstance(zone, dict):
            continue
        polygon = spatial._polygon_points(zone.get("polygon"))
        if not polygon:
            continue
        rendered = " ".join(f"{project(point)[0]:.1f},{project(point)[1]:.1f}" for point in polygon)
        forbidden = zone.get("access") == "forbidden"
        _add(root, "polygon", {
            "points": rendered, "fill": "#f6c9c9" if forbidden else "#dcefe4", "fill-opacity": "0.72",
            "stroke": "#b34040" if forbidden else "#4e8a65", "stroke-width": "2", "stroke-dasharray": "7 5",
        })
        center_x = sum(project(point)[0] for point in polygon) / len(polygon)
        center_y = sum(project(point)[1] for point in polygon) / len(polygon)
        _add(root, "text", {"x": f"{center_x:.1f}", "y": f"{center_y:.1f}", "text-anchor": "middle",
                            "font-size": "13", "font-family": "sans-serif", "fill": "#842b2b"},
             f"{zone.get('zone_id')} · {'禁入' if forbidden else '允许'}")

    persistent_ids = {item.get("anchor_id") for item in scene_map.get("persistent_landmarks", [])
                      if isinstance(item, dict)}
    for anchor in scene_map.get("fixed_anchors", []):
        point = spatial._entity_coords(anchor)
        if not point:
            continue
        x, y = project(point)
        anchor_id = anchor.get("anchor_id", "anchor")
        if anchor_id in persistent_ids:
            _add(root, "circle", {"cx": f"{x:.1f}", "cy": f"{y:.1f}", "r": "12", "fill": "none",
                                  "stroke": "#bb6b21", "stroke-width": "3"})
        _add(root, "rect", {"x": f"{x - 6:.1f}", "y": f"{y - 6:.1f}", "width": "12", "height": "12",
                            "fill": "#f2b84b", "stroke": "#70480d"})
        _add(root, "text", {"x": f"{x + 10:.1f}", "y": f"{y - 8:.1f}", "font-size": "13",
                            "font-family": "sans-serif", "fill": "#3c2b12"}, anchor_id)

    camera_items = dict(spatial._camera_items(scene_map.get("camera", {})))
    selected_camera = camera_items.get(shot_id) if shot_id else None
    state_id = selected_camera.get("blocking_state_id") if isinstance(selected_camera, dict) else None
    positions = spatial._anchor_positions(scene_map, state_id)
    object_by_id = {item.get("object_id"): item for item in scene_map.get("objects", [])
                    if isinstance(item, dict) and item.get("object_id")}
    object_stacks = {}
    for object_id, obj in object_by_id.items():
        point = positions.get(object_id)
        if not point:
            continue
        x, y = project(point)
        stack_key = (round(x, 1), round(y, 1))
        stack_index = object_stacks.get(stack_key, 0)
        object_stacks[stack_key] = stack_index + 1
        marker_x = x + stack_index * 8
        marker_y = y + stack_index * 8
        is_character = obj.get("object_type") in {"character", "person"}
        _add(root, "circle", {"cx": f"{marker_x:.1f}", "cy": f"{marker_y:.1f}", "r": "9" if is_character else "7",
                              "fill": "#276b8e" if is_character else "#72539b", "stroke": "#ffffff", "stroke-width": "2"})
        _add(root, "text", {"x": f"{x + 12:.1f}", "y": f"{y + 20 + stack_index * 18:.1f}", "font-size": "13",
                            "font-family": "sans-serif", "font-weight": "700", "fill": "#1b2730"}, object_id)

    cameras = [(shot_id, selected_camera)] if shot_id and selected_camera else list(camera_items.items())
    for camera_id, camera in cameras:
        if not isinstance(camera, dict):
            continue
        point = spatial._entity_coords(camera)
        bearing = spatial._camera_bearing(camera)
        if not point or bearing is None:
            continue
        x, y = project(point)
        angle = math.radians(bearing)
        dx, dy = math.sin(angle), -math.cos(angle)
        fov = float(camera.get("fov_half", 60))
        for sign in (-1, 1):
            ray_angle = math.radians(bearing + sign * fov)
            _add(root, "line", {"x1": f"{x:.1f}", "y1": f"{y:.1f}",
                                "x2": f"{x + math.sin(ray_angle) * 75:.1f}",
                                "y2": f"{y - math.cos(ray_angle) * 75:.1f}",
                                "stroke": "#b34040", "stroke-width": "1.5", "stroke-dasharray": "5 4"})
        _add(root, "circle", {"cx": f"{x:.1f}", "cy": f"{y:.1f}", "r": "8", "fill": "#b34040"})
        _add(root, "line", {"x1": f"{x:.1f}", "y1": f"{y:.1f}", "x2": f"{x + dx * 28:.1f}",
                            "y2": f"{y + dy * 28:.1f}", "stroke": "#7d2020", "stroke-width": "4"})
        _add(root, "text", {"x": f"{x + 12:.1f}", "y": f"{y + 20:.1f}", "font-size": "12",
                            "font-family": "sans-serif", "fill": "#7d2020"}, camera_id)

    legend_x = 885
    _add(root, "text", {"x": str(legend_x), "y": "105", "font-size": "17", "font-family": "sans-serif",
                        "font-weight": "700", "fill": "#17211b"}, "审阅要点")
    notes = ["绿色：可通行区域", "红色：禁入区域", "橙圈：持久地标", "蓝点：人物",
             "紫点：道具/对象", "红点与虚线：机位/视锥", "本图只读，不进入视频输入"]
    for index, note in enumerate(notes):
        _add(root, "text", {"x": str(legend_x), "y": str(138 + index * 25), "font-size": "13",
                            "font-family": "sans-serif", "fill": "#36423b"}, note)
    for index, scale in enumerate(scene_map.get("scale_anchors", [])):
        if isinstance(scale, dict):
            block_y = 345 + index * 72
            _add(root, "text", {"x": str(legend_x), "y": str(block_y), "font-size": "12",
                                "font-family": "sans-serif", "fill": "#4b5750"},
                 f"尺度：{scale.get('anchor_id')} = {scale.get('real_size_m')}m")
            for line_index, line in enumerate(textwrap.wrap(scale.get("comparison", ""), width=14)):
                _add(root, "text", {"x": str(legend_x), "y": str(block_y + 18 + line_index * 16), "font-size": "11",
                                    "font-family": "sans-serif", "fill": "#68736d"}, line)

    north_x, north_y = left + 28, top + 38
    _add(root, "line", {"x1": str(north_x), "y1": str(north_y + 22), "x2": str(north_x), "y2": str(north_y - 12),
                        "stroke": "#17211b", "stroke-width": "3"})
    _add(root, "text", {"x": str(north_x), "y": str(north_y - 18), "text-anchor": "middle", "font-size": "14",
                        "font-family": "sans-serif", "font-weight": "700", "fill": "#17211b"}, "N")
    return ET.tostring(root, encoding="unicode")


def main(argv=None):
    parser = argparse.ArgumentParser(description="从 scene_map 生成只读 SVG 空间审阅投影")
    parser.add_argument("scene_map", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--shot", help="只渲染指定镜头及其 blocking state")
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
    cameras = dict(spatial._camera_items(scene_map.get("camera", {})))
    if args.shot and args.shot not in cameras:
        print(f"ERROR: 未知镜头 {args.shot}", file=sys.stderr)
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_scene_map(scene_map, args.shot), encoding="utf-8")
    print(f"rendered: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
