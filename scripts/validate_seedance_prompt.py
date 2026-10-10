#!/usr/bin/env python3
"""Validate the user-confirmed Seedance 2.5 direct-model prompt contract."""

from __future__ import annotations

import argparse
import json
import re
import sys

import adapter_config


REQUIRED_SECTIONS = (
    "全局声音与字幕约束",
    "一句话概述",
    "全局视觉设定",
    "详细情节",
    "全局连续性与结尾约束",
)
SECTION_RE = re.compile(r"(?m)^【([^】]+)】[ \t]*")
MATERIAL_RE = re.compile(r"(?m)^\s*@图片(\d+)\s*[：:]\s*(.+)$")
RANGE_RE = re.compile(r"(?m)^\s*(\d+)\s*[—\-–]\s*(\d+)秒\s*[｜|]\s*(镜头\d+|路径节点\d+|阶段\d+|节拍\d+)\s*$")
MULTI_FIELDS = ("画面动作概述", "画面构图", "机位", "动作/表演", "对白", "声音")
ADAPTER = adapter_config.by_contract("seedance-2.5-direct-v1")
if ADAPTER is None:  # pragma: no cover
    raise RuntimeError("missing seedance-2.5-direct-v1 adapter config")
DEFAULT_MIN_DURATION = adapter_config.limit(ADAPTER, "unit_duration_seconds", "min")
DEFAULT_MAX_DURATION = adapter_config.limit(ADAPTER, "unit_duration_seconds", "max")


def _section_contents(text):
    hits = list(SECTION_RE.finditer(text))
    return {
        hit.group(1): text[hit.end(): hits[index + 1].start() if index + 1 < len(hits) else len(text)].strip()
        for index, hit in enumerate(hits)
    }


def validate_text(text, min_duration=DEFAULT_MIN_DURATION, max_duration=DEFAULT_MAX_DURATION):
    issues = []
    error = lambda code, message: issues.append({"level": "ERROR", "code": code, "message": message})
    warning = lambda code, message: issues.append({"level": "WARNING", "code": code, "message": message})

    headers = [match.group(1) for match in SECTION_RE.finditer(text)]
    if not text.lstrip().startswith("【全局声音与字幕约束】"):
        error("opening-section", "Prompt 必须以【全局声音与字幕约束】开头")
    duplicates = sorted({name for name in headers if headers.count(name) > 1})
    if duplicates:
        error("duplicate-section", f"章节只能出现一次: {duplicates}")
    missing = [name for name in REQUIRED_SECTIONS if name not in headers]
    if missing:
        error("missing-section", f"缺少章节: {missing}")
    expected = ["全局声音与字幕约束"]
    if "素材说明" in headers:
        expected.append("素材说明")
    expected.extend(REQUIRED_SECTIONS[1:])
    known_order = [name for name in headers if name in set(expected)]
    if known_order != expected:
        error("section-order", f"章节顺序错误，应为: {' -> '.join(expected)}")
    unknown = [name for name in headers if name not in set(expected)]
    if unknown:
        warning("unknown-section", f"存在契约外章节: {unknown}")

    sections = _section_contents(text)
    empty = [name for name in expected if name in sections and not sections[name]]
    if empty:
        error("empty-section", f"章节不能为空: {empty}")

    materials = MATERIAL_RE.findall(sections.get("素材说明", ""))
    if "素材说明" in headers and not materials:
        error("material-empty", "使用素材说明时至少声明一个 @图片N")
    if materials:
        numbers = [int(number) for number, _ in materials]
        if numbers != list(range(1, len(numbers) + 1)):
            error("material-order", f"@图片N 必须按上传顺序从 1 连续编号，当前={numbers}")
        for number, description in materials:
            if "参考" not in description or "不参考" not in description:
                error("material-boundary", f"@图片{number} 必须同时声明参考与不参考边界")
    handles = [int(number) for number in re.findall(r"@图片(\d+)", text)]
    declared = {int(number) for number, _ in materials}
    undeclared = sorted(set(handles) - declared)
    if undeclared:
        error("material-undeclared", f"使用了未在素材说明声明的句柄: {undeclared}")

    overview = sections.get("一句话概述", "")
    single = bool(re.search(r"单镜头|一镜到底", overview))
    multi = bool(re.search(r"\d+\s*个?镜头|多镜头|连续剪辑", overview))
    if single == multi:
        error("shooting-form", "一句话概述必须且只能明确单镜头一镜到底或多镜头剪辑")

    visual = sections.get("全局视觉设定", "")
    for label in ("全局风格", "关键材质与受光表现", "灯光基线"):
        if not re.search(rf"(?m)^\s*{re.escape(label)}\s*[：:]", visual):
            error("visual-field-missing", f"全局视觉设定缺少 {label}")

    detail = sections.get("详细情节", "")
    ranges = [(int(start), int(end), label) for start, end, label in RANGE_RE.findall(detail)]
    if not ranges:
        error("timeline-missing", "详细情节缺少整数秒时间段")
    else:
        if ranges[0][0] != 0:
            error("timeline-start", "第一个时间段必须从 0 秒开始")
        for previous, current in zip(ranges, ranges[1:]):
            if previous[1] != current[0]:
                error("timeline-gap", f"时间段必须连续: {previous[0]}-{previous[1]} 后接 {current[0]}-{current[1]}")
        if any(end <= start for start, end, _ in ranges):
            error("timeline-range", "每个时间段的结束秒必须大于开始秒")
        duration = ranges[-1][1]
        if duration < min_duration or duration > max_duration:
            error("duration-contract", f"总时长 {duration} 秒超出用户提供的项目契约 {min_duration}-{max_duration} 秒")

    if single:
        if not re.search(r"全程单镜头.*无剪辑", detail):
            error("single-declaration", "一镜到底详细情节必须声明全程单镜头、无剪辑")
        if any(label.startswith("镜头") for _, _, label in ranges):
            error("single-label", "一镜到底时间段必须使用路径节点、阶段或节拍")
        if re.search(r"硬切|跳切|换机位|瞬移", detail):
            error("single-cut-leak", "一镜到底不得包含剪辑、换机位或瞬移指令")
    if multi:
        if any(not label.startswith("镜头") for _, _, label in ranges):
            error("multi-label", "多镜头时间段必须使用镜头N")
        blocks = re.split(RANGE_RE, detail)[1:]
        bodies = blocks[3::4] if blocks else []
        for index, body in enumerate(bodies, 1):
            positions = []
            for field in MULTI_FIELDS:
                match = re.search(rf"(?m)^\s*{re.escape(field)}\s*[：:]", body)
                if not match:
                    error("shot-field-missing", f"镜头{index} 缺少字段 {field}")
                else:
                    positions.append(match.start())
            if positions and positions != sorted(positions):
                error("shot-field-order", f"镜头{index} 字段顺序错误")
            if index < len(bodies) and not re.search(r"(?m)^\s*转场\s*[：:]", body):
                error("transition-missing", f"镜头{index} 缺少转场")

    return issues


def main(argv=None):
    parser = argparse.ArgumentParser(description="校验 Seedance 2.5 直接模型 Prompt")
    parser.add_argument("files", nargs="+", help="待校验文件；- 表示标准输入")
    parser.add_argument("--min-duration", type=int, default=DEFAULT_MIN_DURATION)
    parser.add_argument("--max-duration", type=int, default=DEFAULT_MAX_DURATION)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report, failed = {}, False
    for path in args.files:
        try:
            text = sys.stdin.read() if path == "-" else open(path, encoding="utf-8").read()
        except OSError as exc:
            report[path] = {"issues": [{"level": "ERROR", "code": "read", "message": str(exc)}]}
            failed = True
            continue
        issues = validate_text(text, args.min_duration, args.max_duration)
        report[path] = {"issues": issues}
        failed |= any(item["level"] == "ERROR" for item in issues)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for path, result in report.items():
            print(f"[{path}]")
            if not result["issues"]:
                print("  PASS  无 ERROR / WARNING")
            for item in result["issues"]:
                print(f"  {item['level']:<7} [{item['code']}] {item['message']}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
